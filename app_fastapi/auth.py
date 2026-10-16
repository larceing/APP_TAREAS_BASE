# -*- coding: utf-8 -*-
"""Login con dos modos, elegidos con AUTH_MODO en el .env (ver config.py):

- local (por defecto): usuario/contraseña contra auth_user, con el mismo
  formato de hash que Django (pbkdf2_sha256$iteraciones$sal$hash) -- asi una
  instalacion que venga de Django conserva sus contraseñas. "Es IT" =
  auth_user.is_staff. Los usuarios se crean con scripts/usuarios.py (o los
  crea el instalador: el admin de la demo).
- keycloak: se valida contra el realm de KEYCLOAK_ISSUER con el flujo
  "Direct Access Grant" (grant_type=password): nuestro backend reenvia
  usuario+contraseña al token endpoint y toma un 200 como "credenciales
  correctas", asi login.html no cambia. "Es IT" = grupo "IT" de Keycloak
  (claim "groups"). Quien entra por primera vez se da de alta solo en
  auth_user (ver _asegurar_auth_user). Sin caida a verificacion local: un
  unico origen de verdad para las credenciales.

auth_user es en los dos casos la tabla de la que cuelgan espacios/tareas/etc.

La SESION es propia de la app: cookie firmada (Starlette SessionMiddleware +
itsdangerous, ver main.py); lo unico que persiste en ella es el username y
si es de IT."""
import base64
import hashlib
import hmac
import os
import secrets

import requests
from fastapi import Depends
from fastapi.requests import Request

from . import config, db


class NoAutenticado(Exception):
    """La peticion no trae sesion valida -- un manejador en main.py la
    convierte en una redirección a /login/, no en un 401 crudo."""
    pass


class NoEsIT(Exception):
    """Logueado pero no es de IT (ver docstring del modulo) -- un manejador en
    main.py lo convierte en una redirección a '/' con un aviso, igual que
    NoAutenticado se convierte en redirección a /login/."""
    pass


def _verificar_keycloak(username: str, password: str):
    """(None, False) si Keycloak rechaza las credenciales (o no responde), o
    (username canónico, es_it) si son correctas. "es_it" viene del grupo de
    Keycloak "IT" (claim "groups" del userinfo, vía un protocol mapper en el
    cliente) -- deliberadamente NO se guarda en nuestra base de datos, solo
    en la sesion (ver iniciar_sesion): gestionar quien es de IT es cosa
    entera de Keycloak, no una columna/regla fija aqui.
    No se valida la firma del token: la petición va directa de nuestro
    backend al issuer configurado, así que un 200 en el token endpoint ya es
    prueba suficiente de que la contraseña era correcta.
    Lee KEYCLOAK_ISSUER/etc. en cada llamada (no como constante de modulo) --
    mismo motivo que db.py::entorno_actual() nunca cachea: evita depender de
    que .env ya se haya cargado en el momento exacto en que se importa este
    modulo (el orden de imports en tests.py, por ejemplo, no lo garantiza)."""
    issuer = os.getenv("KEYCLOAK_ISSUER")
    if not issuer:
        return None, False
    try:
        token_resp = requests.post(
            f"{issuer}/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": os.getenv("KEYCLOAK_CLIENT_ID"),
                "client_secret": os.getenv("KEYCLOAK_CLIENT_SECRET"),
                "username": username,
                "password": password,
                # sin pedirlo explicitamente, el token que devuelve Keycloak
                # no lleva el scope "openid" -- y /userinfo lo exige (403
                # insufficient_scope, "Missing openid scope" si falta).
                "scope": "openid",
            },
            timeout=5,
        )
    except requests.RequestException:
        return None, False
    if token_resp.status_code != 200:
        return None, False
    try:
        access_token = token_resp.json()["access_token"]
        userinfo_resp = requests.get(
            f"{issuer}/protocol/openid-connect/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=5,
        )
    except requests.RequestException:
        return None, False
    if userinfo_resp.status_code != 200:
        return None, False
    datos = userinfo_resp.json()
    es_it = "IT" in datos.get("groups", [])
    return datos.get("preferred_username"), es_it


