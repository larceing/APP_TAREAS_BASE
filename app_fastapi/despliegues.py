# -*- coding: utf-8 -*-
"""Modulo opcional MODULO_DESPLIEGUES: gestionar las versiones de los
entornos DEV y PRO desde Configuracion -> Despliegues, sin terminal.

No despliega nada por si mismo: habla con GitHub (el workflow
.github/workflows/despliegue.yml y las releases) con un token que se guarda
cifrado en ajustes_app de la BD REAL, y pregunta a cada entorno su version
en GET /version/. Ver docs/DESPLIEGUE.md."""
from __future__ import annotations

import logging
import os
import re
import threading
import time

import requests

from . import db
from .nexus import cripto

ENTORNOS = ("dev", "pro")
WORKFLOW_APPS = "apps.yml"   # .github/workflows/apps.yml: otras apps del servidor
API = "https://api.github.com"
TIMEOUT = 10
_CIFRADO = "cifrado:"
_PREFIJO = "despliegue."
# los ajustes van a la BD REAL (el panel no cambia con el entorno de datos);
# los tests lo ponen a False, como escritorio_servicios.USAR_BD_REAL
USAR_BD_REAL = True


log = logging.getLogger(__name__)


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


def aprobar_cuando_llegue(version: str, cada: int = 15, hasta: int = 1500, dormir=time.sleep) -> bool:
    """Espera a que la release 'version' deje PRO esperando aprobacion y la
    aprueba: quien pulsa "Pasar a PRO" en el panel ya ha decidido, no hace
    falta un segundo clic. Si la ejecucion acaba antes (fallan las pruebas),
    no hay nada que aprobar. True si la aprobo."""
    t = 0
    while t <= hasta:
        try:
            a = ajustes()
            datos = _github("GET", f"/actions/workflows/{a['workflow']}/runs?event=release&per_page=10") or {}
            for r in datos.get("workflow_runs", []):
                if r.get("head_branch") != version:
                    continue
                if r.get("status") == "completed":
                    log.info("despliegue %s: la ejecución acabó (%s) sin pedir aprobación", version, r.get("conclusion"))
                    return False
                if r.get("status") == "waiting":
                    for p in _github("GET", f"/actions/runs/{r['id']}/pending_deployments") or []:
                        if p["environment"]["name"] == "pro" and p.get("current_user_can_approve"):
                            revisar(r["id"], p["environment"]["id"], True)
                            log.info("despliegue %s: aprobado para PRO desde el panel", version)
                            return True
        except DespliegueError as e:
            log.warning("despliegue %s: %s", version, e)
        dormir(cada)
        t += cada
    log.warning("despliegue %s: no llegó a pedir aprobación; queda para aprobar a mano en el panel", version)
    return False


def aprobar_en_segundo_plano(version: str) -> None:
    threading.Thread(target=aprobar_cuando_llegue, args=(version,), daemon=True,
                     name=f"aprobar-{version}").start()


def preparar_entornos() -> None:
    """Crea en GitHub los entornos dev y pro; en pro, el dueño del token
    tiene que aprobar cada despliegue. Repetirlo no cambia nada."""
    yo = _github("GET", "//user") or {}
    for e in ENTORNOS:
        cuerpo = {"reviewers": [{"type": "User", "id": yo["id"]}]} if e == "pro" and yo.get("id") else {}
        _github("PUT", f"/environments/{e}", json=cuerpo)


# ── otras apps (workflow apps.yml -> tareas.sh app-nueva/app-desplegar/dominio)

