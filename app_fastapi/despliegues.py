# -*- coding: utf-8 -*-
"""Modulo opcional MODULO_DESPLIEGUES: gestionar las versiones de los
entornos DEV y PRO desde Configuracion -> Despliegues, sin terminal.

No despliega nada por si mismo: habla con GitHub (el workflow
.github/workflows/despliegue.yml y las releases) con un token que se guarda
cifrado en ajustes_app de la BD REAL, y pregunta a cada entorno su version
en GET /version/. Ver docs/DESPLIEGUE.md."""
from __future__ import annotations

import os
import re

import requests

from . import db
from .nexus import cripto

ENTORNOS = ("dev", "pro")
API = "https://api.github.com"
TIMEOUT = 10
_CIFRADO = "cifrado:"
_PREFIJO = "despliegue."
# los ajustes van a la BD REAL (el panel no cambia con el entorno de datos);
# los tests lo ponen a False, como escritorio_servicios.USAR_BD_REAL
USAR_BD_REAL = True


class DespliegueError(Exception):
    """Algo que se le puede contar tal cual a quien usa el panel."""


# ── ajustes (BD real: el panel es el mismo en los dos entornos de datos) ─────

def _clave() -> str:
    clave = os.getenv("SESSION_SECRET_KEY", "").strip()
    if not clave:
        raise DespliegueError("Falta SESSION_SECRET_KEY en el .env: sin ella no se puede guardar el token cifrado.")
    return clave


def ajustes() -> dict:
    a = {k: db.get_ajuste(_PREFIJO + k, "", real=USAR_BD_REAL) or "" for k in
         ("repo", "rama", "workflow", "token", *(f"url_{e}" for e in ENTORNOS))}
    a["rama"] = a["rama"] or "main"
    a["workflow"] = a["workflow"] or "despliegue.yml"
    a["token_guardado"] = bool(a.pop("token"))
    return a


def guardar_ajustes(form: dict) -> None:
    repo = (form.get("repo") or "").strip().strip("/")
    repo = re.sub(r"^https?://github\.com/", "", repo).removesuffix(".git")
    if repo and not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise DespliegueError("El repositorio va como usuario/nombre (p. ej. miusuario/app_tareas).")
    db.set_ajuste(_PREFIJO + "repo", repo, real=USAR_BD_REAL)
    db.set_ajuste(_PREFIJO + "rama", (form.get("rama") or "main").strip(), real=USAR_BD_REAL)
    db.set_ajuste(_PREFIJO + "workflow", (form.get("workflow") or "despliegue.yml").strip(), real=USAR_BD_REAL)
    for e in ENTORNOS:
        url = (form.get(f"url_{e}") or "").strip().rstrip("/")
        if url and not url.startswith(("http://", "https://")):
            raise DespliegueError(f"La dirección de {e.upper()} tiene que empezar por https://")
        db.set_ajuste(_PREFIJO + f"url_{e}", url, real=USAR_BD_REAL)
    token = (form.get("token") or "").strip()
    if token:  # vacio = conservar el que habia
        db.set_ajuste(_PREFIJO + "token", _CIFRADO + cripto.cifrar(_clave(), token), real=USAR_BD_REAL)


def _token() -> str:
    guardado = db.get_ajuste(_PREFIJO + "token", "", real=USAR_BD_REAL) or ""
    if not guardado:
        raise DespliegueError("Falta el token de GitHub (abajo, en Conexión con GitHub).")
    claro = cripto.descifrar(_clave(), guardado[len(_CIFRADO):])
    if claro is None:
        raise DespliegueError("No se puede leer el token guardado (¿ha cambiado SESSION_SECRET_KEY?). Vuelve a escribirlo.")
    return claro


def configurado(a: dict | None = None) -> bool:
    a = a or ajustes()
    return bool(a["repo"] and a["token_guardado"])


# ── GitHub ───────────────────────────────────────────────────────────────────

