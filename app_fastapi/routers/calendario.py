# -*- coding: utf-8 -*-
"""Calendario -- vista mes/semana, copiado de core/views.py::calendar_view +
_build_day_cell + core/templates/calendar.html. Muestra los dias especiales
reales (Configuracion -> Calendario, ya construidos en esta v2) y las tareas
reales de la tabla `tareas`, con creacion/edicion de tarea desde el propio
calendario -- el modal incluye subtareas/tiempo estimado-real/sprint (igual
que el modal reducido real, que SI los tiene desde que se le añadieron
Sprints), pero sigue sin empresa/sistema/iniciativa/anclada, que el modal
reducido real tampoco tiene.

No se ha copiado el tablero Kanban/Scrum en si (routers/proyectos.py no
existe todavia) -- las tareas se leen/escriben por SQL directo contra
`tareas`/`columnas_tablero`, sin la capa de "cargar todo el proyecto en
memoria y regrabarlo entero" de core/db_store.py, que solo hace falta para
gestionar el tablero completo (reordenar columnas, mover tarjetas, etc).

Reuniones sincronizadas desde el feed ICS (Configuracion -> Calendario
externo, ver routers/configuracion.py + routers/reunion.py) se pintan aqui
como chips violeta que enlazan a /reunion/<id>/ (el hub de esa reunion),
igual que core/views.py::_build_day_cell + core/templates/calendar.html."""
import calendar as _cal
from datetime import date as _date, datetime as _datetime, timedelta as _timedelta

from fastapi import APIRouter, Depends, Form
from fastapi.requests import Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import acciones, auth, db
from ..flash import flash
from ..templating import templates

router = APIRouter(prefix="/calendario", tags=["calendario"])

MONTH_NAMES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
               "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
DOW_NAMES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
PRIORITIES = ["Normal", "Alta", "Baja"]
PRIO_ORDER = {"Alta": 0, "Normal": 1, "Baja": 2}


def _build_day_cell(fecha, today, tasks_by_date, proyectos_by_id, dias_especiales, done_by_proyecto,
                     reuniones_by_date=None):
    d_str = fecha.isoformat()
    chips = []
    for t in tasks_by_date.get(d_str, []):
        proj = proyectos_by_id.get(t["proyecto_id"])
        chips.append({**t, "proj_color": proj["color"] if proj else "#6b7280",
                      "proj_nombre": proj["nombre"] if proj else ""})

    dia_del_dia = [de for de in dias_especiales if de["fecha_inicio"] <= d_str <= de["fecha_fin"]]
    sedes = [de for de in dia_del_dia if de["categoria"] == "sede"]
    banners = [de for de in dia_del_dia if de["categoria"] == "banner"]
    anot = [de for de in dia_del_dia if de["categoria"] == "anotacion"]
    sede = sedes[0] if sedes else None
    banner = next((b for b in banners if b["urgente"]), None) or (banners[0] if banners else None)

    return {
        "day": fecha.day, "dow": DOW_NAMES[fecha.weekday()], "date": d_str,
        "tasks": chips, "is_today": fecha == today, "is_past": fecha < today,
        "sede": {"tipo": sede["nombre"], "color": sede["color"]} if sede else None,
        "aviso": {"tipo": banner["nombre"], "color": banner["color"], "nota": banner["nota"]} if banner else None,
        "avisos": [{"tipo": b["nombre"], "color": b["color"], "nota": b["nota"]} for b in banners],
        "anotaciones": [{"tipo": a["nombre"], "color": a["color"], "nota": a["nota"]} for a in anot],
        # igual que core/views.py: "urgente" compara contra las columnas
        # es_done reales de CADA proyecto (done_by_proyecto, una sola query
        # para todos los proyectos -- ver db.done_status_names_by_project),
        # no contra el nombre literal 'Hecha' -- si un proyecto ha renombrado
        # su columna de hecho, esto sigue detectando bien lo urgente.
        "urgente": any(
            c["priority"] == "Alta" and c["status"] not in done_by_proyecto.get(c["proyecto_id"], {"Hecha"})
            for c in chips
        ),
        "reuniones": [
            {"reunion_id": r["reunion_id"], "titulo": r["titulo"],
             "hora": r["fecha_inicio"].split(" ")[1] if " " in r["fecha_inicio"] else ""}
            for r in (reuniones_by_date or {}).get(d_str, [])
        ],
    }


