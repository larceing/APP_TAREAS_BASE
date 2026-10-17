# -*- coding: utf-8 -*-
"""Modulo opcional MODULO_DESPLIEGUES: el panel de Ajustes del servidor
(/servidor/, el boton Ajustes de la portada, solo IT global). Las versiones
de TODAS las apps del servidor en DEV y PRO, sin terminal.

No despliega nada por si mismo: habla con GitHub (los workflows y las
releases de cada repositorio) con un token que se guarda cifrado en
ajustes_app de la BD REAL, y pregunta a cada app su version en
<portada>/<ruta>/version/. Cada app es una entrada del catalogo (ver
catalogo()): Tareas, las creadas con apps.yml y las que tienen su propio
repositorio y workflow, que se dan de alta en el panel sin tocar su codigo.
Ver docs/DESPLIEGUE.md."""
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
         ("repo", "rama", "workflow", "token", *(f"url_{e}" for e in ENTORNOS), *(f"portada_{e}" for e in ENTORNOS))}
    a["rama"] = a["rama"] or "main"
    a["workflow"] = a["workflow"] or "despliegue.yml"
    a["token_guardado"] = bool(a.pop("token"))
    for e in ENTORNOS:  # sin portada propia: la del dominio de Tareas (https://dev.x.com/tareas -> https://dev.x.com)
        a[f"portada_{e}_efectiva"] = a[f"portada_{e}"] or _origen(a[f"url_{e}"])
    return a


def _origen(url: str) -> str:
    from urllib.parse import urlparse
    u = urlparse(url or "")
    return f"{u.scheme}://{u.netloc}" if u.scheme and u.netloc else ""


def guardar_ajustes(form: dict) -> None:
    repo = (form.get("repo") or "").strip().strip("/")
    repo = re.sub(r"^https?://github\.com/", "", repo).removesuffix(".git")
    if repo and not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise DespliegueError("El repositorio va como usuario/nombre (p. ej. miusuario/app_tareas).")
    db.set_ajuste(_PREFIJO + "repo", repo, real=USAR_BD_REAL)
    db.set_ajuste(_PREFIJO + "rama", (form.get("rama") or "main").strip(), real=USAR_BD_REAL)
    db.set_ajuste(_PREFIJO + "workflow", (form.get("workflow") or "despliegue.yml").strip(), real=USAR_BD_REAL)
    for e in ENTORNOS:
        for campo, que in ((f"url_{e}", f"La dirección de {e.upper()}"), (f"portada_{e}", f"La portada de {e.upper()}")):
            if campo not in form:
                continue  # el formulario no lo trae: se queda como estaba
            url = (form.get(campo) or "").strip().rstrip("/")
            if url and not url.startswith(("http://", "https://")):
                raise DespliegueError(f"{que} tiene que empezar por https://")
            db.set_ajuste(_PREFIJO + campo, url, real=USAR_BD_REAL)
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

def _github(metodo: str, ruta: str, repo: str = "", **kw):
    """ruta relativa al repositorio ('/releases') o absoluta en la API ('//user').
    Sin repo, el de Tareas (Conexión con GitHub)."""
    repo = repo or ajustes()["repo"]
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


def revisar(run_id: int, entorno_id: int, aprobar: bool, repo: str = "") -> None:
    if repo and repo not in {x["repo"] for x in catalogo()}:
        raise DespliegueError("Ese repositorio no es de ninguna app del panel.")
    _github("POST", f"/actions/runs/{int(run_id)}/pending_deployments", repo=repo, json={
        "environment_ids": [int(entorno_id)], "state": "approved" if aprobar else "rejected",
        "comment": "Desde el panel de despliegues de la app",
    })


def _esperar_y_aprobar(que: str, repo: str, workflow: str, evento: str, es_la_mia,
                       cada: int, hasta: int, dormir) -> bool:
    """Espera a que la ejecucion 'es_la_mia(run)' deje PRO esperando
    aprobacion y la aprueba: quien pulsa "Pasar a PRO" en el panel ya ha
    decidido, no hace falta un segundo clic. Si acaba antes (fallan las
    pruebas, o ese workflow no pide aprobacion) no hay nada que aprobar."""
    t = 0
    while t <= hasta:
        try:
            datos = _github("GET", f"/actions/workflows/{workflow}/runs?event={evento}&per_page=10", repo=repo) or {}
            for r in datos.get("workflow_runs", []):
                if not es_la_mia(r):
                    continue
                if r.get("status") == "completed":
                    log.info("despliegue %s: la ejecución acabó (%s) sin pedir aprobación", que, r.get("conclusion"))
                    return False
                if r.get("status") == "waiting":
                    for p in _github("GET", f"/actions/runs/{r['id']}/pending_deployments", repo=repo) or []:
                        if p["environment"]["name"] == "pro" and p.get("current_user_can_approve"):
                            revisar(r["id"], p["environment"]["id"], True, repo=repo)
                            log.info("despliegue %s: aprobado para PRO desde el panel", que)
                            return True
        except DespliegueError as e:
            log.warning("despliegue %s: %s", que, e)
        dormir(cada)
        t += cada
    log.warning("despliegue %s: no llegó a pedir aprobación; queda para aprobar a mano en el panel", que)
    return False


