# -*- coding: utf-8 -*-
"""Ajustes del servidor (modulo opcional MODULO_DESPLIEGUES): las versiones
de todas las apps del servidor en DEV y PRO, pasar a PRO, volver atras y
aprobar, todo a traves de GitHub (ver despliegues.py). Lo abre el boton
Ajustes de la portada. Solo IT global (auth.requiere_admin_global): ser
Admin de una sola app no basta.

Vive en /ajustes/ de la raiz del dominio (https://pro.dominio/ajustes/), no
dentro de /tareas/: es del servidor, no de Tareas, aunque lo sirva esta app.
La entrada lo manda aqui sin X-Forwarded-Prefix (ruta_base lo deja pasar
tal cual) y con X-Ruta-App, donde esta Tareas, para el login y Salir. La
pagina (servidor.html) no lleva nada de Tareas: ni su menu ni su nombre."""
from fastapi import APIRouter, Depends
from fastapi.requests import Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
import re

from .. import auth, config, despliegues, ruta_base
from ..flash import flash
from ..templating import templates

router = APIRouter(prefix="/ajustes", tags=["despliegues"])
_solo_it = [Depends(auth.requiere_admin_global)]

_NOMBRE = {"dev": "DEV", "pro": "PRO"}


def _volver() -> RedirectResponse:
    return RedirectResponse(url="/ajustes/", status_code=303)


def _raiz(request: Request) -> str:
    """https://<el dominio por el que se ha entrado>, sin la ruta de Tareas."""
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "https").split(",")[0].strip()
    host = request.headers.get("host", "")
    return f"{proto}://{host}" if host else ""


def _ruta_app(request: Request) -> str:
    """Donde esta Tareas en este dominio (/tareas, o nada si va en su propio
    dominio): lo dice la entrada en X-Ruta-App, si no APP_RUTA_BASE."""
    return ruta_base._normalizar(request.headers.get("x-ruta-app", "")) or ruta_base.ruta_base()


@router.get("/acceso/")
def acceso(request: Request):
    """Para las portadas estaticas de antes: quien la mira y si es IT global.
    Sin sesion: usuario null y admin false, sin pedir login."""
    return JSONResponse({"usuario": request.session.get("usuario") or request.session.get("portada_usuario") or None,
                         "admin": auth.es_admin_global_sesion(request)}, headers={"Cache-Control": "no-store"})


# ── la portada del entorno (https://pro.dominio/) ────────────────────────────
# La entrada manda "/" aqui (location = /) con la lista de apps en
# X-Portada-Apps ("ruta|nombre|salud|grupo;...", de sus apps/*.conf, ver
# tareas.sh escribir_entrada_conf). Sin sesion no se ensena nada: al login.
# Cada uno ve solo las apps de sus grupos de Keycloak (el grupo o un
# subgrupo); IT global las ve todas, con su version, y el boton Ajustes.

_RUTA_APP = re.compile(r"^[a-z][a-z0-9-]{0,30}$")
_SALUD = re.compile(r"^[A-Za-z0-9._/-]*$")


def _apps_de_la_entrada(request: Request) -> list:
    crudo = request.headers.get("x-portada-apps", "")
    try:
        crudo = crudo.encode("latin-1").decode("utf-8")   # nginx manda los bytes tal cual
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    apps = []
    for trozo in crudo.split(";"):
        partes = (trozo.split("|") + ["", "", "", ""])[:4]
        ruta, nombre, salud, grupo = (x.strip() for x in partes)
        if not _RUTA_APP.match(ruta):
            continue
        salud = salud.lstrip("/") if _SALUD.match(salud) else "version/"
        apps.append({"ruta": ruta, "nombre": nombre or ruta, "salud": salud or "version/", "grupo": grupo.strip("/")})
    return apps


def _puede_ver(app: dict, grupos: list, admin: bool, tiene_tareas: bool) -> bool:
    if admin:
        return True
    if app["ruta"] == "tareas":
        return tiene_tareas
    g = app["grupo"]
    return bool(g) and any(x == g or x.startswith(g + "/") for x in grupos)


