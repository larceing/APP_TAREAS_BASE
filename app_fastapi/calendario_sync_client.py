# -*- coding: utf-8 -*-
"""Cliente minimo para leer un feed ICS publicado (Outlook/Office 365 ->
Configuracion del calendario -> "Publicar calendario"). Funcion pura de red:
no toca la BD de la app, igual que core/mantis_client.py. Errores de
red/formato se traducen a ValueError con mensaje legible para que la vista
los convierta en JsonResponse({"ok": False, ...}), en vez de dejar pasar el
traceback crudo de requests/icalendar."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import requests

_TIMEOUT = 15

# Ventana [pasado, futuro] de la sincronizacion -- un feed ICS publicado suele
# incluir años de historico y reuniones recurrentes "para siempre", asi que
# hace falta acotar antes de expandir la recurrencia (recurring_ical_events
# necesita un rango concreto, no admite "hasta el infinito").
_VENTANA_PASADO_DIAS = 30
_VENTANA_FUTURO_DIAS = 180

_TEAMS_LINK_RE = re.compile(r'https://teams\.microsoft\.com/l/meetup-join/[^\s"<>]+')


def fetch_eventos(ics_url: str) -> list[dict]:
    """Descarga el feed ICS y expande las reuniones recurrentes (RRULE, tipo
    "todos los viernes") en ocurrencias concretas dentro de la ventana de
    sincronizacion -- icalendar por si solo NO hace esto, devolveria la serie
    una unica vez. Cada ocurrencia comparte 'uid' con el resto de la serie
    pero tiene su propia fecha_inicio (ver TaskStoreDB._reunion_id, que
    combina ambos para no machacar unas ocurrencias con otras).

    Devuelve una lista de dicts: {uid, titulo, fecha_inicio (datetime naive),
    fecha_fin (datetime naive|None), ubicacion, enlace_teams}."""
    import recurring_ical_events  # import diferido: solo se carga al usarse, no en el arranque de la app
    from icalendar import Calendar

    if not ics_url:
        raise ValueError("no hay ninguna URL de feed ICS configurada (Configuración → Calendario externo)")

    try:
        resp = requests.get(ics_url, timeout=_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise ValueError(f"no se pudo descargar el feed ICS: {e}") from e

    try:
        cal = Calendar.from_ical(resp.content)
        desde = date.today() - timedelta(days=_VENTANA_PASADO_DIAS)
        hasta = date.today() + timedelta(days=_VENTANA_FUTURO_DIAS)
        ocurrencias = recurring_ical_events.of(cal).between(desde, hasta)
    except Exception as e:
        raise ValueError(f"el feed ICS no se pudo interpretar: {e}") from e

    eventos = []
    for componente in ocurrencias:
        uid = str(componente.get("UID", "")).strip()
        fecha_inicio = _a_datetime_naive(componente.get("DTSTART"))
        if not uid or not fecha_inicio:
            continue
        eventos.append({
            "uid": uid,
            "titulo": str(componente.get("SUMMARY", "") or "").strip() or "(sin título)",
            "fecha_inicio": fecha_inicio,
            "fecha_fin": _a_datetime_naive(componente.get("DTEND")),
            "ubicacion": str(componente.get("LOCATION", "") or "").strip(),
            "enlace_teams": _extraer_enlace_teams(componente),
        })
    return eventos


def _a_datetime_naive(prop):
    if prop is None:
        return None
    valor = prop.dt
    if isinstance(valor, datetime):
        # quitar zona horaria (naive) para poder comparar/guardar sin lios --
        # a hora local, que es lo que se ve en el Calendario de la app
        return valor.astimezone().replace(tzinfo=None) if valor.tzinfo else valor
    if isinstance(valor, date):
        # evento de dia completo (VALUE=DATE): sin hora, medianoche
        return datetime(valor.year, valor.month, valor.day)
    return None


def _extraer_enlace_teams(componente) -> str:
    # Outlook suele meter un campo dedicado con el enlace de Teams; si no
    # esta, se busca dentro de la descripcion (donde tambien suele aparecer).
    dedicado = componente.get("X-MICROSOFT-SKYPETEAMSMEETINGURL")
    if dedicado:
        return str(dedicado).strip()
    m = _TEAMS_LINK_RE.search(str(componente.get("DESCRIPTION", "") or ""))
    return m.group(0) if m else ""