def _asegurar_auth_user(username: str) -> None:
    """Aprovisionamiento just-in-time: si Keycloak ya validó a esta persona
    pero todavía no tiene fila en auth_user, se crea sola. 'password' con
    prefijo '!' = convención de Django para "sin contraseña local
    utilizable" (mismo patrón que el usuario de ejemplo de
    la BD de pruebas) -- la contraseña de verdad vive en Keycloak, no aquí."""
    if db.get_user_id(username) is not None:
        return
    conn = db.connect()
    try:
        with conn.cursor() as cur:
            # TODAS las columnas obligatorias, sin fiarse de DEFAULTs: la
            # auth_user real la creo Django y NO tiene ningun valor por
            # defecto (first_name/last_name/email/date_joined...) -- con solo
            # cinco columnas el alta reventaba (1364 "Field 'first_name'
            # doesn't have a default value") la primera vez que entraba
            # alguien nuevo por Keycloak. Los tests no lo veian porque la
            # auth_user de test_app_tareas si tenia DEFAULTs (ya no).
            cur.execute(
                "INSERT INTO auth_user (password, is_superuser, username, first_name, last_name, email, "
                "is_staff, is_active, date_joined) VALUES ('!keycloak', 0, %s, '', '', '', 0, 1, NOW())",
                (username,),
            )
        conn.commit()
    finally:
        conn.close()


# ── modo local: hash compatible con Django (pbkdf2_sha256) ─────────────────

PBKDF2_ITERACIONES = 870000  # las mismas que Django 5.x


def hash_contrasena(password: str, iteraciones: int = PBKDF2_ITERACIONES) -> str:
    sal = secrets.token_urlsafe(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), sal.encode(), iteraciones)
    return f"pbkdf2_sha256${iteraciones}${sal}${base64.b64encode(dk).decode()}"


def _verificar_pbkdf2_sha256(password: str, guardado: str) -> bool:
    """False para cualquier cosa que no sea un hash pbkdf2_sha256 bien
    formado -- incluido '!...' (convención de Django para "sin contraseña
    utilizable", la que llevan los usuarios dados de alta por Keycloak)."""
    try:
        algoritmo, iteraciones, sal, esperado = guardado.split("$", 3)
        if algoritmo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), sal.encode(), int(iteraciones))
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(base64.b64encode(dk).decode(), esperado)


def _verificar_local(username: str, password: str):
    conn = db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT username, password, is_staff, is_active FROM auth_user WHERE username = %s", (username,))
            fila = cur.fetchone()
    finally:
        conn.close()
    if not fila or not fila[3] or not _verificar_pbkdf2_sha256(password, fila[1] or ""):
        return None, False
    return fila[0], bool(fila[2])


def verificar_credenciales(username: str, password: str):
    """(None, False) si son invalidas, o (username canónico, es_it) si son
    correctas -- usado por routers/login.py al procesar el formulario."""
    if config.auth_modo() == "local":
        return _verificar_local(username.strip(), password)
    validado, es_it = _verificar_keycloak(username, password)
    if not validado:
        return None, False
    _asegurar_auth_user(validado)
    return validado, es_it


def iniciar_sesion(request: Request, username: str, es_it: bool = False) -> None:
    request.session["usuario"] = username
    request.session["es_it"] = es_it


def cerrar_sesion(request: Request) -> None:
    request.session.clear()


def requiere_login(request: Request) -> str:
    usuario = request.session.get("usuario")
    if not usuario:
        raise NoAutenticado()
    return usuario


def requiere_it(request: Request, usuario: str = Depends(requiere_login)) -> str:
    """Como requiere_login, pero exige ademas ser de IT (ver
    iniciar_sesion/session['es_it']) -- para /configuracion/
    entero: ser Admin de un espacio no da acceso a la configuracion global
    de la app, son dos privilegios sin relacion."""
    if not request.session.get("es_it"):
        raise NoEsIT()
    return usuario
