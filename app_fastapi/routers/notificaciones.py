# -*- coding: utf-8 -*-
"""Campana de notificaciones de la cabecera (_base.html) -- fase 1 de
mensajeria, igual que la de CS Manager: un contador que el navegador
consulta cada pocos segundos (/notificaciones/resumen), un desplegable con
las ultimas, y la lista completa, que al abrirla las marca todas como
leidas. Los textos los genera notificar.py."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from fastapi.requests import Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import auth, db
from ..templating import templates

router = APIRouter(prefix="/notificaciones", tags=["notificaciones"])


@router.get("/resumen")
def resumen(usuario: str = Depends(auth.requiere_login)):
    user_id = db.get_user_id(usuario)
    if not user_id:
        return JSONResponse({"sin_leer": 0, "ultima_id": 0, "ultimas": [], "buzon_sin_leer": 0, "muros_sin_leer": 0})
    db.generar_recordatorios_buzon(user_id)  # los recordatorios de notas que vencen nacen aqui, sin hilo aparte
    datos = db.resumen_notificaciones(user_id)
    datos["buzon_sin_leer"] = db.contar_buzon_sin_leer(user_id)
    datos["muros_sin_leer"] = sum(db.contar_muros_sin_leer(user_id).values())
    return JSONResponse(datos)


@router.get("/")
def lista(request: Request, usuario: str = Depends(auth.requiere_login)):
    user_id = db.get_user_id(usuario)
    notificaciones = db.load_notificaciones(user_id) if user_id else []
    if user_id:
        db.marcar_notificaciones_leidas(user_id)  # entrar a la lista completa = todas leidas (igual que CS Manager)
    return templates.TemplateResponse(request, "notificaciones.html", {
        "usuario": usuario, "activo": "notificaciones", "notificaciones": notificaciones,
        "hoy": date.today().isoformat(), "ayer": (date.today() - timedelta(days=1)).isoformat(),
    })


@router.post("/leer-todas/")
def leer_todas(request: Request, usuario: str = Depends(auth.requiere_login)):
    user_id = db.get_user_id(usuario)
    if user_id:
        db.marcar_notificaciones_leidas(user_id)
    volver = request.headers.get("referer", "/")
    return RedirectResponse(url=volver if volver.startswith(str(request.base_url)) else "/", status_code=303)