@router.get("/portada-entorno/")
def ver_portada(request: Request):
    ruta_app = _ruta_app(request)
    usuario = request.session.get("usuario") or request.session.get("portada_usuario") or ""
    if not usuario:
        return RedirectResponse(url=ruta_app + "/login/?next=/portada/", status_code=303,
                                headers={"Cache-Control": "no-store"})
    admin = auth.es_admin_global_sesion(request)
    grupos = request.session.get("grupos") or []
    apps = [a for a in _apps_de_la_entrada(request)
            if _puede_ver(a, grupos, admin, bool(request.session.get("usuario")))]
    entorno = request.headers.get("x-portada-entorno", "")
    entorno = entorno if re.match(r"^[a-z]{2,10}$", entorno) else ""
    panel = request.headers.get("x-portada-ajustes", "") or "/ajustes/"
    if not (panel.startswith("https://") or panel.startswith("/")) or '"' in panel or "<" in panel:
        panel = "/ajustes/"
    r = templates.TemplateResponse(request, "portada.html", {
        "usuario": usuario, "admin": admin, "apps": apps, "entorno": entorno,
        "ruta_app": ruta_app, "panel": panel})
    r.headers["Cache-Control"] = "no-store"
    return r


def _usuario(request: Request) -> str:
    return request.session.get("usuario") or ""


def _es_admin(request: Request) -> bool:
    return auth.es_admin_global_sesion(request)


@router.get("/")
def ver_panel(request: Request, usuario: str = Depends(_usuario), admin: bool = Depends(_es_admin)):
    """Sin sesion no se manda al /login/ de siempre (en la raiz no hay
    Tareas): al de Tareas, y sin permiso se dice aqui mismo."""
    if request.scope.get("ruta_base"):
        # entrado por /tareas/ajustes/ (despues del login, o un enlace viejo):
        # a la de la raiz del dominio, que es la buena
        return RedirectResponse(url=_raiz(request) + "/ajustes/", status_code=303)
    ruta_app = _ruta_app(request)
    if not usuario:
        # el login es el de Tareas; al acabar vuelve aqui
        return RedirectResponse(url=ruta_app + "/login/?next=/ajustes/", status_code=303)
    datos = {"usuario": usuario, "ruta_app": ruta_app, "portada": "/" if request.headers.get("x-ruta-app") else (config.app_url_portal() or "/")}
    if not admin:
        return templates.TemplateResponse(request, "servidor.html", dict(datos, sin_permiso=True), status_code=403)
    return templates.TemplateResponse(request, "servidor.html", dict(datos, despliegue=despliegues.panel()))


@router.post("/github/", dependencies=_solo_it)
async def guardar_ajustes(request: Request):
    form = await request.form()
    try:
        despliegues.guardar_ajustes(dict(form))
        flash(request, "success", "Conexión con GitHub guardada.")
    except despliegues.DespliegueError as e:
        flash(request, "error", str(e))
    return _volver()


@router.post("/preparar-github/", dependencies=_solo_it)
def preparar_github(request: Request):
    try:
        despliegues.preparar_entornos()
        flash(request, "success", "Entornos dev y pro creados en GitHub; PRO pedirá tu aprobación.")
    except despliegues.DespliegueError as e:
        flash(request, "error", str(e))
    return _volver()


@router.post("/nueva-version/", dependencies=_solo_it)
async def crear_version(request: Request):
    """Tareas: versión nueva (release); con a_pro se aprueba sola para PRO."""
    form = await request.form()
    try:
        nueva = despliegues.crear_version(form.get("tipo", ""), form.get("notas", ""))
        if form.get("a_pro"):
            despliegues.aprobar_en_segundo_plano(nueva)
            flash(request, "success", f"Versión {nueva} creada. Se está construyendo y pasará sola a PRO "
                                      "(unos 5 minutos); la tarjeta lo dirá con el punto verde.")
        else:
            flash(request, "success", f"Versión {nueva} creada. Se está construyendo; en unos minutos "
                                      "aparecerá aquí arriba para que la apruebes y llegue a PRO.")
    except despliegues.DespliegueError as e:
        flash(request, "error", str(e))
    return _volver()