def _github(metodo: str, ruta: str, **kw):
    """ruta relativa al repositorio ('/releases') o absoluta en la API ('//user')."""
    repo = ajustes()["repo"]
    if not repo:
        raise DespliegueError("Falta el repositorio de GitHub (abajo, en Conexión con GitHub).")
    url = f"{API}{ruta[1:]}" if ruta.startswith("//") else f"{API}/repos/{repo}{ruta}"
    try:
        r = requests.request(metodo, url, timeout=TIMEOUT, headers={
            "Authorization": f"Bearer {_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }, **kw)
    except requests.RequestException as e:
        raise DespliegueError(f"No se puede hablar con GitHub: {e}") from e
    if r.status_code in (401, 403):
        raise DespliegueError("GitHub no acepta el token: revisa que no haya caducado y que tenga los permisos de docs/DESPLIEGUE.md.")
    if r.status_code == 404:
        raise DespliegueError("GitHub no encuentra el repositorio o el workflow (¿nombre correcto? ¿el token ve ese repo?).")
    if r.status_code >= 400:
        try:
            detalle = r.json().get("message", "")
        except ValueError:
            detalle = r.text[:200]
        raise DespliegueError(f"GitHub respondió {r.status_code}: {detalle}")
    return r.json() if r.content else None


def versiones(limite: int = 10) -> list[dict]:
    datos = _github("GET", f"/releases?per_page={limite}") or []
    return [{"version": v["tag_name"], "nombre": v.get("name") or v["tag_name"], "fecha": (v.get("published_at") or "")[:10],
             "url": v.get("html_url", ""), "borrador": v.get("draft", False)} for v in datos]


def ejecuciones(limite: int = 8) -> list[dict]:
    a = ajustes()
    datos = _github("GET", f"/actions/workflows/{a['workflow']}/runs?per_page={limite}") or {}
    salida = []
    for r in datos.get("workflow_runs", []):
        e = {"id": r["id"], "titulo": r.get("display_title") or r.get("name", ""), "evento": r.get("event", ""),
             "estado": r.get("status", ""), "resultado": r.get("conclusion") or "", "url": r.get("html_url", ""),
             "fecha": (r.get("created_at") or "").replace("T", " ")[:16], "pendientes": []}
        if e["estado"] == "waiting":
            for p in _github("GET", f"/actions/runs/{r['id']}/pending_deployments") or []:
                e["pendientes"].append({"entorno": p["environment"]["name"], "entorno_id": p["environment"]["id"],
                                        "puede": p.get("current_user_can_approve", False)})
        salida.append(e)
    return salida


_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def siguiente_version(ultima: str | None, tipo: str) -> str:
    """'v1.2.3' + patch -> 'v1.2.4'; minor -> 'v1.3.0'; major -> 'v2.0.0'.
    Sin versiones previas (o con un nombre raro) se empieza en v1.0.0."""
    m = _SEMVER.match(ultima or "")
    if not m:
        return "v1.0.0"
    mayor, menor, parche = map(int, m.groups())
    if tipo == "major":
        return f"v{mayor + 1}.0.0"
    if tipo == "minor":
        return f"v{mayor}.{menor + 1}.0"
    return f"v{mayor}.{menor}.{parche + 1}"


def crear_version(tipo: str, notas: str = "") -> str:
    """Publica una release nueva sobre la rama principal: el workflow la
    construye y deja PRO esperando aprobacion."""
    if tipo not in ("patch", "minor", "major"):
        raise DespliegueError("Tipo de versión desconocido.")
    publicadas = [v["version"] for v in versiones(30) if not v["borrador"] and _SEMVER.match(v["version"])]
    ordenadas = sorted(publicadas, key=lambda v: tuple(map(int, _SEMVER.match(v).groups())), reverse=True)
    nueva = siguiente_version(ordenadas[0] if ordenadas else None, tipo)
    _github("POST", "/releases", json={
        "tag_name": nueva, "target_commitish": ajustes()["rama"], "name": nueva,
        "body": notas.strip(), "generate_release_notes": True,
    })
    return nueva


def desplegar(entorno: str, version: str) -> None:
    """Lanza el workflow a mano: esa version (ya construida) en ese entorno.
    version='anterior' = rollback a la ultima buena."""
    if entorno not in ENTORNOS:
        raise DespliegueError("Entorno desconocido.")
    version = (version or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", version):
        raise DespliegueError("Versión no válida.")
    a = ajustes()
    _github("POST", f"/actions/workflows/{a['workflow']}/dispatches",
            json={"ref": a["rama"], "inputs": {"entorno": entorno, "version": version}})


def revisar(run_id: int, entorno_id: int, aprobar: bool) -> None:
    _github("POST", f"/actions/runs/{int(run_id)}/pending_deployments", json={
        "environment_ids": [int(entorno_id)], "state": "approved" if aprobar else "rejected",
        "comment": "Desde el panel de despliegues de la app",
    })


def preparar_entornos() -> None:
    """Crea en GitHub los entornos dev y pro; en pro, el dueño del token
    tiene que aprobar cada despliegue. Repetirlo no cambia nada."""
    yo = _github("GET", "//user") or {}
    for e in ENTORNOS:
        cuerpo = {"reviewers": [{"type": "User", "id": yo["id"]}]} if e == "pro" and yo.get("id") else {}
        _github("PUT", f"/environments/{e}", json=cuerpo)


# ── version de cada entorno (GET <url>/version/) ─────────────────────────────

def version_de(url: str) -> dict:
    if not url:
        return {"version": "", "ok": None, "detalle": "sin dirección"}
    try:
        r = requests.get(f"{url}/version/", timeout=5)
        r.raise_for_status()
        return {"version": r.json().get("version", "?"), "ok": True, "detalle": ""}
    except (requests.RequestException, ValueError) as e:
        return {"version": "", "ok": False, "detalle": "no responde" if isinstance(e, requests.RequestException) else "respuesta rara"}


def panel() -> dict:
    """Todo lo que pinta la pestaña; los fallos de GitHub van en 'error' en
    vez de romper la pagina."""
    a = ajustes()
    datos = {"ajustes": a, "configurado": configurado(a), "error": "",
             "entornos": [{"nombre": e, "url": a[f"url_{e}"], **version_de(a[f"url_{e}"])} for e in ENTORNOS],
             "versiones": [], "ejecuciones": []}
    if datos["configurado"]:
        try:
            datos["versiones"] = versiones()
            datos["ejecuciones"] = ejecuciones()
        except DespliegueError as e:
            datos["error"] = str(e)
    return datos
