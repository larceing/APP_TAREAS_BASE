# -*- coding: utf-8 -*-
"""Pantalla de login real (formulario + sesion), copiada de
core/templates/login.html -- sustituye al HTTP Basic del principio (que no
tenia pantalla propia, el navegador sacaba su popup nativo en cada
peticion). La verificacion de usuario/contrasena sigue siendo la misma
(auth.py, contra auth_user); lo unico nuevo aqui es guardar el resultado en
una sesion (cookie firmada, ver main.py) para no volver a pedirlo en cada
peticion."""
from fastapi import APIRouter, Form
from fastapi.requests import Request
from fastapi.responses import RedirectResponse

from .. import auth
from ..templating import templates

router = APIRouter(tags=["login"])


def _next_seguro(next_url: str) -> str:
    """El destino tras el login viene de la propia URL (?next=...) -- se
    exige que sea una ruta relativa de esta misma app, nunca una URL
    absoluta/externa (evita usarlo como redirect abierto)."""
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return "/"


@router.get("/login/")
def formulario_login(request: Request, next: str = "/"):
    if request.session.get("usuario"):
        return RedirectResponse(url=_next_seguro(next))
    return templates.TemplateResponse(request, "login.html", {"error": False, "next": _next_seguro(next)})


@router.post("/login/")
def procesar_login(
    request: Request, username: str = Form(...), password: str = Form(...), next: str = Form("/"),
):
    next_url = _next_seguro(next)
    usuario, es_it = auth.verificar_credenciales(username, password)
    if not usuario:
        return templates.TemplateResponse(request, "login.html", {"error": True, "next": next_url})
    auth.iniciar_sesion(request, usuario, es_it)
    return RedirectResponse(url=next_url, status_code=303)


@router.get("/logout/")
def cerrar_sesion(request: Request):
    auth.cerrar_sesion(request)
    return RedirectResponse(url="/login/")
