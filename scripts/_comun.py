# -*- coding: utf-8 -*-
"""Lo que comparten los scripts de instalacion: cargar el MISMO .env que la
app (app_fastapi/.env) y abrir conexiones con sus DB_*."""
import os
import sys
from pathlib import Path

import pymysql
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))  # para poder hacer "from app_fastapi import ..."
load_dotenv(BASE_DIR / "app_fastapi" / ".env")

SQL_SCHEMA = BASE_DIR / "scripts" / "schema_app_tareas.sql"


def conectar(database: str | None = None, user: str | None = None, password: str | None = None):
    return pymysql.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"), port=int(os.getenv("DB_PORT", "3306")),
        user=user or os.getenv("DB_USER"), password=password if password is not None else os.getenv("DB_PASSWORD"),
        database=database, charset="utf8mb4",
    )


def sentencias_schema() -> list[str]:
    """El .sql sin las lineas de comentario y troceado por ';' (ninguna
    sentencia del esquema lleva ';' dentro de un literal)."""
    sql = SQL_SCHEMA.read_text(encoding="utf-8")
    sin_comentarios = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    return [t.strip() for t in sin_comentarios.split(";") if t.strip()]
