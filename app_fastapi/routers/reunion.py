# -*- coding: utf-8 -*-
"""Reunion -- hub de una reunion sincronizada desde el calendario externo
(ICS): pizarra + tareas rapidas + notas rapidas, todas etiquetadas con el
mismo reunion_id. Copiado de core/views.py::reunion_detail/
reunion_task_quick_add/reunion_vincular_whiteboard/reunion_note_quick_add +
core/templates/reunion_detail.html.

Diferencia deliberada de seguridad frente al original: el original SOLO
comprueba en reunion_detail que la reunion pertenece al usuario logueado --
las otras 3 rutas (anadir tarea, anadir nota, vincular pizarra) no lo hacen,
así que cualquier usuario autenticado que adivinara/copiara un reunion_id
ajeno podria escribir en el hub de otra persona. Aqui las 4 rutas comprueban
propiedad (404 si no coincide), cerrando ese hueco en vez de copiarlo tal
cual -- decision tomada en este port (app de un solo usuario en la practica,
pero la comprobacion no cuesta nada y evita el hueco de raiz)."""
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.requests import Request
from fastapi.responses import RedirectResponse

from .. import acciones, auth, db
from ..templating import templates

router = APIRouter(prefix="/reunion", tags=["reunion"])

NOTA_COLOR_PALETTE = ["#fef9c3", "#fecdd3", "#bfdbfe", "#bbf7d0", "#e9d5ff", "#fed7aa"]


def _reunion_del_usuario(reunion_id: str, usuario: str) -> dict:
    reunion = db.get_reunion_calendario(reunion_id)
    if not reunion or reunion["usuario"] != usuario:
        raise HTTPException(status_code=404)
    return reunion


@router.get("/{reunion_id}/")
def reunion_detail(reunion_id: str, request: Request, usuario: str = Depends(auth.requiere_login)):
    reunion = _reunion_del_usuario(reunion_id, usuario)

    tareas_reunion = []
    for t in db.load_tasks_by_reunion(reunion_id):
        columnas = db.load_board_columns(t["proyecto_id"])
        hecha = any(c["nombre"] == t["status"] and c["es_done"] for c in columnas)
        toggle_estado = (
            next((c["nombre"] for c in columnas if not c["es_done"]), "Pendiente") if hecha
            else next((c["nombre"] for c in columnas if c["es_done"]), t["status"])
        )
        tareas_reunion.append({"task": t, "hecha": hecha, "toggle_estado": toggle_estado})

    return templates.TemplateResponse(request, "reunion_detail.html", {
        "usuario": usuario, "activo": None,
        "reunion": reunion,
        "whiteboard_vinculada": db.get_whiteboard_by_reunion(reunion_id),
        "whiteboards_disponibles": [w for w in db.load_whiteboards() if not w["reunion_id"]],
        "tareas_reunion": tareas_reunion,
        "notas_reunion": [n for n in db.load_notas() if n["reunion_id"] == reunion_id],
    })


@router.post("/{reunion_id}/tarea/anadir/")
def reunion_task_quick_add(reunion_id: str, request: Request, title: str = Form(""), usuario: str = Depends(auth.requiere_login)):
    """Alta rapida de una tarea REAL del Kanban (proyecto 'general', mismo
    catch-all que otros flujos de esta app), solo etiquetada a la reunion --
    no es un checklist aparte, sigue viendose en el tablero de siempre."""
    _reunion_del_usuario(reunion_id, usuario)
    title = title.strip()
    if title and db.get_proyecto("general"):
        acciones.crear_tarea(acciones.Actor.web(request, usuario), "general", title, reunion_id=reunion_id)
    return RedirectResponse(url=f"/reunion/{reunion_id}/", status_code=303)


@router.post("/{reunion_id}/nota/anadir/")
def reunion_note_quick_add(reunion_id: str, titulo: str = Form(""), usuario: str = Depends(auth.requiere_login)):
    """Alta rapida de una nota REAL (misma tabla/galeria de Notas de
    siempre), solo etiquetada a la reunion -- mismo criterio que
    reunion_task_quick_add: se sigue viendo en /notas/, no es un duplicado
    aparte."""
    _reunion_del_usuario(reunion_id, usuario)
    titulo = titulo.strip()
    if titulo:
        db.crear_nota(
            nota_id=str(uuid.uuid4())[:8], titulo=titulo, contenido="",
            color=NOTA_COLOR_PALETTE[0], reunion_id=reunion_id,
        )
    return RedirectResponse(url=f"/reunion/{reunion_id}/", status_code=303)


@router.post("/{reunion_id}/pizarra/vincular/")
def reunion_vincular_whiteboard(
    reunion_id: str, whiteboard_id: str = Form(""), usuario: str = Depends(auth.requiere_login),
):
    _reunion_del_usuario(reunion_id, usuario)
    if whiteboard_id:
        db.set_whiteboard_reunion(whiteboard_id, reunion_id)
    return RedirectResponse(url=f"/reunion/{reunion_id}/", status_code=303)
