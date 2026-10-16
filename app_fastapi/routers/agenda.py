# -*- coding: utf-8 -*-
"""Agenda -- hub de un dia CUALQUIERA (no solo los que tienen una reunion
sincronizada): tareas con fecha_fin ese dia + notas ancladas a esa fecha +
una pizarra vinculada, mas las reuniones sincronizadas de ese dia si las
hay. Mismo patron que routers/reunion.py (que es el mismo hub pero atado a
una reunion real de Outlook), copiado y adaptado -- ver CLAUDE.md, seccion
Agenda.

A proposito NO hay comprobacion de "propiedad" como en reunion.py
(_reunion_del_usuario): una fecha no pertenece a nadie, a diferencia de una
reunion real con dueno.

Calendario y el Home (main.py::inicio) consultan estas mismas funciones de
db.py (load_tasks_by_due_date, load_reuniones_calendario) para "que hay
hoy" -- ninguno de los dos vuelve a escribir esa consulta por su cuenta."""
import uuid

from fastapi import APIRouter, Depends, Form
from fastapi.requests import Request
from fastapi.responses import RedirectResponse

from .. import acciones, auth, db
from ..templating import templates

router = APIRouter(prefix="/agenda", tags=["agenda"])

NOTA_COLOR_PALETTE = ["#fef9c3", "#fecdd3", "#bfdbfe", "#bbf7d0", "#e9d5ff", "#fed7aa"]


@router.get("/{fecha}/")
def agenda_detalle(fecha: str, request: Request, usuario: str = Depends(auth.requiere_login)):
    tareas_dia = []
    for t in db.load_tasks_by_due_date(fecha, fecha):
        columnas = db.load_board_columns(t["proyecto_id"])
        hecha = any(c["nombre"] == t["status"] and c["es_done"] for c in columnas)
        toggle_estado = (
            next((c["nombre"] for c in columnas if not c["es_done"]), "Pendiente") if hecha
            else next((c["nombre"] for c in columnas if c["es_done"]), t["status"])
        )
        tareas_dia.append({"task": t, "hecha": hecha, "toggle_estado": toggle_estado})

    reuniones_dia = [
        {"reunion_id": r["reunion_id"], "titulo": r["titulo"],
         "hora": r["fecha_inicio"].split(" ")[1] if " " in r["fecha_inicio"] else ""}
        for r in db.load_reuniones_calendario(usuario, fecha, fecha)
    ]

    return templates.TemplateResponse(request, "agenda_detalle.html", {
        "usuario": usuario, "activo": None,
        "fecha": fecha,
        "reuniones_dia": reuniones_dia,
        "whiteboard_vinculada": db.get_whiteboard_by_agenda_fecha(fecha),
        "whiteboards_disponibles": [w for w in db.load_whiteboards() if not w["reunion_id"] and not w["agenda_fecha"]],
        "tareas_dia": tareas_dia,
        "notas_dia": [n for n in db.load_notas() if n["agenda_fecha"] == fecha],
    })


@router.post("/{fecha}/tarea/anadir/")
def agenda_task_quick_add(fecha: str, request: Request, title: str = Form(""), usuario: str = Depends(auth.requiere_login)):
    """Alta rapida de una tarea REAL del Kanban (proyecto 'general', mismo
    catch-all que otros flujos de esta app), con fecha_fin=fecha -- asi
    aparece igual en el Calendario normal ese mismo dia, sin necesitar
    ninguna columna/comprobacion especial en ningun otro sitio."""
    title = title.strip()
    if title and db.get_proyecto("general"):
        acciones.crear_tarea(acciones.Actor.web(request, usuario), "general", title, fecha_fin=fecha)
    return RedirectResponse(url=f"/agenda/{fecha}/", status_code=303)


@router.post("/{fecha}/nota/anadir/")
def agenda_note_quick_add(fecha: str, titulo: str = Form(""), usuario: str = Depends(auth.requiere_login)):
    """Alta rapida de una nota REAL (misma tabla/galeria de Notas de
    siempre), anclada a esa fecha -- mismo criterio que
    reunion_note_quick_add: se sigue viendo en /notas/, no es un duplicado
    aparte."""
    titulo = titulo.strip()
    if titulo:
        db.crear_nota(
            nota_id=str(uuid.uuid4())[:8], titulo=titulo, contenido="",
            color=NOTA_COLOR_PALETTE[0], agenda_fecha=fecha,
        )
    return RedirectResponse(url=f"/agenda/{fecha}/", status_code=303)


@router.post("/{fecha}/pizarra/vincular/")
def agenda_vincular_whiteboard(
    fecha: str, whiteboard_id: str = Form(""), usuario: str = Depends(auth.requiere_login),
):
    if whiteboard_id:
        db.set_whiteboard_agenda_fecha(whiteboard_id, fecha)
    return RedirectResponse(url=f"/agenda/{fecha}/", status_code=303)
