# -*- coding: utf-8 -*-
"""Ajustes del servidor (/servidor/, modulo opcional MODULO_DESPLIEGUES): las
versiones de todas las apps del servidor en DEV y PRO, pasar a PRO, volver
atras y aprobar, todo a traves de GitHub (ver despliegues.py). Lo abre el
boton Ajustes de la portada de cada entorno. Solo IT global
(auth.requiere_admin_global): ser Admin de una sola app no basta."""
from fastapi import APIRouter, Depends
from fastapi.requests import Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import auth, despliegues
from ..flash import flash
from ..templating import templates

router = APIRouter(prefix="/servidor", tags=["despliegues"])
_solo_it = [Depends(auth.requiere_admin_global)]

_NOMBRE = {"dev": "DEV", "pro": "PRO"}


def _volver() -> RedirectResponse:
    return RedirectResponse(url="/servidor/", status_code=303)


@router.get("/acceso/")
def acceso(request: Request):
    """Para la portada (pagina estatica): enseña el boton Ajustes solo si la
    persona que la mira es IT global. Sin sesion responde false, sin login."""
    return JSONResponse({"admin": auth.es_admin_global_sesion(request)}, headers={"Cache-Control": "no-store"})


@router.get("/", dependencies=_solo_it)
def ver_panel(request: Request, usuario: str = Depends(auth.requiere_login)):
    return templates.TemplateResponse(request, "servidor.html", {
        "usuario": usuario, "activo": "servidor", "despliegue": despliegues.panel()})


@router.post("/ajustes/", dependencies=_solo_it)
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
