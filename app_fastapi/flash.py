# -*- coding: utf-8 -*-
"""Mensajes flash, equivalente a django.contrib.messages (messages.success/
warning/error) -- una ruta llama a flash(request, "success", "texto") antes
de responder (el caso real es justo antes de un RedirectResponse, patron
post/redirect/get) y el siguiente render de _base.html los pinta una vez y
los descarta, igual que Django (FallbackStorage: se leen y se borran).

Vive en la sesion de Starlette -- la misma que ya usa csrf.py para guardar
el token -- que se firma y persiste sola en la cookie de sesion al final de
CADA respuesta (incluidas las redirecciones), con tal de mutar el dict en
sitio (nunca reasignar request.session = ...). No hace falta nada nuevo en
main.py: SessionMiddleware ya esta instalado desde que existe csrf.py."""
from fastapi import Request

_SESSION_KEY = "_flash_messages"

# Mismos 3 tags que estilos tiene static/css/main.css::.django-message-*
# (success/warning/error) -- Django admite tambien debug/info pero esta app
# nunca los usa (grep de messages.debug/messages.info en core/views.py: 0
# resultados), asi que no hace falta portar esos estilos.
TAG_SUCCESS = "success"
TAG_WARNING = "warning"
TAG_ERROR = "error"


def flash(request: Request, tag: str, texto: str) -> None:
    request.session.setdefault(_SESSION_KEY, []).append({"tags": tag, "texto": texto})


def pop_flashed(request: Request) -> list:
    return request.session.pop(_SESSION_KEY, [])