@router.get("/")
def ver_calendario(request: Request, usuario: str = Depends(auth.requiere_login)):
    today = _date.today()
    qp = request.query_params

    def _int_qp(nombre, actual):
        try:
            return int(qp.get(nombre, actual))
        except ValueError:
            return actual

    year = max(2020, min(_int_qp("year", today.year), 2040))
    month = max(1, min(_int_qp("month", today.month), 12))
    vista = qp.get("vista", "mes")
    if vista not in ("mes", "semana"):
        vista = "mes"
    project_filter = qp.get("project", "")
    category_filter = qp.get("category", "")

    ref_date = today
    prev_ref = next_ref = ""
    week_title = ""
    monday = sunday = None

    if vista == "semana":
        try:
            ref_date = _datetime.strptime(qp.get("ref_date", ""), "%Y-%m-%d").date()
        except ValueError:
            ref_date = today
        monday = ref_date - _timedelta(days=ref_date.weekday())
        sunday = monday + _timedelta(days=6)
        prev_ref = (monday - _timedelta(days=7)).isoformat()
        next_ref = (monday + _timedelta(days=7)).isoformat()
        year, month = monday.year, monday.month
        if monday.month == sunday.month:
            week_title = f"{monday.day}–{sunday.day} de {MONTH_NAMES[monday.month]} {monday.year}"
        else:
            week_title = f"{monday.day} {MONTH_NAMES[monday.month]} – {sunday.day} {MONTH_NAMES[sunday.month]} {sunday.year}"
        range_start, range_end = monday.isoformat(), sunday.isoformat()
    else:
        last_day = _cal.monthrange(year, month)[1]
        range_start = _date(year, month, 1).isoformat()
        range_end = _date(year, month, last_day).isoformat()

    proyectos = db.load_proyectos_calendario()
    proyectos_by_id = {p["id"]: p for p in proyectos}
    target_tasks = db.load_tasks_by_due_date(range_start, range_end, project_filter, category_filter)
    dias_especiales = db.load_dias_especiales_resueltos()
    proj_cats = [c for c in db.load_categorias_globales() if c["activo"]] if project_filter else []
    done_by_proyecto = db.done_status_names_by_project()

    tasks_by_date: dict = {}
    for t in target_tasks:
        tasks_by_date.setdefault(t["fecha_fin"], []).append(t)
    for lst in tasks_by_date.values():
        lst.sort(key=lambda t: PRIO_ORDER.get(t["priority"], 1))

    reuniones_by_date: dict = {}
    for r in db.load_reuniones_calendario(usuario, range_start, range_end):
        reuniones_by_date.setdefault(r["fecha_inicio"].split(" ")[0], []).append(r)

    def build(d):
        return _build_day_cell(d, today, tasks_by_date, proyectos_by_id, dias_especiales, done_by_proyecto,
                                reuniones_by_date)

    weeks, week_days = [], []
    if vista == "semana":
        week_days = [build(monday + _timedelta(days=i)) for i in range(7)]
    else:
        for week in _cal.monthcalendar(year, month):
            days = []
            for day in week:
                days.append({"day": None, "date": "", "tasks": [], "is_today": False, "is_past": False}
                            if day == 0 else build(_date(year, month, day)))
            weeks.append(days)

    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)

    return templates.TemplateResponse(request, "calendario.html", {
        "usuario": usuario, "activo": "calendario",
        "vista": vista, "weeks": weeks, "week_days": week_days, "week_title": week_title,
        "ref_date": ref_date.isoformat(), "prev_ref": prev_ref, "next_ref": next_ref,
        "today_str": today.isoformat(), "year": year, "month": month, "month_name": MONTH_NAMES[month],
        "today_year": today.year, "today_month": today.month,
        "prev_year": prev_year, "prev_month": prev_month, "next_year": next_year, "next_month": next_month,
        "proyectos": proyectos, "proj_cats": proj_cats,
        "active_project": project_filter, "category_filter": category_filter,
        "priorities": PRIORITIES,
    })


