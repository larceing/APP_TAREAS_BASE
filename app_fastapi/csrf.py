# -*- coding: utf-8 -*-
"""Proteccion CSRF -- patron doble cookie/sesion, sin importar nada de
Django (esta v2 no depende de la app real ni siquiera para esto). El token
vive en la sesion firmada (Starlette SessionMiddleware, tan segura como la
cookie de sesion de Django) y se refleja en una cookie legible por JS con
el MISMO nombre que ya usaba Django (`gestor_csrftoken`, ver
gestor/settings.py::CSRF_COOKIE_NAME) -- el JS ya copiado literal de la app
real (static/js/whiteboard.js, y varios fetch() de otras plantillas)
llamaba a getCookie('gestor_csrftoken') + mandaba el header X-CSRFToken sin
que hiciera nada hasta ahora; con esto empiezan a funcionar de verdad.

Se aplica como dependency GLOBAL (ver main.py::FastAPI(dependencies=...)),
asi que corre en TODA peticion sin tener que tocar cada router uno a uno.
Solo valida en POST -- esta app no usa PUT/PATCH/DELETE -- y nunca en
/api/, que se autentica con X-API-Key sin sesion/cookies de por medio,
igual que Django exime de CSRF a las vistas de API con autenticacion por
token."""
import secrets

from fastapi import HTTPException, Request, Response

CSRF_SESSION_KEY = "csrf_token"
CSRF_COOKIE_NAME = "gestor_csrftoken"
CSRF_HEADER_NAME = "X-CSRFToken"
CSRF_FIELD_NAME = "csrf_token"
EXEMPT_PREFIXES = ("/api/",)


def _get_or_create_token(request: Request) -> str:
    token = request.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


def token_actual(request: Request) -> str:
    """Para {{ csrf_field() }} en las plantillas (ver templating.py) --
    mismo token que ya se genero/reflejo en la cookie por la dependency
    global, nunca crea uno nuevo aqui (evita que renderizar dos formularios
    en la misma pagina produzca tokens distintos)."""
    return _get_or_create_token(request)


async def proteger(request: Request) -> None:
    """Dependency global -- SOLO valida (y de paso genera/mantiene el token
    en la sesion si no existia). NO fija la cookie aqui: si un endpoint
    devuelve un Response propio (TemplateResponse/RedirectResponse/
    JSONResponse/... -- que es TODO endpoint de esta app), FastAPI
    descarta cualquier cookie fijada desde dentro de una Depends(), porque
    solo conserva las cabeceras del Response que la propia ruta devuelve.
    La cookie se refleja aparte, en main.py::_logs_de_uso (ver
    reflejar_cookie), que si tiene acceso al Response FINAL de verdad."""
    token = _get_or_create_token(request)

    if request.method != "POST" or request.url.path.startswith(EXEMPT_PREFIXES):
        return

    enviado = request.headers.get(CSRF_HEADER_NAME)
    if not enviado:
        content_type = request.headers.get("content-type", "")
        if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
            form = await request.form()
            enviado = form.get(CSRF_FIELD_NAME)
    if not enviado or not secrets.compare_digest(str(enviado), token):
        raise HTTPException(status_code=403, detail="CSRF token inválido o ausente. Recarga la página e inténtalo de nuevo.")


def reflejar_cookie(request: Request, response: Response) -> None:
    """Refleja en una cookie legible por JS el token que 'proteger()' ya
    genero/valido en la sesion -- llamada desde main.py::_logs_de_uso
    (middleware real, no Depends()), justo antes de devolver la respuesta
    final. samesite=lax (no strict): un enlace externo (ej. un email) debe
    poder navegar sin perder la cookie; lax ya bloquea el caso que importa
    (un POST cross-site)."""
    token = request.session.get(CSRF_SESSION_KEY)
    if token:
        # Secure cuando la peticion llega por HTTPS (directa o tras la entrada).
        https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"
        response.set_cookie(CSRF_COOKIE_NAME, token, samesite="lax", secure=https)
