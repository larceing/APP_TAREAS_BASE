# -*- coding: utf-8 -*-
"""Configuracion -> Despliegues (modulo opcional MODULO_DESPLIEGUES): crear
una version, ponerla en un entorno, volver atras y aprobar el paso a PRO,
todo a traves de GitHub (ver despliegues.py). El panel lo pinta
configuracion.html (tipo=despliegues); aqui solo los POST. Solo IT."""
from fastapi import APIRouter, Depends
from fastapi.requests import Request
from fastapi.responses import RedirectResponse

from .. import auth, despliegues
from ..flash import flash

router = APIRouter(prefix="/configuracion/despliegues", tags=["despliegues"], dependencies=[Depends(auth.requiere_it)])

_NOMBRE = {"dev": "DEV", "pro": "PRO"}


def _volver() -> RedirectResponse:
    return RedirectResponse(url="/configuracion/?tipo=despliegues", status_code=303)


@router.post("/ajustes/")
async def guardar_ajustes(request: Request, usuario: str = Depends(auth.requiere_login)):
    form = await request.form()
    try:
        despliegues.guardar_ajustes(dict(form))
        flash(request, "success", "Conexión con GitHub guardada.")
    except despliegues.DespliegueError as e:
        flash(request, "error", str(e))
    return _volver()


@router.post("/preparar-github/")
def preparar_github(request: Request, usuario: str = Depends(auth.requiere_login)):
    try:
        despliegues.preparar_entornos()
        flash(request, "success", "Entornos dev y pro creados en GitHub; PRO pedirá tu aprobación.")
    except despliegues.DespliegueError as e:
        flash(request, "error", str(e))
    return _volver()


@router.post("/nueva-version/")
async def crear_version(request: Request, usuario: str = Depends(auth.requiere_login)):
    form = await request.form()
    try:
        nueva = despliegues.crear_version(form.get("tipo", ""), form.get("notas", ""))
        flash(request, "success", f"Versión {nueva} creada. Se está construyendo; en unos minutos "
                                  "aparecerá aquí arriba para que la apruebes y llegue a PRO.")
    except despliegues.DespliegueError as e:
        flash(request, "error", str(e))
    return _volver()


@router.post("/desplegar/")
async def desplegar(request: Request, usuario: str = Depends(auth.requiere_login)):
    form = await request.form()
    entorno, version = form.get("entorno", ""), (form.get("version") or "").strip()
    try:
        despliegues.desplegar(entorno, version)
        que = "la versión anterior" if version == "anterior" else version
        flash(request, "success", f"Pedido: {que} en {_NOMBRE.get(entorno, entorno)}. Tarda unos minutos; "
                                  + ("en PRO hay que aprobarlo abajo." if entorno == "pro" else "lo verás en Ejecuciones."))
    except despliegues.DespliegueError as e:
        flash(request, "error", str(e))
    return _volver()


@router.post("/revisar/")
async def revisar(request: Request, usuario: str = Depends(auth.requiere_login)):
    form = await request.form()
    aprobar = form.get("decision") == "aprobar"
    try:
        despliegues.revisar(int(form.get("run_id", 0)), int(form.get("entorno_id", 0)), aprobar)
        flash(request, "success", "Aprobado: se está desplegando." if aprobar else "Rechazado: no se despliega.")
    except (despliegues.DespliegueError, ValueError) as e:
        flash(request, "error", str(e) or "Datos no válidos.")
    return _volver()


# ── otras apps ───────────────────────────────────────────────────────────────

_ESPERA = " Tarda unos minutos: el resultado sale abajo, en Otras aplicaciones → Últimas peticiones."


@router.post("/apps/nueva/")
async def app_nueva(request: Request, usuario: str = Depends(auth.requiere_login)):
    form = await request.form()
    try:
        ruta = despliegues.app_nueva(dict(form))
        flash(request, "success", f"Pedido: crear /{ruta}/ en DEV y PRO, con su login y sus grupos." + _ESPERA)
    except despliegues.DespliegueError as e:
        flash(request, "error", str(e))
    return _volver()


@router.post("/apps/desplegar/")
async def app_desplegar(request: Request, usuario: str = Depends(auth.requiere_login)):
    form = await request.form()
    ruta, entorno, version = form.get("ruta", ""), form.get("entorno", ""), (form.get("version") or "").strip()
    try:
        despliegues.app_desplegar(ruta, entorno, version)
        que = "la versión anterior" if version == "anterior" else version
        flash(request, "success", f"Pedido: {que} de /{ruta}/ en {_NOMBRE.get(entorno, entorno)}." + _ESPERA)
    except despliegues.DespliegueError as e:
        flash(request, "error", str(e))
    return _volver()


@router.post("/apps/dominio/")
async def app_dominio(request: Request, usuario: str = Depends(auth.requiere_login)):
    form = await request.form()
    try:
        dominio = despliegues.app_dominio(form.get("ruta", ""), form.get("dominio", ""))
        flash(request, "success", f"Pedido: {dominio} para {form.get('ruta')} en PRO, con certificado y login." + _ESPERA)
    except despliegues.DespliegueError as e:
        flash(request, "error", str(e))
    return _volver()