def aprobar_cuando_llegue(version: str, cada: int = 15, hasta: int = 1500, dormir=time.sleep) -> bool:
    """La release 'version' de Tareas. True si la aprobo."""
    a = ajustes()
    return _esperar_y_aprobar(version, a["repo"], a["workflow"], "release",
                              lambda r: r.get("head_branch") == version, cada, hasta, dormir)


def aprobar_en_segundo_plano(version: str) -> None:
    threading.Thread(target=aprobar_cuando_llegue, args=(version,), daemon=True,
                     name=f"aprobar-{version}").start()


def _aprobar_pedido(que: str, repo: str, workflow: str, desde: str, cada: int = 15, hasta: int = 900,
                    dormir=time.sleep) -> bool:
    """Lo mismo para un "Run workflow" pedido desde el panel: la primera
    ejecucion a mano de ese workflow creada desde 'desde' (ISO, UTC)."""
    return _esperar_y_aprobar(que, repo, workflow, "workflow_dispatch",
                              lambda r: (r.get("created_at") or "") >= desde, cada, hasta, dormir)


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


def _guardar_app(ruta: str, nombre: str, imagen: str, salud: str = "") -> None:
    import json
    lista = [a for a in apps() if a["ruta"] != ruta] + [{"ruta": ruta, "nombre": nombre, "imagen": imagen, "salud": salud}]
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
    _guardar_app(ruta, nombre, imagen, salud)
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


# ── apps con su propio repositorio y workflow (p. ej. otro proyecto) ────────
# Se dan de alta en el panel: el workflow de su repo tiene que aceptar
# workflow_dispatch con un campo para el entorno (dev/pro) y otro para la
# version (la etiqueta de su imagen). El token tiene que ver tambien ese repo.