_RUTA_APP = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
_DOMINIO = re.compile(r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")
_NOMBRE_APP = re.compile(r"^[\w\s.()-]{1,60}$")


def apps() -> list[dict]:
    """Las apps creadas desde el panel (ruta, nombre, imagen)."""
    import json
    try:
        datos = json.loads(db.get_ajuste(_PREFIJO + "apps", "[]", real=USAR_BD_REAL) or "[]")
    except ValueError:
        datos = []
    return [a for a in datos if isinstance(a, dict) and _RUTA_APP.match(a.get("ruta", ""))]


def _guardar_app(ruta: str, nombre: str, imagen: str) -> None:
    import json
    lista = [a for a in apps() if a["ruta"] != ruta] + [{"ruta": ruta, "nombre": nombre, "imagen": imagen}]
    db.set_ajuste(_PREFIJO + "apps", json.dumps(sorted(lista, key=lambda a: a["ruta"])), real=USAR_BD_REAL)


def _pedir_apps(inputs: dict) -> None:
    _github("POST", f"/actions/workflows/{WORKFLOW_APPS}/dispatches",
            json={"ref": ajustes()["rama"], "inputs": {k: v for k, v in inputs.items() if v}})


def app_nueva(form: dict) -> str:
    ruta = (form.get("ruta") or "").strip().lower().strip("/")
    nombre = (form.get("nombre") or "").strip() or ruta.capitalize()
    imagen = (form.get("imagen") or "").strip().lower()
    puerto = (form.get("puerto") or "8000").strip()
    salud = (form.get("salud") or "").strip().lstrip("/")
    if not _RUTA_APP.match(ruta) or ruta in ("tareas", "auth", "version"):
        raise DespliegueError("La ruta va en minúsculas, con letras, números o guiones (p. ej. inventario), y no puede ser tareas.")
    if not _NOMBRE_APP.match(nombre):
        raise DespliegueError("El nombre: hasta 60 letras, números, espacios, puntos, guiones o paréntesis.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9./_-]+", imagen) or ":" in imagen:
        raise DespliegueError("La imagen va sin versión, p. ej. ghcr.io/usuario/inventario.")
    if not re.fullmatch(r"\d{2,5}", puerto):
        raise DespliegueError("El puerto es un número (p. ej. 8000).")
    if not re.fullmatch(r"[A-Za-z0-9._/-]*", salud):
        raise DespliegueError("El camino de comprobación solo lleva letras, números, / . _ -")
    _pedir_apps({"accion": "nueva", "app": ruta, "nombre": nombre, "imagen": imagen, "puerto": puerto, "salud": salud})
    _guardar_app(ruta, nombre, imagen)
    return ruta


def app_desplegar(ruta: str, entorno: str, version: str) -> None:
    version = (version or "").strip()
    if ruta not in {a["ruta"] for a in apps()}:
        raise DespliegueError("Esa app no está creada desde este panel.")
    if entorno not in ENTORNOS:
        raise DespliegueError("Entorno desconocido.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", version):
        raise DespliegueError("Versión no válida.")
    _pedir_apps({"accion": "desplegar", "app": ruta, "entorno": entorno, "version": version})


def app_dominio(ruta: str, dominio: str) -> str:
    dominio = (dominio or "").strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0]
    if ruta != "tareas" and ruta not in {a["ruta"] for a in apps()}:
        raise DespliegueError("Elige una app de la lista.")
    if not _DOMINIO.match(dominio):
        raise DespliegueError("El dominio va sin https://, p. ej. inventario.midominio.com.")
    _pedir_apps({"accion": "dominio", "app": ruta, "dominio": dominio})
    return dominio


def ejecuciones_apps(limite: int = 6) -> list[dict]:
    datos = _github("GET", f"/actions/workflows/{WORKFLOW_APPS}/runs?per_page={limite}") or {}
    return [{"id": r["id"], "titulo": r.get("display_title") or r.get("name", ""), "estado": r.get("status", ""),
             "resultado": r.get("conclusion") or "", "url": r.get("html_url", ""),
             "fecha": (r.get("created_at") or "").replace("T", " ")[:16]} for r in datos.get("workflow_runs", [])]


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
             "versiones": [], "ejecuciones": [], "apps": apps(), "ejecuciones_apps": []}
    if datos["configurado"]:
        try:
            datos["versiones"] = versiones()
            datos["ejecuciones"] = ejecuciones()
        except DespliegueError as e:
            datos["error"] = str(e)
        try:
            datos["ejecuciones_apps"] = ejecuciones_apps()
        except DespliegueError:
            pass  # sin apps.yml en el repositorio todavia: la seccion sale vacia
    return datos
