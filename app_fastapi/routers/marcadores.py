# -*- coding: utf-8 -*-
"""Marcadores: accesos directos PERSONALES a cualquier URL de la app (un
tablero, un sprint filtrado, el SLA de Mantis...) -- ver
scripts/schema_app_tareas.sql para el porque de que 'url' pueda llevar un
query param 'abrir=...' (reabre un modal concreto al llegar, ver
tablero.html). Solo dos rutas: crear/eliminar -- la lista se pinta con el
global de Jinja templating.py::marcadores_activos(), no hace falta una
pagina propia."""
import uuid

from fastapi import APIRouter, Depends, Form
from fastapi.requests import Request
from fastapi.responses import RedirectResponse

from .. import auth, db

router = APIRouter(tags=["marcadores"])


@router.post("/marcadores/nuevo/")
def crear_marcador(
    request: Request, titulo: str = Form(...), url: str = Form(...),
    usuario: str = Depends(auth.requiere_login),
):
    user_id = db.get_user_id(usuario)
    # Solo rutas relativas propias de la app -- nunca un dominio externo
    # (evita que esto se use como un open-redirect encubierto).
    if user_id and titulo.strip() and url.strip().startswith("/") and not url.strip().startswith("//"):
        db.crear_marcador(str(uuid.uuid4())[:8], user_id, titulo.strip()[:150], url.strip()[:500])
    referer = request.headers.get("referer") or "/"
    return RedirectResponse(url=referer, status_code=303)


@router.post("/marcadores/{marcador_id}/eliminar/")
def eliminar_marcador(request: Request, marcador_id: str, usuario: str = Depends(auth.requiere_login)):
    user_id = db.get_user_id(usuario)
    if user_id:
        db.eliminar_marcador(marcador_id, user_id)
    referer = request.headers.get("referer") or "/"
    return RedirectResponse(url=referer, status_code=303)
