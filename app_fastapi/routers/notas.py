# -*- coding: utf-8 -*-
"""Notas -- CRUD completo, copiado del comportamiento de core/views.py
(notas/nota_new/nota_edit/nota_delete) + core/templates/notas.html.
Mismo patron de siempre: formularios normales (POST + redirect), no JSON/
fetch -- igual que el original, no una reescritura a API."""
import uuid

from fastapi import APIRouter, Depends, Form
from fastapi.requests import Request
from fastapi.responses import RedirectResponse

from .. import auth, db
from ..templating import templates

router = APIRouter(prefix="/notas", tags=["notas"])

# Misma paleta que NOTA_COLOR_PALETTE en core/models.py
NOTA_COLOR_PALETTE = ["#fef9c3", "#fecdd3", "#bfdbfe", "#bbf7d0", "#e9d5ff", "#fed7aa"]


@router.get("/")
def listar_notas(request: Request, usuario: str = Depends(auth.requiere_login)):
    return templates.TemplateResponse(request, "notas.html", {
        "notas": db.load_notas(), "nota_colors": NOTA_COLOR_PALETTE,
        "usuario": usuario, "activo": "notas",
    })


@router.post("/nueva/")
def crear_nota(
    titulo: str = Form(""),
    contenido: str = Form(""),
    color: str = Form(""),
    usuario: str = Depends(auth.requiere_login),
):
    titulo = titulo.strip()
    if titulo:
        db.crear_nota(
            nota_id=str(uuid.uuid4())[:8], titulo=titulo,
            contenido=contenido.strip(), color=color or NOTA_COLOR_PALETTE[0],
        )
    return RedirectResponse(url="/notas/", status_code=303)


@router.post("/{nota_id}/editar/")
def editar_nota(
    nota_id: str,
    titulo: str = Form(None),
    contenido: str = Form(None),
    color: str = Form(None),
    usuario: str = Depends(auth.requiere_login),
):
    actual = next((n for n in db.load_notas() if n["nota_id"] == nota_id), None)
    if actual:
        db.editar_nota(
            nota_id=nota_id,
            titulo=(titulo.strip() if titulo is not None else actual["titulo"]),
            contenido=(contenido.strip() if contenido is not None else actual["contenido"]),
            color=(color if color is not None else actual["color"]),
        )
    return RedirectResponse(url="/notas/", status_code=303)


@router.post("/{nota_id}/eliminar/")
def eliminar_nota(nota_id: str, usuario: str = Depends(auth.requiere_login)):
    db.eliminar_nota(nota_id)
    return RedirectResponse(url="/notas/", status_code=303)
