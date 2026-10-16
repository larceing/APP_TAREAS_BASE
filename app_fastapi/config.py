# -*- coding: utf-8 -*-
"""Configuracion de instalacion: lo que cambia de una empresa a otra sin
tocar codigo. Todo sale del .env (ver .env.example) y se lee en cada
llamada, no como constante de modulo, por el mismo motivo que
db.py::entorno_actual(): no depender del orden en que se importa cada
modulo respecto a load_dotenv().

- Marca: APP_NOMBRE, APP_EMPRESA, APP_LOGO.
- Login: AUTH_MODO = local (por defecto, usuario/contraseña en auth_user) o
  keycloak (SSO, ver auth.py).
- Modulos opcionales, apagados por defecto: MODULO_MANTIS, MODULO_NEXUS,
  MODULO_ESCRITORIO, MODULO_CONECTORES, MODULO_DESPLIEGUES. Apagado = no se monta su router, no sale en el menu ni
  en Configuracion, y (escritorio) no arrancan sus hilos.
"""
import os

MODULOS = ("mantis", "nexus", "escritorio", "conectores", "despliegues")

_VERDADERO = {"1", "true", "si", "sí", "yes", "on"}


def app_nombre() -> str:
    return os.getenv("APP_NOMBRE", "").strip() or "Gestor de Tareas"


def app_empresa() -> str:
    return os.getenv("APP_EMPRESA", "").strip() or "Mi Empresa"


def app_logo() -> str:
    return os.getenv("APP_LOGO", "").strip() or "/static/img/logo.svg"


def auth_modo() -> str:
    modo = os.getenv("AUTH_MODO", "local").strip().lower()
    return modo if modo in ("local", "keycloak") else "local"


def modulo_activo(nombre: str) -> bool:
    if nombre not in MODULOS:
        raise ValueError(f"módulo desconocido: {nombre}")
    return os.getenv(f"MODULO_{nombre.upper()}", "").strip().lower() in _VERDADERO
