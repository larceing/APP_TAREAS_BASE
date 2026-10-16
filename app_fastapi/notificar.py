# -*- coding: utf-8 -*-
"""Quien recibe que notificacion en la campana (tabla notificaciones, ver
routers/notificaciones.py). Un sitio unico para los textos y los enlaces,
llamado desde los routers donde pasa cada cosa.

Tipos de la fase 1: nota recibida (Buzon), recordatorio de una nota que
vence (lo genera db.generar_recordatorios_buzon al consultar la campana) y
tarea asignada. Nunca se notifica a uno mismo de algo que acaba de hacer.
"""
from urllib.parse import urlencode

from . import db


def _resumen(texto: str, n: int = 80) -> str:
    texto = " ".join((texto or "").split())
    return texto if len(texto) <= n else texto[: n - 3] + "..."


def _nombre(username: str) -> str:
    for u in db.load_usuarios():
        if u["username"] == username:
            return u["nombre_completo"]
    return username


def nota_recibida(para_user_id: int, de_username: str, contenido: str, nota_id: int, reenviada: bool = False,
                  nombre: str = None) -> bool:
    """nombre: nombre visible ya calculado (p. ej. "ana.lopez (vía API: …)", ver
    acciones.Actor); si no, se saca del username."""
    verbo = "te ha reenviado una nota" if reenviada else "te ha enviado una nota"
    db.crear_notificacion(para_user_id, "nota", f"{nombre or _nombre(de_username)} {verbo}: {_resumen(contenido)}",
                          f"/buzon/#nota-{nota_id}")
    return True


def tarea_asignada(asignado_a, actor_user_id, actor_username: str, tarea_id: str, titulo: str, proyecto_id: str,
                   nombre: str = None) -> bool:
    """True si ha avisado a alguien (nunca a quien se asigna a si mismo)."""
    if not asignado_a or asignado_a == actor_user_id:
        return False
    db.crear_notificacion(
        asignado_a, "tarea_asignada", f"{nombre or _nombre(actor_username)} te ha asignado una tarea: {_resumen(titulo)}",
        f"/proyecto/{proyecto_id}/tablero/?{urlencode({'abrir_tarea': tarea_id})}",
    )
    return True