_CAMPO = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,40}$")
_WORKFLOW = re.compile(r"^[\w.-]+\.ya?ml$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def externas() -> list[dict]:
    import json
    try:
        datos = json.loads(db.get_ajuste(_PREFIJO + "externas", "[]", real=USAR_BD_REAL) or "[]")
    except ValueError:
        datos = []
    return [a for a in datos if isinstance(a, dict) and _RUTA_APP.match(a.get("ruta", ""))]


def _guardar_externas(lista: list[dict]) -> None:
    import json
    db.set_ajuste(_PREFIJO + "externas", json.dumps(sorted(lista, key=lambda a: a["ruta"])), real=USAR_BD_REAL)


def externa_guardar(form: dict) -> str:
    ruta = (form.get("ruta") or "").strip().lower().strip("/")
    nombre = (form.get("nombre") or "").strip() or ruta.capitalize()
    repo = re.sub(r"^https?://github\.com/", "", (form.get("repo") or "").strip().strip("/")).removesuffix(".git")
    workflow = (form.get("workflow") or "").strip()
    rama = (form.get("rama") or "").strip() or "main"
    campo_entorno = (form.get("campo_entorno") or "").strip() or "entorno"
    campo_version = (form.get("campo_version") or "").strip() or "version"
    salud = (form.get("salud") or "").strip().lstrip("/") or "version/"
    if not _RUTA_APP.match(ruta) or ruta in ("tareas", "auth", "version", "no-disponible"):
        raise DespliegueError("La ruta es la de la portada, en minúsculas (p. ej. linai para /linai/), y no puede ser tareas.")
    if ruta in {a["ruta"] for a in apps()}:
        raise DespliegueError("Esa ruta ya es de una app creada desde este panel.")
    if not _NOMBRE_APP.match(nombre):
        raise DespliegueError("El nombre: hasta 60 letras, números, espacios, puntos, guiones o paréntesis.")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise DespliegueError("El repositorio va como usuario/nombre (p. ej. miusuario/otro-proyecto).")
    if not _WORKFLOW.match(workflow):
        raise DespliegueError("El workflow es el nombre de su fichero en .github/workflows (p. ej. desplegar.yml).")
    if not re.fullmatch(r"[\w./-]{1,100}", rama):
        raise DespliegueError("Rama no válida.")
    if not (_CAMPO.match(campo_entorno) and _CAMPO.match(campo_version)) or campo_entorno == campo_version:
        raise DespliegueError("Los nombres de los campos del workflow: letras, números, _ o -, y distintos entre sí.")
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", salud):
        raise DespliegueError("El camino de la versión solo lleva letras, números, / . _ -")
    nueva = {"ruta": ruta, "nombre": nombre, "repo": repo, "workflow": workflow, "rama": rama,
             "campo_entorno": campo_entorno, "campo_version": campo_version, "salud": salud,
             "anterior": bool(form.get("anterior"))}
    _guardar_externas([a for a in externas() if a["ruta"] != ruta] + [nueva])
    return ruta


def externa_quitar(ruta: str) -> None:
    """Solo la quita del panel: la app sigue en el servidor como estaba."""
    _guardar_externas([a for a in externas() if a["ruta"] != ruta])


# ── el catalogo: todas las apps del panel, con lo que hace falta para cada una

def catalogo() -> list[dict]:
    """Una entrada por app: Tareas (Conexión con GitHub), las creadas con
    apps.yml (mismo repo que Tareas) y las de su propio repositorio.
    tipo: tareas | servidor | externa."""
    a = ajustes()
    from . import config
    lista = [{"ruta": "tareas", "nombre": config.app_nombre(), "tipo": "tareas", "repo": a["repo"],
              "workflow": a["workflow"], "rama": a["rama"], "salud": "version/", "anterior": True}]
    for x in apps():
        lista.append({"ruta": x["ruta"], "nombre": x["nombre"], "tipo": "servidor", "repo": a["repo"],
                      "workflow": WORKFLOW_APPS, "rama": a["rama"], "salud": x.get("salud") or "version/",
                      "anterior": True, "imagen": x.get("imagen", "")})
    for x in externas():
        lista.append({**x, "tipo": "externa"})
    return lista


def _del_catalogo(ruta: str) -> dict:
    for x in catalogo():
        if x["ruta"] == ruta:
            return x
    raise DespliegueError("Esa app no está en el panel.")


def url_version(app: dict, entorno: str, a: dict | None = None) -> str:
    """Donde pregunta el panel la version de la app en ese entorno."""
    a = a or ajustes()
    if app["tipo"] == "tareas":
        return f"{a[f'url_{entorno}']}/version/" if a[f"url_{entorno}"] else ""
    base = a[f"portada_{entorno}_efectiva"]
    return f"{base}/{app['ruta']}/{app['salud'].lstrip('/')}" if base else ""


def url_app(app: dict, entorno: str, a: dict | None = None) -> str:
    """Donde se abre la app en ese entorno."""
    a = a or ajustes()
    if app["tipo"] == "tareas":
        return f"{a[f'url_{entorno}']}/" if a[f"url_{entorno}"] else ""
    base = a[f"portada_{entorno}_efectiva"]
    return f"{base}/{app['ruta']}/" if base else ""


def poner_version(ruta: str, entorno: str, version: str) -> dict:
    """Esa version de esa app en ese entorno, por el workflow que le toque."""
    app = _del_catalogo(ruta)
    version = (version or "").strip()
    if entorno not in ENTORNOS:
        raise DespliegueError("Entorno desconocido.")
    if not _VERSION.match(version):
        raise DespliegueError("Versión no válida.")
    if version == "anterior" and not app["anterior"]:
        raise DespliegueError(f"El workflow de {app['nombre']} no sabe volver a la anterior: escribe la versión.")
    if app["tipo"] == "tareas":
        desplegar(entorno, version)
    elif app["tipo"] == "servidor":
        app_desplegar(ruta, entorno, version)
    else:
        _github("POST", f"/actions/workflows/{app['workflow']}/dispatches", repo=app["repo"], json={
            "ref": app["rama"], "inputs": {app["campo_entorno"]: entorno, app["campo_version"]: version}})
    return app


def pasar_a_pro(ruta: str, tipo: str = "patch", notas: str = "") -> str:
    """El boton de cada tarjeta. Tareas saca una version nueva (release) que
    llega sola a PRO; el resto pone en PRO la version que DEV dice tener.
    Si el workflow pide aprobacion para PRO, se aprueba solo."""
    from datetime import datetime, timedelta, timezone
    app = _del_catalogo(ruta)
    if app["tipo"] == "tareas":
        nueva = crear_version(tipo, notas)
        aprobar_en_segundo_plano(nueva)
        return nueva
    en_dev = version_de_url(url_version(app, "dev"))
    version = en_dev["version"]
    if not en_dev["ok"] or not _VERSION.match(version or "") or version == "anterior":
        raise DespliegueError(f"No sé qué versión tiene {app['nombre']} en DEV (su {app['salud']} no la dice): "
                              "escríbela en «Poner» de PRO.")
    desde = (datetime.now(timezone.utc) - timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    poner_version(ruta, "pro", version)
    threading.Thread(target=_aprobar_pedido, args=(f"{ruta} {version}", app["repo"], app["workflow"], desde),
                     daemon=True, name=f"aprobar-{ruta}").start()
    return version


def _pendientes(app: dict) -> list[dict]:
    """Ejecuciones de esa app esperando aprobacion."""
    datos = _github("GET", f"/actions/workflows/{app['workflow']}/runs?status=waiting&per_page=5", repo=app["repo"]) or {}
    salida = []
    for r in datos.get("workflow_runs", []):
        for p in _github("GET", f"/actions/runs/{r['id']}/pending_deployments", repo=app["repo"]) or []:
            salida.append({"run_id": r["id"], "titulo": r.get("display_title") or r.get("name", ""), "url": r.get("html_url", ""),
                           "entorno": p["environment"]["name"], "entorno_id": p["environment"]["id"],
                           "puede": p.get("current_user_can_approve", False), "repo": app["repo"]})
    return salida


# ── version de cada entorno (GET <url>/version/) ─────────────────────────────

def version_de(url: str) -> dict:
    """La de Tareas: url es su direccion (sin /version/)."""
    return version_de_url(f"{url}/version/" if url else "")


def version_de_url(url: str) -> dict:
    """GET url: 200 con JSON {"version": ...}, o 200 a secas (responde, sin
    decir version)."""
    if not url:
        return {"version": "", "ok": None, "detalle": "sin dirección"}
    try:
        r = requests.get(url, timeout=5)
        r.raise_for_status()
    except requests.RequestException:
        return {"version": "", "ok": False, "detalle": "no responde"}
    try:
        datos = r.json()
        version = str(datos.get("version") or "") if isinstance(datos, dict) else ""
    except ValueError:
        version = ""
    return {"version": version, "ok": True, "detalle": "" if version else "responde, sin decir versión"}


def panel() -> dict:
    """Todo lo que pinta /servidor/; los fallos de GitHub van en 'error' (o
    en el 'error' de cada app) en vez de romper la pagina."""
    from concurrent.futures import ThreadPoolExecutor
    a = ajustes()
    cat = catalogo()
    datos = {"ajustes": a, "configurado": configurado(a), "error": "",
             "entornos": [{"nombre": e, "url": a[f"url_{e}"], **version_de(a[f"url_{e}"])} for e in ENTORNOS],
             "versiones": [], "ejecuciones": [], "apps": apps(), "externas": externas(), "ejecuciones_apps": [],
             "tarjetas": []}
    # las versiones de cada app en cada entorno, a la vez (cada una tarda lo suyo)
    urls = [(x, e, url_version(x, e, a)) for x in cat for e in ENTORNOS]
    with ThreadPoolExecutor(max_workers=8) as pool:
        respuestas = list(pool.map(lambda t: version_de_url(t[2]), urls))
    for x in cat:
        tarjeta = {**x, "entornos": [], "pendientes": [], "error": ""}
        for (app, e, url), v in zip(urls, respuestas):
            if app is x:
                tarjeta["entornos"].append({"nombre": e, "url": url_app(x, e, a), **v})
        datos["tarjetas"].append(tarjeta)
    if datos["configurado"]:
        try:
            datos["versiones"] = versiones()
            datos["ejecuciones"] = ejecuciones()
            datos["tarjetas"][0]["pendientes"] = [
                {"run_id": e["id"], "titulo": e["titulo"], "url": e["url"], "repo": "", **p}
                for e in datos["ejecuciones"] for p in e["pendientes"]]
        except DespliegueError as e:
            datos["error"] = str(e)
        try:
            datos["ejecuciones_apps"] = ejecuciones_apps()
        except DespliegueError:
            pass  # sin apps.yml en el repositorio todavia: la seccion sale vacia
        for t in datos["tarjetas"]:
            if t["tipo"] == "externa":
                try:
                    t["pendientes"] = _pendientes(t)
                except DespliegueError as e:
                    t["error"] = str(e)
    return datos