@router.post("/pasar-a-pro/", dependencies=_solo_it)
async def pasar_a_pro(request: Request):
    """Cualquier otra app: lo que tiene DEV pasa a PRO."""
    form = await request.form()
    ruta = form.get("ruta", "")
    try:
        version = despliegues.pasar_a_pro(ruta)
        flash(request, "success", f"Pedido: {version} de {ruta} en PRO. Tarda unos minutos; si su workflow pide "
                                  "aprobación, se aprueba sola.")
    except despliegues.DespliegueError as e:
        flash(request, "error", str(e))
    return _volver()


@router.post("/poner/", dependencies=_solo_it)
async def poner(request: Request):
    """Una versión concreta (o "anterior") de una app en un entorno."""
    form = await request.form()
    ruta, entorno, version = form.get("ruta", "tareas"), form.get("entorno", ""), (form.get("version") or "").strip()
    try:
        app = despliegues.poner_version(ruta, entorno, version)
        que = "la versión anterior" if version == "anterior" else version
        flash(request, "success", f"Pedido: {que} de {app['nombre']} en {_NOMBRE.get(entorno, entorno)}. Tarda unos minutos"
                                  + ("; en PRO puede que haya que aprobarlo arriba." if entorno == "pro" else "."))
    except despliegues.DespliegueError as e:
        flash(request, "error", str(e))
    return _volver()


@router.post("/revisar/", dependencies=_solo_it)
async def revisar(request: Request):
    form = await request.form()
    aprobar = form.get("decision") == "aprobar"
    try:
        despliegues.revisar(int(form.get("run_id", 0)), int(form.get("entorno_id", 0)), aprobar, repo=form.get("repo", ""))
        flash(request, "success", "Aprobado: se está desplegando." if aprobar else "Rechazado: no se despliega.")
    except (despliegues.DespliegueError, ValueError) as e:
        flash(request, "error", str(e) or "Datos no válidos.")
    return _volver()


# ── apps de otros repositorios ───────────────────────────────────────────────

@router.post("/externas/guardar/", dependencies=_solo_it)
async def externa_guardar(request: Request):
    form = await request.form()
    try:
        ruta = despliegues.externa_guardar(dict(form))
        flash(request, "success", f"/{ruta}/ añadida al panel. Recuerda que el token de GitHub tiene que ver su repositorio.")
    except despliegues.DespliegueError as e:
        flash(request, "error", str(e))
    return _volver()


@router.post("/externas/quitar/", dependencies=_solo_it)
async def externa_quitar(request: Request):
    form = await request.form()
    despliegues.externa_quitar(form.get("ruta", ""))
    flash(request, "success", "Quitada del panel (en el servidor sigue igual).")
    return _volver()


# ── apps creadas desde el panel (apps.yml) ───────────────────────────────────

_ESPERA = " Tarda unos minutos: el resultado sale abajo, en Últimas peticiones."


@router.post("/apps/nueva/", dependencies=_solo_it)
async def app_nueva(request: Request):
    form = await request.form()
    try:
        ruta = despliegues.app_nueva(dict(form))
        flash(request, "success", f"Pedido: crear /{ruta}/ en DEV y PRO, con su login y sus grupos." + _ESPERA)
    except despliegues.DespliegueError as e:
        flash(request, "error", str(e))
    return _volver()


@router.post("/apps/dominio/", dependencies=_solo_it)
async def app_dominio(request: Request):
    form = await request.form()
    try:
        dominio = despliegues.app_dominio(form.get("ruta", ""), form.get("dominio", ""))
        flash(request, "success", f"Pedido: {dominio} para {form.get('ruta')} en PRO, con certificado y login." + _ESPERA)
    except despliegues.DespliegueError as e:
        flash(request, "error", str(e))
    return _volver()


# ── la direccion de antes (/tareas/servidor/) ────────────────────────────────
# Las portadas que aun no se han rehecho (tareas.sh portada) preguntan aqui.

antiguo = APIRouter(prefix="/servidor", tags=["despliegues"])
antiguo.add_api_route("/acceso/", acceso, methods=["GET"])


@antiguo.get("/")
def a_ajustes(request: Request):
    return RedirectResponse(url=_raiz(request) + "/ajustes/", status_code=303)