@router.get("/categorias/{proyecto_id}/json")
def categorias_json(proyecto_id: str, usuario: str = Depends(auth.requiere_login)):
    return JSONResponse({"categories": [{"nombre": n} for n in db.load_categorias_para_proyecto(proyecto_id)]})


@router.get("/columnas/{proyecto_id}/json")
def columnas_json(proyecto_id: str, usuario: str = Depends(auth.requiere_login)):
    return JSONResponse({"columnas": [{"nombre": c["nombre"]} for c in db.load_board_columns(proyecto_id)]})


@router.get("/sprints/{proyecto_id}/json")
def sprints_json(proyecto_id: str, usuario: str = Depends(auth.requiere_login)):
    return JSONResponse({"sprints": [
        {"sprint_id": s["sprint_id"], "nombre": s["nombre"], "estado": s["estado"]}
        for s in db.load_sprints(proyecto_id)
    ]})


def _volver_seguro(volver: str) -> str:
    """Evita que un 'volver' manipulado redirija fuera de esta pagina --
    el campo llega de un input oculto rellenado por JS con la URL actual,
    pero se valida igualmente antes de usarlo como Location de la redirect."""
    return volver if volver.startswith("/calendario") else "/calendario/"


@router.post("/tarea/nueva/")
def crear_tarea(
    request: Request, title: str = Form(""), proyecto: str = Form(""), category: str = Form(""),
    status: str = Form("Pendiente"), priority: str = Form("Normal"),
    description: str = Form(""), next_step: str = Form(""),
    fecha_inicio: str = Form(""), fecha_fin: str = Form(""),
    sprint_id: str = Form(""), subtareas: str = Form(""),
    tiempo_estimado: str = Form(""), tiempo_real: str = Form(""),
    volver: str = Form("/calendario/"), usuario: str = Depends(auth.requiere_login),
):
    if title.strip() and proyecto:
        try:
            acciones.crear_tarea(
                acciones.Actor.web(request, usuario), proyecto, title, estado=status, prioridad=priority,
                descripcion=description, proximo_paso=next_step, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
                categoria=category, sprint_id=sprint_id, subtareas=subtareas,
                tiempo_estimado=tiempo_estimado.strip() or None, tiempo_real=tiempo_real.strip() or None,
            )
        except acciones.AccionError as e:
            flash(request, "error", e.mensaje)
    return RedirectResponse(url=_volver_seguro(volver), status_code=303)


@router.post("/tarea/{task_id}/editar/")
def editar_tarea(
    task_id: str, request: Request, title: str = Form(""), proyecto: str = Form(""), category: str = Form(""),
    status: str = Form(""), priority: str = Form(""), description: str = Form(""), next_step: str = Form(""),
    fecha_inicio: str = Form(""), fecha_fin: str = Form(""),
    sprint_id: str = Form(""), subtareas: str = Form(""),
    tiempo_estimado: str = Form(""), tiempo_real: str = Form(""),
    volver: str = Form("/calendario/"), usuario: str = Depends(auth.requiere_login),
):
    if title.strip() and proyecto:
        try:
            acciones.editar_tarea(
                acciones.Actor.web(request, usuario), task_id, proyecto_id=proyecto, titulo=title, estado=status,
                prioridad=priority, descripcion=description, proximo_paso=next_step, fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin, categoria=category, sprint_id=sprint_id, subtareas=subtareas,
                tiempo_estimado=tiempo_estimado.strip() or None, tiempo_real=tiempo_real.strip() or None,
            )
        except acciones.AccionError as e:
            flash(request, "error", e.mensaje)
    return RedirectResponse(url=_volver_seguro(volver), status_code=303)
