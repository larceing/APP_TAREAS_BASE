# -*- coding: utf-8 -*-
"""Tablero por proyecto (editable) -- la pieza grande que quedaba pendiente
de "Proyectos". Copiado de core/views.py::board/_render_board/project_new/
project_edit/column_new/column_rename/column_move/column_delete/task_reorder
+ core/templates/board.html, mas los sprints de Scrum: project_sprints/
sprint_new/sprint_edit/sprint_close/sprint_add_task/sprint_add_tasks_bulk/
sprint_remove_task/project_tasks_without_sprint + core/templates/
project_sprints.html.

Simplificaciones deliberadas frente al original (documentadas, no
escondidas -- ver README):
- Importar tareas desde Excel al crear un proyecto (mismo formulario,
  reutiliza excel_import.import_tasks_from_excel) y exportar CSV del
  tablero (mismo subconjunto reducido de filtros que el original: sin
  sistema/iniciativa/IA) SI estan -- ver plantilla_importar_excel y
  tablero_exportar_csv.
- Deshacer/rehacer (Ctrl+Z/Ctrl+Y) y el modal de atajos de teclado (`?`) SI
  estan -- el listener de teclado global vive en templates/_base.html
  (equivalente a static/js/board.js::initKeyboard() del original), las
  funciones _undo()/_redo()/_performMove() viven aqui en tablero.html (como
  en el original), reutilizando el mismo endpoint /tarea/<id>/reordenar/
  que el drag-and-drop real -- solo restauran la COLUMNA, no la posicion
  exacta dentro de ella, igual limitacion que el original.
- Borrar un proyecto entero (eliminar_proyecto) SI esta -- 'general' es
  intocable, igual que el original. **Mejora deliberada sobre el
  original**: en Django `project_delete` existe en el backend pero no hay
  NINGUN boton/enlace en ninguna plantilla que lo dispare (confirmado por
  busqueda exhaustiva) -- es codigo muerto en la practica. Aqui SI hay un
  boton "Eliminar proyecto" real en el modal de editar proyecto de
  tablero.html (oculto en modo "nuevo", solo visible editando; ausente del
  todo si el proyecto es 'general'), con un `showConfirm()` que explica que
  se pierde antes de confirmar.
- El panel de detalle lateral de tarea (task_detail/task_doc_upload) SI
  esta -- salvo el boton "Duplicar tarea" del original, que se deja para
  cuando/si se porte "duplicar tarea" como pieza aparte (no pedida en este
  pase).
- La seleccion multiple + borrado en bloque (tareas_borrar_varias) SI esta.
- Los filtros de sistema/iniciativa/prioridad/rango de fechas SI estan
  (ademas de estado, categoria, IA y busqueda, que ya estaban). El rango de
  fechas filtra por FECHA DE CREACION (creada_en), no por fecha_inicio/
  fecha_fin -- igual que el original, que lo etiqueta "Creadas entre" --
  con la misma comparacion de string (no de fecha) que hace que date_to
  excluya de facto las tareas creadas ese mismo dia despues de medianoche;
  replicado tal cual (bug-compatible), no corregido aqui (ver ver_tablero).
  La barra de filtros esta copiada estructuralmente de core/templates/
  board.html (dos filas, colapsada por defecto, boton "sliders" para
  desplegarla, prioridad como "pills" no <select> -- con el mismo detalle
  real del original: las reglas CSS [data-p="Alta"].active etc. son
  codigo muerto porque el HTML real nunca pone data-p, asi que la pill
  activa siempre sale oscura, nunca coloreada por prioridad; replicado tal
  cual, ver templates/tablero.html).
- El modal de tarea del tablero muestra el selector de sprint con los
  sprints del proyecto actualmente cargado (no se vuelve a pedir por AJAX
  al reasignar la tarea a otro proyecto, a diferencia de categoria/estado
  que si lo hacen) -- reasignar una tarea Scrum de sprint Y de proyecto a
  la vez en el mismo guardado es un caso raro que queda sin cubrir."""
import csv
import json
import os
import uuid
from datetime import datetime, timedelta
from io import BytesIO, StringIO
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.requests import Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse

from .. import acciones, auth, db, excel_import, logging_setup, muro
from ..flash import flash
from ..templating import templates

router = APIRouter(tags=["tablero"])

ESTADOS_PROYECTO = ["Activo", "En pausa", "Cerrado"]
TIPOS_PROYECTO = ["kanban", "scrum"]
PRIORITIES = ["Normal", "Alta", "Baja"]
# Lista fija que usa Resumen/Dashboard para las tarjetas de metricas y las
# barras "por estado" -- igual que core/models.py::STATUSES. Es una
# inconsistencia heredada del original, no introducida aqui: las columnas
# reales del tablero SI son personalizables por proyecto (ver
# load_board_columns), pero estas dos paginas siguen asumiendo estos 4
# nombres fijos -- si un proyecto renombra sus columnas, estas metricas
# dejan de cuadrar con el tablero real de ese proyecto.
STATUSES = ["Pendiente", "En curso", "En espera", "Hecha"]

COLOR_PALETTE = [
    "#2563eb", "#7c3aed", "#db2777", "#ea580c",
    "#16a34a", "#0891b2", "#9333ea", "#b45309",
    "#0f766e", "#c2410c",
]
COLUMN_COLOR_PRESETS = [
    "#f97316", "#2563eb", "#ca8a04", "#16a34a", "#7c3aed",
    "#ec4899", "#0891b2", "#6b7280", "#dc2626", "#84cc16",
]


def _redirect_tablero(project_id: str) -> RedirectResponse:
    return RedirectResponse(url=f"/proyecto/{project_id}/tablero/", status_code=303)


# ── proyectos ────────────────────────────────────────────────────────────────

@router.get("/excel/plantilla-importar-tareas/")
def plantilla_importar_excel(usuario: str = Depends(auth.requiere_login)):
    """Genera al vuelo la plantilla .xlsx para importar tareas (al crear un
    proyecto o desde el Backlog) -- igual que
    core/views.py::plantilla_import_excel. Ruta deliberadamente fuera de
    /proyecto/<algo>/ (que aqui siempre es un project_id dinamico) para no
    arriesgarse a colisionar con GET /proyecto/{project_id}/ (Resumen)."""
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill

    # Mismas cabeceras que espera excel_import.import_tasks_from_excel (no
    # estan como constante ahi, se repiten aqui literales -- igual que
    # core/views.py::IMPORT_EXCEL_HEADERS).
    headers = [
        "Titulo", "Descripcion", "Categoria", "Sistema", "Empresa", "Iniciativa",
        "Prioridad", "Fecha Inicio", "Fecha Fin", "Proximo paso",
    ]
    header_fill = PatternFill("solid", fgColor="2563EB")
    header_font = Font(color="FFFFFF", bold=True)
    ejemplo_font = Font(italic=True, color="6B7280")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Tareas"
    ws.append(headers)
    ws.append([
        "Ejemplo: revisar acceso al ERP", "Descripcion opcional", "Incidencia",
        "ERP", "Empresa Demo", "", "Normal", "2026-08-01", "", "Siguiente paso opcional",
    ])
    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 22
    ws.freeze_panes = "A2"
    for cell in ws[2]:
        cell.font = ejemplo_font
    for col, width in zip("ABCDEFGHIJ", [32, 34, 16, 14, 12, 14, 10, 13, 13, 30]):
        ws.column_dimensions[col].width = width

    ws2 = wb.create_sheet("Valores validos")
    ws2.append(["Categoria", "Sistema", "Empresa", "Iniciativa", "Prioridad"])
    columnas = [
        [c["nombre"] for c in db.load_categorias_globales() if c["activo"]],
        [s["nombre"] for s in db.load_sistemas() if s["activo"]],
        [e["nombre"] for e in db.load_empresas() if e["activo"]],
        [i["nombre"] for i in db.load_iniciativas() if i["activo"]],
        list(PRIORITIES),
    ]
    for i in range(max(len(c) for c in columnas)):
        ws2.append([c[i] if i < len(c) else "" for c in columnas])
    for col in range(1, 6):
        cell = ws2.cell(row=1, column=col)
        cell.fill = PatternFill("solid", fgColor="6B7280")
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for col in "ABCDE":
        ws2.column_dimensions[col].width = 20

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="plantilla_importar_tareas.xlsx"'},
    )


def _puede_editar_espacio_de(espacio_id: str, usuario: str) -> bool:
    """True si el proyecto no tiene espacio asignado todavia (situacion
    legada real hoy -- se deja pasar igual que siempre) o si el usuario es
    Editor/Admin de ese espacio. Lector -> False."""
    if not espacio_id:
        return True
    return db.puede_editar_espacio(espacio_id, db.get_user_id(usuario))


@router.post("/proyecto/nuevo/")
async def crear_proyecto(
    request: Request,
    nombre: str = Form(""), descripcion: str = Form(""), responsable: str = Form(""),
    color: str = Form(""), estado: str = Form("Activo"), tipo: str = Form("kanban"),
    fecha_inicio: str = Form(""), fecha_fin: str = Form(""),
    requiere_subtareas_completas: str = Form(""), espacio_id: str = Form(""),
    excel_tareas: Optional[UploadFile] = File(None),
    usuario: str = Depends(auth.requiere_login),
):
    nombre = nombre.strip()
    if not nombre:
        return RedirectResponse(url="/", status_code=303)
    if not _puede_editar_espacio_de(espacio_id.strip(), usuario):
        flash(request, "error", "No tienes permiso de Editor en ese espacio.")
        return RedirectResponse(url="/", status_code=303)
    if tipo not in TIPOS_PROYECTO:
        tipo = "kanban"
    if estado not in ESTADOS_PROYECTO:
        estado = "Activo"
    project_id = str(uuid.uuid4())[:8]
    db.crear_proyecto(project_id, nombre, descripcion.strip(), responsable.strip(),
                       color or COLOR_PALETTE[0], estado, tipo, fecha_inicio.strip(), fecha_fin.strip(),
                       requiere_subtareas_completas=bool(requiere_subtareas_completas),
                       espacio_id=espacio_id.strip())
    muro.proyecto_creado(project_id, db.get_user_id(usuario))

    # Importar tareas desde Excel al crear es OPCIONAL, mismo formulario --
    # igual que core/views.py::project_new, reutiliza EXACTAMENTE el mismo
    # import_tasks_from_excel que ya usa el Backlog para un proyecto YA
    # existente (aqui titulos_existentes siempre vacio, el proyecto acaba
    # de nacer). Mismos 3 mensajes flash que el original (exito con
    # tareas importadas / avisos por fila / error de lectura del Excel).
    if excel_tareas is not None and excel_tareas.filename:
        data = await excel_tareas.read()
        categorias = db.load_categorias_para_proyecto(project_id)
        sistemas = [s for s in db.load_sistemas() if s["activo"]]
        empresas = [e for e in db.load_empresas() if e["activo"]]
        iniciativas = [i for i in db.load_iniciativas() if i["activo"]]
        try:
            nuevas, avisos = excel_import.import_tasks_from_excel(
                BytesIO(data), excel_tareas.filename, len(data), set(),
                categorias, sistemas, empresas, iniciativas, PRIORITIES,
            )
            for t in nuevas:
                db.crear_tarea(
                    str(uuid.uuid4())[:8], project_id, t["category"], t["title"], "Pendiente", t["priority"],
                    t["description"], t["next_step"], t["fecha_inicio"], t["fecha_fin"],
                    empresa_id=t["empresa_id"], iniciativa_id=t["iniciativa_id"], sistema_id=t["sistema_id"],
                )
            if nuevas:
                flash(request, "success", f"Proyecto '{nombre}' creado con {len(nuevas)} tareas importadas.")
            if avisos:
                texto = "; ".join(avisos[:8])
                if len(avisos) > 8:
                    texto += f" (+{len(avisos) - 8} avisos más)"
                flash(request, "warning", f"{len(avisos)} filas con avisos: {texto}")
                logging_setup.errores.error(
                    f"{usuario} | POST /proyecto/nuevo/ (import Excel de '{nombre}') -> {len(avisos)} avisos: "
                    + "; ".join(avisos[:8])
                )
        except ValueError as e:
            flash(request, "error", f"No se pudo leer el Excel, el proyecto se creó sin tareas: {e}")
            logging_setup.errores.error(f"{usuario} | POST /proyecto/nuevo/ (import Excel de '{nombre}') -> {e}")

    return _redirect_tablero(project_id)


@router.post("/proyecto/{project_id}/editar/")
def editar_proyecto(
    request: Request,
    project_id: str, nombre: str = Form(None), descripcion: str = Form(None), responsable: str = Form(None),
    color: str = Form(None), estado: str = Form(None), tipo: str = Form(None),
    fecha_inicio: str = Form(None), fecha_fin: str = Form(None), espacio_id: str = Form(None),
    requiere_subtareas_completas: str = Form(""), usuario: str = Depends(auth.requiere_login),
):
    actual = db.get_proyecto(project_id)
    if not actual:
        return RedirectResponse(url="/", status_code=303)
    if not _puede_editar_espacio_de(actual["espacio_id"], usuario):
        flash(request, "error", "No tienes permiso de Editor en el espacio de este proyecto.")
        return _redirect_tablero(project_id)
    nuevo_tipo = tipo if tipo in TIPOS_PROYECTO else actual["tipo"]
    nuevo_estado = estado if estado in ESTADOS_PROYECTO else actual["estado"]
    db.editar_proyecto(
        project_id,
        nombre=(nombre.strip() if nombre is not None else actual["nombre"]),
        descripcion=(descripcion.strip() if descripcion is not None else actual["descripcion"]),
        responsable=(responsable.strip() if responsable is not None else actual["responsable"]),
        color=(color if color is not None else actual["color"]),
        estado=nuevo_estado, tipo=nuevo_tipo,
        fecha_inicio=(fecha_inicio.strip() if fecha_inicio is not None else actual["fecha_inicio"]),
        fecha_fin=(fecha_fin.strip() if fecha_fin is not None else actual["fecha_fin"]),
        requiere_subtareas_completas=bool(requiere_subtareas_completas),
        espacio_id=(espacio_id.strip() if espacio_id is not None else actual["espacio_id"]),
    )
    return _redirect_tablero(project_id)


# Eliminar un proyecto vive en routers/proyectos.py::eliminar_proyecto_de_espacio
# (admin del espacio + doble confirmacion) -- antes habia una ruta aqui mismo
# que solo exigia permiso de Editor, sin ninguna confirmacion fuerte;
# consolidado en un unico sitio, mas restrictivo, ver project_config_scope en
# la memoria de esta sesion.


# ── duplicar proyecto ────────────────────────────────────────────────────────
# Igual que core/views.py::project_duplicate + core/templates/
# project_duplicate.html: pagina propia (no un modal), no un simple boton.

@router.get("/proyecto/{project_id}/duplicar/")
def ver_duplicar_proyecto(project_id: str, request: Request, usuario: str = Depends(auth.requiere_login)):
    original = db.get_proyecto(project_id)
    if not original:
        return RedirectResponse(url="/", status_code=303)
    done_names = db.done_status_names_by_project().get(project_id, {"Hecha"})
    tareas_activas = [
        t for t in db.load_tasks_para_tablero(project_id, borrada=False) if t["status"] not in done_names
    ]
    return templates.TemplateResponse(request, "project_duplicate.html", {
        "usuario": usuario, "activo": "tablero", "proyecto": original, "proyecto_actual": project_id,
        "original": original, "proj_count_original": len(tareas_activas),
    })


@router.post("/proyecto/{project_id}/duplicar/")
def duplicar_proyecto(
    request: Request,
    project_id: str, nombre: str = Form(""), copiar_tareas: str = Form("pendientes"),
    copiar_hitos: str = Form(""), fechas: str = Form("limpiar"), crear_sprint: str = Form(""),
    usuario: str = Depends(auth.requiere_login),
):
    original = db.get_proyecto(project_id)
    if not original:
        return RedirectResponse(url="/", status_code=303)
    if not _puede_editar_espacio_de(original["espacio_id"], usuario):
        flash(request, "error", "No tienes permiso de Editor en el espacio de este proyecto.")
        return RedirectResponse(url=f"/proyecto/{project_id}/", status_code=303)
    nombre = nombre.strip() or f"{original['nombre']} (copia)"
    if copiar_tareas not in ("pendientes", "todas", "ninguna"):
        copiar_tareas = "pendientes"
    if fechas not in ("limpiar", "mantener"):
        fechas = "limpiar"
    nuevo_id = db.duplicar_proyecto(
        project_id, nombre, copiar_tareas, fechas,
        copiar_hitos=bool(copiar_hitos), crear_sprint_flag=bool(crear_sprint),
    )
    if not nuevo_id:
        return RedirectResponse(url="/", status_code=303)
    return RedirectResponse(url=f"/proyecto/{nuevo_id}/", status_code=303)


# ── resumen (pagina de aterrizaje del proyecto) ─────────────────────────────
# Igual que core/views.py::project_home + core/templates/project.html.

@router.get("/proyecto/{project_id}/")
def project_home(project_id: str, request: Request, usuario: str = Depends(auth.requiere_login)):
    proyecto = db.get_proyecto(project_id)
    if not proyecto:
        return RedirectResponse(url="/", status_code=303)

    proj_tasks = db.load_tasks_para_tablero(project_id, borrada=False)
    total = len(proj_tasks)
    done_names = {c["nombre"] for c in db.load_board_columns(project_id) if c["es_done"]}
    by_status = {s: len([t for t in proj_tasks if t["status"] == s]) for s in STATUSES}
    hechas = len([t for t in proj_tasks if t["status"] in done_names])
    done_pct = int(hechas / total * 100) if total else 0

    proj_cats = [dict(c) for c in db.load_categorias_globales() if c["activo"]]
    for cat in proj_cats:
        cat["task_count"] = len([t for t in proj_tasks if t["category"] == cat["nombre"]])

    proj_ms = sorted(db.load_hitos_por_proyecto(project_id), key=lambda m: m["fecha"] or "9999")

    recent_activity = sorted(
        proj_tasks, key=lambda t: t["actualizada_en"] or t["creada_en"] or "0000", reverse=True,
    )[:8]

    return templates.TemplateResponse(request, "project_home.html", {
        "usuario": usuario, "activo": "resumen", "proyecto": proyecto, "proyecto_actual": project_id,
        "proj_tasks": proj_tasks, "by_status": by_status, "done_pct": done_pct, "total": total,
        "proj_cats": proj_cats, "proj_ms": proj_ms, "recent_activity": recent_activity,
        "statuses": STATUSES,
    })


# ── dashboard ────────────────────────────────────────────────────────────────
# Igual que core/views.py::project_dashboard + core/templates/
# project_dashboard.html -- burndown y heatmap son canvas dibujados a mano en
# el propio JS de la plantilla, sin libreria, igual que el original.

def _compute_burndown(sprint: dict, sprint_tasks: list):
    """Igual que core/views.py::compute_burndown. Devuelve (burndown_json,
    burndown_total)."""
    burndown_total = len(sprint_tasks)
    if not (sprint["fecha_inicio"] and sprint["fecha_fin"] and sprint_tasks):
        return "[]", burndown_total
    try:
        start_d = datetime.strptime(sprint["fecha_inicio"], "%Y-%m-%d").date()
        end_d = datetime.strptime(sprint["fecha_fin"], "%Y-%m-%d").date()
    except ValueError:
        return "[]", burndown_total
    duration = (end_d - start_d).days + 1
    if duration < 1:
        return "[]", burndown_total

    closed_by_day = {}
    for t in sprint_tasks:
        if t["cerrada_en"]:
            try:
                cd = datetime.strptime(t["cerrada_en"][:10], "%Y-%m-%d").date().isoformat()
                closed_by_day[cd] = closed_by_day.get(cd, 0) + 1
            except ValueError:
                pass

    remaining = burndown_total
    pts = []
    for i in range(duration):
        day = (start_d + timedelta(days=i)).isoformat()
        remaining -= closed_by_day.get(day, 0)
        ideal = round(burndown_total * (1 - i / (duration - 1))) if duration > 1 else 0
        pts.append({"day": day, "remaining": max(0, remaining), "ideal": ideal})
    return json.dumps(pts), burndown_total


@router.get("/proyecto/{project_id}/dashboard/")
def project_dashboard(project_id: str, request: Request, usuario: str = Depends(auth.requiere_login)):
    proyecto = db.get_proyecto(project_id)
    if not proyecto:
        return RedirectResponse(url="/", status_code=303)

    tasks = db.load_dashboard_data(project_id)
    total = len(tasks)
    done_names = {c["nombre"] for c in db.load_board_columns(project_id) if c["es_done"]}
    hechas = len([t for t in tasks if t["status"] in done_names])
    done_pct = int(hechas / total * 100) if total else 0

    by_status = [(s, len([t for t in tasks if t["status"] == s])) for s in STATUSES]

    hoy = datetime.now().strftime("%Y-%m-%d")
    overdue = sorted(
        [t for t in tasks if t["fecha_fin"] and t["fecha_fin"] < hoy and t["status"] not in done_names],
        key=lambda t: t["fecha_fin"],
    )

    by_cat = []
    for cat in db.load_categorias_globales():
        if not cat["activo"]:
            continue
        cat_tasks = [t for t in tasks if t["category"] == cat["nombre"]]
        if not cat_tasks:
            continue
        pending = len([t for t in cat_tasks if t["status"] not in done_names])
        by_cat.append((cat["nombre"], cat["color"], pending, len(cat_tasks)))
    cat_max = max([c[3] for c in by_cat], default=0)

    by_priority = [(p, len([t for t in tasks if t["priority"] == p and t["status"] not in done_names])) for p in PRIORITIES]
    p_max = max([c[1] for c in by_priority], default=0)

    sprint_stats = []
    active_sprint = None
    burndown_json, burndown_total = "[]", 0
    if proyecto["tipo"] == "scrum":
        sprints = sorted(db.load_sprints(project_id), key=lambda s: s["numero"])
        counts = db.sprint_counts_por_proyecto(project_id, [s["sprint_id"] for s in sprints])
        for s in sprints:
            c = counts.get(s["sprint_id"], {"total": 0, "hecha": 0})
            pct = int(c["hecha"] / c["total"] * 100) if c["total"] else 0
            sprint_stats.append({"sprint": s, "total": c["total"], "hecha": c["hecha"], "pct": pct})
        active_sprint = next((s for s in sprints if s["estado"] == "activo"), None)
        if active_sprint:
            sprint_tasks = [t for t in tasks if t["sprint_id"] == active_sprint["sprint_id"]]
            burndown_json, burndown_total = _compute_burndown(active_sprint, sprint_tasks)

    heatmap = {}
    limite = (datetime.now() - timedelta(days=364)).strftime("%Y-%m-%d")
    for t in tasks:
        dia = t["creada_en"][:10] if t["creada_en"] else ""
        if dia and dia >= limite:
            heatmap[dia] = heatmap.get(dia, 0) + 1

    return templates.TemplateResponse(request, "project_dashboard.html", {
        "usuario": usuario, "activo": "dashboard", "proyecto": proyecto, "proyecto_actual": project_id,
        "total": total, "done_pct": done_pct, "by_status": by_status, "overdue": overdue,
        "by_cat": by_cat, "cat_max": cat_max, "by_priority": by_priority, "p_max": p_max,
        "sprint_stats": sprint_stats, "active_sprint": active_sprint,
        "burndown_json": burndown_json, "burndown_total": burndown_total,
        "heatmap_json": json.dumps(heatmap),
    })


# ── documentos ───────────────────────────────────────────────────────────────
# Igual que core/views.py::project_docs/doc_upload/doc_download/doc_delete/
# task_doc_upload. doc_download/doc_delete son genericas (sirven igual para un
# documento de proyecto o de tarea); task_doc_upload SI es propia del panel de
# detalle de tarea (ver mas abajo, junto a task_detail).

@router.get("/proyecto/{project_id}/documentos/")
def project_docs(project_id: str, request: Request, usuario: str = Depends(auth.requiere_login)):
    proyecto = db.get_proyecto(project_id)
    if not proyecto:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "project_docs.html", {
        "usuario": usuario, "activo": "documentos", "proyecto": proyecto, "proyecto_actual": project_id,
        "proj_docs": db.load_documentos_proyecto(project_id),
        "task_docs_grouped": db.load_documentos_por_tarea(project_id),
    })


@router.post("/proyecto/{project_id}/doc/subir/")
async def doc_upload(request: Request, project_id: str, file: UploadFile = File(...), usuario: str = Depends(auth.requiere_login)):
    proyecto = db.get_proyecto(project_id)
    if not proyecto:
        return RedirectResponse(url="/", status_code=303)
    if not db.puede_actuar_en_proyecto(project_id, db.get_user_id(usuario), "editores_gestionan_documentos_wiki"):
        flash(request, "error", "No tienes permiso para subir documentos a este proyecto.")
        return RedirectResponse(url=f"/proyecto/{project_id}/documentos/", status_code=303)
    if file.filename:
        ext = Path(file.filename).suffix
        filename = str(uuid.uuid4()) + ext
        data = await file.read()
        (db.media_dir() / filename).write_bytes(data)
        db.crear_documento(project_id, "", file.filename, filename, len(data), usuario)
    return RedirectResponse(url=f"/proyecto/{project_id}/documentos/", status_code=303)


@router.get("/doc/{doc_id}/descargar/")
def doc_download(doc_id: str, usuario: str = Depends(auth.requiere_login)):
    doc = db.get_documento(doc_id)
    if not doc:
        return RedirectResponse(url="/", status_code=303)
    path = db.media_dir() / doc["filename"]
    if not path.exists():
        return RedirectResponse(url="/", status_code=303)
    return FileResponse(path, filename=doc["nombre"])


@router.post("/doc/{doc_id}/eliminar/")
def doc_delete(request: Request, doc_id: str, usuario: str = Depends(auth.requiere_login)):
    doc = db.get_documento(doc_id)
    if doc and not db.puede_actuar_en_proyecto(doc["proyecto_id"], db.get_user_id(usuario), "editores_gestionan_documentos_wiki"):
        flash(request, "error", "No tienes permiso para eliminar documentos de este proyecto.")
        if doc["tarea_id"]:
            return RedirectResponse(url=f"/proyecto/{doc['proyecto_id']}/tablero/?abrir_tarea={doc['tarea_id']}", status_code=303)
        return RedirectResponse(url=f"/proyecto/{doc['proyecto_id']}/documentos/", status_code=303)
    if doc:
        path = db.media_dir() / doc["filename"]
        if path.exists():
            path.unlink()
        db.eliminar_documento(doc_id)
        # un documento de tarea vuelve al tablero con el panel de detalle ya
        # reabierto (?abrir_tarea=), no a Documentos -- de ahi vino el borrado.
        # Diferencia deliberada frente al original (que siempre manda a
        # board_project sin reabrir nada): aqui SI se reaprovecha el mismo
        # mecanismo ?abrir_tarea= que ya usa el buscador global.
        if doc["tarea_id"]:
            return RedirectResponse(
                url=f"/proyecto/{doc['proyecto_id']}/tablero/?abrir_tarea={doc['tarea_id']}", status_code=303,
            )
        return RedirectResponse(url=f"/proyecto/{doc['proyecto_id']}/documentos/", status_code=303)
    return RedirectResponse(url="/", status_code=303)


# ── panel de detalle lateral de tarea ────────────────────────────────────────
# Igual que core/views.py::task_detail/task_doc_upload + core/templates/
# board.html (openDetail/closeDetail). Sin duplicar tarea desde el panel (el
# original tiene un boton "Duplicar" ahi -- pieza aparte, no pedida en este
# pase, se deja para cuando/si se porte "duplicar tarea" en general).

@router.get("/tarea/{task_id}/detalle/")
def task_detail(task_id: str, usuario: str = Depends(auth.requiere_login)):
    t = db.get_tarea_by_id(task_id)
    if not t:
        return JSONResponse({"ok": False}, status_code=404)
    proyecto = db.get_proyecto(t["proyecto_id"])
    sprint = db.get_sprint(t["sprint_id"]) if t["sprint_id"] else None
    documentos = db.load_documentos_de_tarea(task_id)
    return JSONResponse({
        "ok": True, "task_id": t["task_id"], "title": t["title"],
        "status": t["status"], "priority": t["priority"],
        "category": t["category"], "proyecto": t["proyecto_id"],
        "project_name": proyecto["nombre"] if proyecto else "?",
        "project_color": proyecto["color"] if proyecto else "#2563eb",
        "sprint_nombre": sprint["nombre"] if sprint else "", "sprint_id": t["sprint_id"],
        "description": t["description"], "next_step": t["next_step"],
        "created_at": t["creada_en"], "updated_at": t["actualizada_en"], "deleted": t["deleted"],
        "fecha_inicio": t["fecha_inicio"], "fecha_fin": t["fecha_fin"],
        "subtareas": t["subtareas_raw"],
        "tiempo_estimado": t["tiempo_estimado"], "tiempo_real": t["tiempo_real"],
        "empresa_id": t["empresa_id"], "sistema_id": t["sistema_id"], "iniciativa_id": t["iniciativa_id"],
        "anclada": t["anclada"],
        "documents": [
            {"doc_id": d["doc_id"], "nombre": d["nombre"], "size_str": d["size_str"],
             "icon": d["icon"], "uploaded_at": d["uploaded_at"]}
            for d in documentos
        ],
    })


@router.post("/tarea/{task_id}/doc/subir/")
async def task_doc_upload(task_id: str, file: UploadFile = File(...), usuario: str = Depends(auth.requiere_login)):
    proyecto_id, _, _, _ = db.tarea_estado_actual(task_id)
    if not proyecto_id or not file.filename:
        return RedirectResponse(url="/", status_code=303)
    if not db.puede_actuar_en_proyecto(proyecto_id, db.get_user_id(usuario), "editores_gestionan_documentos_wiki"):
        return RedirectResponse(url=f"/proyecto/{proyecto_id}/tablero/?abrir_tarea={task_id}", status_code=303)
    ext = Path(file.filename).suffix
    filename = str(uuid.uuid4()) + ext
    data = await file.read()
    (db.media_dir() / filename).write_bytes(data)
    db.crear_documento(proyecto_id, task_id, file.filename, filename, len(data), usuario)
    return RedirectResponse(url=f"/proyecto/{proyecto_id}/tablero/?abrir_tarea={task_id}", status_code=303)


# ── backlog (Scrum) ──────────────────────────────────────────────────────────
# Igual que core/views.py::project_backlog/project_backlog_import_excel +
# excel_import.py (adaptado de import_tasks_from_excel, sin Django). El
# enlace "Descargar plantilla" SI esta (ver plantilla_importar_excel mas
# arriba, junto a crear_proyecto -- se reutiliza aqui y al crear un proyecto).

@router.get("/proyecto/{project_id}/backlog/")
def project_backlog(project_id: str, request: Request, usuario: str = Depends(auth.requiere_login)):
    proyecto = db.get_proyecto(project_id)
    if not proyecto:
        return RedirectResponse(url="/", status_code=303)
    tareas = db.load_tasks_para_tablero(project_id, borrada=False)
    backlog = sorted(
        [t for t in tareas if not t["sprint_id"]],
        key=lambda t: (STATUSES.index(t["status"]) if t["status"] in STATUSES else 99, t["orden"]),
    )
    open_sprints = [s for s in db.load_sprints(project_id) if s["estado"] != "cerrado"]
    return templates.TemplateResponse(request, "project_backlog.html", {
        "usuario": usuario, "activo": "backlog", "proyecto": proyecto, "proyecto_actual": project_id,
        "backlog": backlog, "open_sprints": open_sprints,
        "proj_cats": db.load_categorias_para_proyecto(project_id), "priorities": PRIORITIES, "statuses": STATUSES,
        "import_max_rows": excel_import.IMPORT_EXCEL_MAX_ROWS,
    })


@router.post("/proyecto/{project_id}/backlog/importar-excel/")
async def project_backlog_import_excel(
    project_id: str, excel_tareas: UploadFile = File(...), sprint_id: str = Form(""),
    usuario: str = Depends(auth.requiere_login),
):
    proyecto = db.get_proyecto(project_id)
    if not proyecto:
        return JSONResponse({"ok": False, "error": "proyecto no encontrado"}, status_code=404)
    if sprint_id and not db.get_sprint(sprint_id):
        sprint_id = ""

    tareas_actuales = db.load_tasks_para_tablero(project_id, borrada=False)
    titulos_existentes = {t["title"].strip().lower() for t in tareas_actuales}
    categorias = db.load_categorias_para_proyecto(project_id)
    sistemas = [s for s in db.load_sistemas() if s["activo"]]
    empresas = [e for e in db.load_empresas() if e["activo"]]
    iniciativas = [i for i in db.load_iniciativas() if i["activo"]]

    data = await excel_tareas.read()
    try:
        nuevas, avisos = excel_import.import_tasks_from_excel(
            BytesIO(data), excel_tareas.filename or "", len(data),
            titulos_existentes, categorias, sistemas, empresas, iniciativas, PRIORITIES,
        )
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    for t in nuevas:
        db.crear_tarea(
            str(uuid.uuid4())[:8], project_id, t["category"], t["title"], "Pendiente", t["priority"],
            t["description"], t["next_step"], t["fecha_inicio"], t["fecha_fin"],
            empresa_id=t["empresa_id"], iniciativa_id=t["iniciativa_id"], sistema_id=t["sistema_id"],
            sprint_id=sprint_id,
        )
    return JSONResponse({"ok": True, "importadas": len(nuevas), "avisos": avisos})


# ── gantt ────────────────────────────────────────────────────────────────────
# Igual que core/views.py::project_gantt + core/templates/project_gantt.html
# -- el posicionamiento real de barras/pines es JS puro (porcentajes segun
# fechas), igual que el original, no hay nada que calcular aqui salvo el
# rango gantt_start/gantt_end y separar tareas con/sin fechas.

@router.get("/proyecto/{project_id}/gantt/")
def project_gantt(project_id: str, request: Request, usuario: str = Depends(auth.requiere_login)):
    proyecto = db.get_proyecto(project_id)
    if not proyecto:
        return RedirectResponse(url="/", status_code=303)

    qp = request.query_params
    mode = qp.get("mode", "fechas")
    sprint_id_param = qp.get("sprint_id", "")
    view = qp.get("view", "Activas")
    if view not in ("Activas", "Todas", "Hechas"):
        view = "Activas"

    tareas = db.load_tasks_para_tablero(project_id, borrada=False)
    proj_ms = db.load_hitos_por_proyecto(project_id)
    proj_sprints = sorted(db.load_sprints(project_id), key=lambda s: s["numero"], reverse=True) if proyecto["tipo"] == "scrum" else []

    active_sprint = None
    if mode == "sprint" and proyecto["tipo"] == "scrum":
        if sprint_id_param:
            active_sprint = next((s for s in proj_sprints if s["sprint_id"] == sprint_id_param), None)
        if active_sprint is None and proj_sprints:
            active_sprint = next((s for s in proj_sprints if s["estado"] == "activo"), proj_sprints[0])
        if active_sprint:
            tareas = [t for t in tareas if t["sprint_id"] == active_sprint["sprint_id"]]
    else:
        mode = "fechas"

    # Igual que el filtro "view" del Tablero -- por defecto solo Activas
    # (oculta las Hechas), para que el Gantt de un proyecto con muchas
    # tareas ya cerradas no se dispare de alto por defecto.
    done_names = {c["nombre"] for c in db.load_board_columns(project_id) if c["es_done"]}
    if view == "Activas":
        tareas = [t for t in tareas if t["status"] not in done_names]
    elif view == "Hechas":
        tareas = [t for t in tareas if t["status"] in done_names]

    all_dates = []
    for t in tareas:
        if t["fecha_inicio"]:
            all_dates.append(t["fecha_inicio"])
        if t["fecha_fin"]:
            all_dates.append(t["fecha_fin"])
    for m in proj_ms:
        if m["fecha"]:
            all_dates.append(m["fecha"])
    if active_sprint:
        if active_sprint["fecha_inicio"]:
            all_dates.append(active_sprint["fecha_inicio"])
        if active_sprint["fecha_fin"]:
            all_dates.append(active_sprint["fecha_fin"])

    gantt_start = min(all_dates) if all_dates else ""
    gantt_end = max(all_dates) if all_dates else ""

    tasks_with_dates = [t for t in tareas if t["fecha_inicio"] and t["fecha_fin"]]
    tasks_without_dates = [t for t in tareas if not (t["fecha_inicio"] and t["fecha_fin"])]

    return templates.TemplateResponse(request, "project_gantt.html", {
        "usuario": usuario, "activo": "gantt", "proyecto": proyecto, "proyecto_actual": project_id,
        "mode": mode, "proj_sprints": proj_sprints, "active_sprint": active_sprint, "proj_ms": proj_ms,
        "gantt_start": gantt_start, "gantt_end": gantt_end, "view": view, "views": ["Activas", "Todas", "Hechas"],
        "tasks_with_dates": tasks_with_dates, "tasks_without_dates": tasks_without_dates,
    })


# ── tablero ──────────────────────────────────────────────────────────────────

@router.get("/proyecto/{project_id}/tablero/")
def ver_tablero(project_id: str, request: Request, usuario: str = Depends(auth.requiere_login)):
    proyecto = db.get_proyecto(project_id)
    if not proyecto:
        return RedirectResponse(url="/", status_code=303)
    puede_editar = _puede_editar_espacio_de(proyecto["espacio_id"], usuario)

    qp = request.query_params
    view = qp.get("view", "Activas")
    if view not in ("Activas", "Todas", "Hechas", "Borradas"):
        view = "Activas"
    query = qp.get("q", "").strip().lower()
    cat = qp.get("cat", "Todas")
    ia_filter = qp.get("ia", "Todas")
    if ia_filter not in ("Todas", "Si", "No"):
        ia_filter = "Todas"
    priority_filter = qp.get("priority", "Todas")
    if priority_filter not in ("Todas", *PRIORITIES):
        priority_filter = "Todas"
    sistema_filter = qp.get("sistema", "Todos")
    iniciativa_filter = qp.get("iniciativa", "Todas")
    date_from = qp.get("date_from", "").strip()
    date_to = qp.get("date_to", "").strip()

    proj_columns = db.load_board_columns(project_id)
    done_names = {c["nombre"] for c in proj_columns if c["es_done"]}

    # Resolucion de sprint igual que core/views.py::board: ?sprint_id= ->
    # sprint activo -> el mas reciente (numero mas alto) -- solo si el
    # proyecto es Scrum y ya tiene algun sprint creado.
    proj_sprints = db.load_sprints(project_id) if proyecto["tipo"] == "scrum" else []
    sprint = None
    if proj_sprints:
        sprint_id_param = qp.get("sprint_id", "")
        if sprint_id_param:
            sprint = next((s for s in proj_sprints if s["sprint_id"] == sprint_id_param), None)
        if sprint is None:
            sprint = next((s for s in proj_sprints if s["estado"] == "activo"), proj_sprints[0])

    def visible(t):
        if view == "Borradas":
            pass  # ya viene filtrado por borrada en la query
        if sprint is not None and t["sprint_id"] != sprint["sprint_id"]:
            return False
        if cat != "Todas" and t["category"] != cat:
            return False
        if ia_filter == "Si" and not t["generada_por_ia"]:
            return False
        if ia_filter == "No" and t["generada_por_ia"]:
            return False
        if priority_filter != "Todas" and t["priority"] != priority_filter:
            return False
        if sistema_filter != "Todos" and t["sistema_id"] != sistema_filter:
            return False
        if iniciativa_filter != "Todas" and t["iniciativa_id"] != iniciativa_filter:
            return False
        # Igual que core/views.py::_render_board: el rango de fechas filtra
        # por FECHA DE CREACION (creada_en), NO por fecha_inicio/fecha_fin --
        # el propio original lo etiqueta "Creadas entre" en el HTML. Ademas
        # creada_en incluye hora ("YYYY-MM-DD HH:MM") y se compara como
        # STRING contra date_from/date_to ("YYYY-MM-DD" puro), asi que
        # date_to excluye de facto las tareas creadas ESE MISMO DIA despues
        # de medianoche (una cadena con hora es lexicograficamente mayor que
        # la fecha sola) -- inconsistencia real heredada del original,
        # replicada tal cual a proposito (bug-compatible), no corregida aqui.
        if date_from and t["creada_en"] < date_from:
            return False
        if date_to and t["creada_en"] > date_to:
            return False
        if query:
            hay = " ".join([t["title"], t["category"], t["description"], t["next_step"]]).lower()
            if query not in hay:
                return False
        return True

    if view == "Borradas":
        tareas = [t for t in db.load_tasks_para_tablero(project_id, borrada=True) if visible(t)]
    else:
        todas = [t for t in db.load_tasks_para_tablero(project_id, borrada=False) if visible(t)]
        if view == "Activas":
            tareas = [t for t in todas if t["status"] not in done_names]
        elif view == "Hechas":
            tareas = [t for t in todas if t["status"] in done_names]
        else:
            tareas = todas

    if view == "Activas":
        disp_cols = [c for c in proj_columns if not c["es_done"]]
    elif view == "Hechas":
        disp_cols = [c for c in proj_columns if c["es_done"]]
    elif view == "Borradas":
        disp_cols = []
    else:
        disp_cols = proj_columns

    board_data = [
        {**c, "tasks": [t for t in tareas if t["status"] == c["nombre"]]}
        for c in disp_cols
    ]
    if view == "Borradas":
        board_data.append({"id": "", "nombre": "Borrada", "color": "#6b7280", "es_done": False,
                            "max_tareas": 0, "tasks": tareas})

    return templates.TemplateResponse(request, "tablero.html", {
        "usuario": usuario, "activo": "tablero", "proyecto": proyecto, "proyecto_actual": project_id,
        "board_data": board_data, "view": view, "query": qp.get("q", ""), "cat": cat, "ia_filter": ia_filter,
        "priority_filter": priority_filter, "sistema_filter": sistema_filter,
        "iniciativa_filter": iniciativa_filter, "date_from": date_from, "date_to": date_to,
        "views": ["Activas", "Todas", "Hechas", "Borradas"],
        "proj_cats": db.load_categorias_para_proyecto(project_id),
        "proj_columns": proj_columns, "column_colors": COLUMN_COLOR_PRESETS,
        "proyectos": db.load_proyectos_sidebar(), "priorities": PRIORITIES,
        "sistemas": db.load_sistemas(), "empresas": db.load_empresas(), "iniciativas": db.load_iniciativas(),
        "estados_proyecto": ESTADOS_PROYECTO, "tipos_proyecto": TIPOS_PROYECTO, "palette": COLOR_PALETTE,
        "sprint": sprint, "proj_sprints": proj_sprints,
        "mantis_base_url": os.getenv("MANTIS_BASE_URL", "").strip().rstrip("/"),
        "puede_editar": puede_editar,
        "miembros_asignables": db.load_miembros_espacio(proyecto["espacio_id"]) if proyecto["espacio_id"] else db.load_usuarios(),
    })


@router.get("/proyecto/{project_id}/tablero/exportar/")
def tablero_exportar_csv(project_id: str, request: Request, usuario: str = Depends(auth.requiere_login)):
    """Igual que core/views.py::board_export_csv -- mismo subconjunto
    reducido de filtros que el original (view/q/cat/priority/date_from/
    date_to; NO incluye sistema/iniciativa/ia, inconsistencia real ya
    presente en Django frente a los filtros completos del propio tablero,
    replicada tal cual, no corregida aqui)."""
    proyecto = db.get_proyecto(project_id)
    if not proyecto:
        return RedirectResponse(url="/", status_code=303)

    qp = request.query_params
    view = qp.get("view", "Todas")
    query = qp.get("q", "").strip().lower()
    cat = qp.get("cat", "Todas")
    priority_filter = qp.get("priority", "Todas")
    date_from = qp.get("date_from", "").strip()
    date_to = qp.get("date_to", "").strip()

    proj_columns = db.load_board_columns(project_id)
    done_names = {c["nombre"] for c in proj_columns if c["es_done"]}
    sprint_map = {s["sprint_id"]: s["nombre"] for s in db.load_sprints(project_id)} if proyecto["tipo"] == "scrum" else {}

    def visible(t):
        if view == "Borradas":
            pass  # ya viene filtrado por borrada en la query
        if view == "Activas" and t["status"] in done_names:
            return False
        if view == "Hechas" and t["status"] not in done_names:
            return False
        if cat != "Todas" and t["category"] != cat:
            return False
        if priority_filter != "Todas" and t["priority"] != priority_filter:
            return False
        if date_from and t["creada_en"] < date_from:
            return False
        if date_to and t["creada_en"] > date_to:
            return False
        if query:
            hay = " ".join([t["title"], t["category"], t["description"], t["next_step"]]).lower()
            if query not in hay:
                return False
        return True

    tareas = db.load_tasks_para_tablero(project_id, borrada=(view == "Borradas"))
    filtradas = sorted([t for t in tareas if visible(t)], key=lambda t: (t["orden"], t["title"].lower()))

    buf = StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["ID", "Titulo", "Estado", "Prioridad", "Categoria",
                      "Descripcion", "Proximo paso", "Creada", "Fecha fin", "Sprint",
                      "T.Estimado(h)", "T.Real(h)"])
    for t in filtradas:
        writer.writerow([
            t["task_id"], t["title"], t["status"], t["priority"], t["category"],
            t["description"], t["next_step"], t["creada_en"][:10] if t["creada_en"] else "",
            t["fecha_fin"], sprint_map.get(t["sprint_id"], ""),
            t["tiempo_estimado"], t["tiempo_real"],
        ])

    safe_name = "".join(c for c in proyecto["nombre"] if c.isalnum() or c in " -_")
    contenido = "﻿" + buf.getvalue()  # BOM utf-8-sig, igual que el original (Excel abre bien acentos)
    return Response(
        content=contenido, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}-tablero.csv"'},
    )


# ── columnas ─────────────────────────────────────────────────────────────────

def _permiso_columna(col_id: str, usuario: str, permiso: str) -> bool:
    proyecto_id = db.get_columna_proyecto_id(col_id)
    if not proyecto_id:
        return True
    return db.puede_actuar_en_proyecto(proyecto_id, db.get_user_id(usuario), permiso)


@router.post("/proyecto/{project_id}/columna/nueva/")
def crear_columna(
    request: Request, project_id: str, nombre: str = Form(""), color: str = Form(""), es_done: str = Form("false"),
    usuario: str = Depends(auth.requiere_login),
):
    if not db.puede_actuar_en_proyecto(project_id, db.get_user_id(usuario), "editores_gestionan_columnas"):
        flash(request, "error", "No tienes permiso para crear columnas en este proyecto.")
        return _redirect_tablero(project_id)
    nombre = nombre.strip()
    if nombre:
        color_final = color if color in COLUMN_COLOR_PRESETS else COLUMN_COLOR_PRESETS[-2]
        db.crear_columna(project_id, nombre, color_final, es_done == "true")
    return _redirect_tablero(project_id)


@router.post("/columna/{col_id}/renombrar/")
def renombrar_columna(
    request: Request, col_id: str, nombre: str = Form(""), color: str = Form(""),
    es_done: str = Form("false"), max_tareas: str = Form("0"), usuario: str = Depends(auth.requiere_login),
):
    referer = request.headers.get("referer") or "/"
    # Renombrar/recolorear una columna existente cuenta como "apariencia"
    # (un solo formulario junta nombre+color+es_done+max_tareas, no tiene
    # sentido partirlo en dos permisos) -- crear/mover/eliminar columnas
    # enteras es "gestionar_columnas", mas abajo.
    if not _permiso_columna(col_id, usuario, "editores_editan_apariencia"):
        flash(request, "error", "No tienes permiso para editar esta columna.")
        return RedirectResponse(url=referer, status_code=303)
    nombre = nombre.strip()
    try:
        max_int = max(0, min(99, int(max_tareas)))
    except ValueError:
        max_int = 0
    if nombre:
        color_final = color if color in COLUMN_COLOR_PRESETS else COLUMN_COLOR_PRESETS[-2]
        db.renombrar_columna(col_id, nombre, color_final, es_done == "true", max_int)
    return RedirectResponse(url=referer, status_code=303)


@router.post("/columna/{col_id}/mover/")
def mover_columna(request: Request, col_id: str, direction: str = Form("left"), usuario: str = Depends(auth.requiere_login)):
    referer = request.headers.get("referer") or "/"
    if not _permiso_columna(col_id, usuario, "editores_gestionan_columnas"):
        flash(request, "error", "No tienes permiso para mover columnas en este proyecto.")
        return RedirectResponse(url=referer, status_code=303)
    db.mover_columna(col_id, direction if direction in ("left", "right") else "left")
    return RedirectResponse(url=referer, status_code=303)


@router.post("/columna/{col_id}/eliminar/")
def eliminar_columna(request: Request, col_id: str, usuario: str = Depends(auth.requiere_login)):
    referer = request.headers.get("referer") or "/"
    if not _permiso_columna(col_id, usuario, "editores_gestionan_columnas"):
        flash(request, "error", "No tienes permiso para eliminar columnas en este proyecto.")
        return RedirectResponse(url=referer, status_code=303)
    db.eliminar_columna(col_id)
    return RedirectResponse(url=referer, status_code=303)


# ── tareas del tablero (modal completo) ─────────────────────────────────────

@router.post("/proyecto/{project_id}/tarea/nueva/")
def crear_tarea(
    project_id: str, request: Request, title: str = Form(""), category: str = Form(""), status: str = Form("Pendiente"),
    priority: str = Form("Normal"), description: str = Form(""), next_step: str = Form(""),
    fecha_inicio: str = Form(""), fecha_fin: str = Form(""), empresa_id: str = Form(""),
    sistema_id: str = Form(""), iniciativa_id: str = Form(""), anclada: str = Form("false"),
    subtareas: str = Form(""), tiempo_estimado: str = Form(""), tiempo_real: str = Form(""),
    sprint_id: str = Form(""), asignado_a: str = Form(""), usuario: str = Depends(auth.requiere_login),
):
    # acciones.crear_tarea: guarda + avisa al asignado + publica en el muro (igual que la API)
    if title.strip():
        try:
            acciones.crear_tarea(
                acciones.Actor.web(request, usuario), project_id, title, estado=status, prioridad=priority,
                descripcion=description, proximo_paso=next_step, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
                categoria=category, empresa_id=empresa_id, sistema_id=sistema_id, iniciativa_id=iniciativa_id,
                sprint_id=sprint_id, asignado_a=asignado_a.strip() or None, subtareas=subtareas,
                tiempo_estimado=tiempo_estimado.strip() or None, tiempo_real=tiempo_real.strip() or None,
                anclada=(anclada == "true"),
            )
        except acciones.AccionError as e:
            flash(request, "error", e.mensaje)
    return _redirect_tablero(project_id)


@router.post("/proyecto/{project_id}/tarea/rapida/")
def crear_tarea_rapida(
    project_id: str, request: Request, title: str = Form(""), status: str = Form("Pendiente"), sprint_id: str = Form(""),
    usuario: str = Depends(auth.requiere_login),
):
    if title.strip():
        try:
            acciones.crear_tarea(acciones.Actor.web(request, usuario), project_id, title, estado=status, sprint_id=sprint_id)
        except acciones.AccionError as e:
            flash(request, "error", e.mensaje)
    return _redirect_tablero(project_id)


@router.post("/tarea/{task_id}/editar-completa/")
def editar_tarea(
    task_id: str, request: Request, proyecto: str = Form(...), title: str = Form(""), category: str = Form(""),
    status: str = Form(""), priority: str = Form(""), description: str = Form(""), next_step: str = Form(""),
    fecha_inicio: str = Form(""), fecha_fin: str = Form(""), empresa_id: str = Form(""),
    sistema_id: str = Form(""), iniciativa_id: str = Form(""), anclada: str = Form("false"),
    subtareas: str = Form(""), tiempo_estimado: str = Form(""), tiempo_real: str = Form(""),
    sprint_id: str = Form(""), asignado_a: str = Form(""), usuario: str = Depends(auth.requiere_login),
):
    # El modal manda TODOS los campos. Si cerrarla no se puede porque quedan
    # subtareas sin marcar, el resto se guarda y el estado se queda como
    # estaba (si_bloquea_cierre='revertir'), igual que siempre.
    try:
        acciones.editar_tarea(
            acciones.Actor.web(request, usuario), task_id, proyecto_id=proyecto, titulo=title, estado=status,
            prioridad=priority, descripcion=description, proximo_paso=next_step, fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin, categoria=category, empresa_id=empresa_id, sistema_id=sistema_id,
            iniciativa_id=iniciativa_id, sprint_id=sprint_id, asignado_a=asignado_a.strip() or None,
            subtareas=subtareas, tiempo_estimado=tiempo_estimado.strip() or None,
            tiempo_real=tiempo_real.strip() or None, anclada=(anclada == "true"),
        )
    except acciones.AccionError as e:
        flash(request, "error", e.mensaje)
    return _redirect_tablero(proyecto)


@router.post("/tarea/{task_id}/reordenar/")
def reordenar_tarea(task_id: str, request: Request, status: str = Form(...), before_id: str = Form(""),
                    usuario: str = Depends(auth.requiere_login)):
    try:
        acciones.mover_tarea(acciones.Actor.web(request, usuario), task_id, status, before_id)
    except acciones.AccionError as e:
        return JSONResponse({"ok": False, "error": e.mensaje}, status_code=e.codigo)
    return JSONResponse({"ok": True})


@router.post("/tarea/{task_id}/borrar-tablero/")
def borrar_tarea(task_id: str, request: Request, proyecto: str = Form(...), usuario: str = Depends(auth.requiere_login)):
    # el proyecto y el permiso se resuelven de la BD dentro de la accion (no
    # del campo 'proyecto' del formulario, que solo sirve para volver)
    try:
        acciones.eliminar_tarea(acciones.Actor.web(request, usuario), task_id)
    except acciones.AccionError as e:
        flash(request, "error", "No tienes permiso para eliminar esta tarea." if e.codigo == 403 else e.mensaje)
    return _redirect_tablero(proyecto)


@router.post("/tarea/{task_id}/duplicar/")
def duplicar_tarea(task_id: str, usuario: str = Depends(auth.requiere_login)):
    proyecto_id, _, _, _ = db.tarea_estado_actual(task_id)
    if not proyecto_id:
        return RedirectResponse(url="/", status_code=303)
    db.duplicar_tarea(task_id)
    return _redirect_tablero(proyecto_id)


@router.post("/tarea/{task_id}/restaurar/")
def restaurar_tarea(task_id: str, request: Request, proyecto: str = Form(...), usuario: str = Depends(auth.requiere_login)):
    try:
        acciones.restaurar_tarea(acciones.Actor.web(request, usuario), task_id)
    except acciones.AccionError as e:
        flash(request, "error", e.mensaje)
    return _redirect_tablero(proyecto)


@router.post("/tarea/borrar-varios/")
def tareas_borrar_varias(task_ids: str = Form("[]"), usuario: str = Depends(auth.requiere_login)):
    """Selección múltiple + borrado en bloque -- igual que
    core/views.py::task_bulk_delete + core/templates/board.html
    (_selectedIds/bulkDelete()): task_ids llega como un campo de formulario
    cuyo VALOR es una cadena JSON con la lista de ids (no un body JSON
    raíz), igual que en el original."""
    try:
        ids = [i for i in json.loads(task_ids) if isinstance(i, str)]
    except (ValueError, TypeError):
        ids = []
    borradas = db.borrar_tareas_bulk(ids)
    return JSONResponse({"ok": True, "deleted": borradas})


# ── sprints (Scrum) ──────────────────────────────────────────────────────────

@router.get("/proyecto/{project_id}/sprints/")
def ver_sprints(project_id: str, request: Request, usuario: str = Depends(auth.requiere_login)):
    proyecto = db.get_proyecto(project_id)
    if not proyecto:
        return RedirectResponse(url="/", status_code=303)
    proj_sprints = db.load_sprints(project_id)
    sprint_counts = db.sprint_counts_por_proyecto(project_id, [s["sprint_id"] for s in proj_sprints])
    return templates.TemplateResponse(request, "project_sprints.html", {
        "usuario": usuario, "activo": "sprints", "proyecto": proyecto, "proyecto_actual": project_id,
        "proj_sprints": proj_sprints, "sprint_counts": sprint_counts, "sprint_statuses": db.SPRINT_STATUSES,
    })


@router.get("/proyecto/{project_id}/sprint/{sprint_id}/")
def ver_sprint_en_tablero(project_id: str, sprint_id: str):
    """Igual que core/views.py::sprint_board: el Tablero de un sprint
    concreto es el mismo Tablero, acotado via ?sprint_id=."""
    return RedirectResponse(url=f"/proyecto/{project_id}/tablero/?sprint_id={sprint_id}", status_code=303)


@router.get("/proyecto/{project_id}/tareas/sin-sprint/")
def tareas_sin_sprint_json(project_id: str, usuario: str = Depends(auth.requiere_login)):
    return JSONResponse({"tasks": db.load_tareas_sin_sprint(project_id)})


@router.post("/proyecto/{project_id}/sprint/nuevo/")
def crear_sprint(
    project_id: str, nombre: str = Form(""), fecha_inicio: str = Form(""), fecha_fin: str = Form(""),
    estado: str = Form("planificado"), objetivo: str = Form(""), usuario: str = Depends(auth.requiere_login),
):
    if estado not in db.SPRINT_STATUSES:
        estado = "planificado"
    db.crear_sprint(project_id, nombre.strip(), fecha_inicio.strip(), fecha_fin.strip(), estado, objetivo.strip())
    return RedirectResponse(url=f"/proyecto/{project_id}/sprints/", status_code=303)


@router.post("/sprint/{sprint_id}/editar/")
def editar_sprint(
    sprint_id: str, nombre: str = Form(""), fecha_inicio: str = Form(""), fecha_fin: str = Form(""),
    estado: str = Form("planificado"), objetivo: str = Form(""), usuario: str = Depends(auth.requiere_login),
):
    actual = db.get_sprint(sprint_id)
    if not actual:
        return RedirectResponse(url="/", status_code=303)
    if estado not in db.SPRINT_STATUSES:
        estado = actual["estado"]
    db.editar_sprint(sprint_id, nombre.strip() or actual["nombre"], fecha_inicio.strip(), fecha_fin.strip(),
                      estado, objetivo.strip())
    return RedirectResponse(url=f"/proyecto/{actual['proyecto_id']}/sprints/", status_code=303)


@router.post("/sprint/{sprint_id}/cerrar/")
def cerrar_sprint(sprint_id: str, usuario: str = Depends(auth.requiere_login)):
    actual = db.get_sprint(sprint_id)
    if not actual:
        return RedirectResponse(url="/", status_code=303)
    nuevo_id = db.cerrar_sprint(sprint_id)
    if not nuevo_id:
        return RedirectResponse(url=f"/proyecto/{actual['proyecto_id']}/sprints/", status_code=303)
    return RedirectResponse(url=f"/proyecto/{actual['proyecto_id']}/sprint/{nuevo_id}/", status_code=303)


@router.post("/sprint/{sprint_id}/tarea/anadir/")
def anadir_tarea_a_sprint(sprint_id: str, task_id: str = Form(...), usuario: str = Depends(auth.requiere_login)):
    actual = db.get_sprint(sprint_id)
    if not actual:
        return RedirectResponse(url="/", status_code=303)
    db.sprint_add_task(sprint_id, task_id)
    return RedirectResponse(url=f"/proyecto/{actual['proyecto_id']}/sprint/{sprint_id}/", status_code=303)


@router.post("/sprint/{sprint_id}/tareas/anadir-varias/")
def anadir_tareas_a_sprint_bulk(sprint_id: str, task_ids: str = Form("[]"), usuario: str = Depends(auth.requiere_login)):
    actual = db.get_sprint(sprint_id)
    try:
        ids = list(set(json.loads(task_ids)))
    except Exception:
        ids = []
    added = db.sprint_add_tasks_bulk(sprint_id, ids) if actual else 0
    return JSONResponse({"ok": bool(actual), "added": added})


@router.post("/sprint/{sprint_id}/tarea/{task_id}/quitar/")
def quitar_tarea_de_sprint(sprint_id: str, task_id: str, usuario: str = Depends(auth.requiere_login)):
    actual = db.get_sprint(sprint_id)
    if not actual:
        return RedirectResponse(url="/", status_code=303)
    db.sprint_remove_task(sprint_id, task_id)
    return RedirectResponse(url=f"/proyecto/{actual['proyecto_id']}/sprint/{sprint_id}/", status_code=303)


# ── hitos (milestones), abiertos desde el sidebar en cualquier pagina ───────
# Igual que core/views.py::milestone_new/milestone_edit -- sin ruta de
# borrado individual porque el original tampoco la tiene. Ambas rutas
# redirigen siempre al tablero del proyecto, sea cual sea la pagina desde la
# que se abrio el modal (mismo "salto" que hace el original a project_home).

@router.post("/hito/nuevo/{project_id}/")
def crear_hito(
    project_id: str, nombre: str = Form(""), fecha: str = Form(""), completado: str = Form(""),
    usuario: str = Depends(auth.requiere_login),
):
    nombre = nombre.strip()
    if nombre:
        db.crear_hito(project_id, nombre, fecha.strip(), completado == "on")
    return _redirect_tablero(project_id)


@router.post("/hito/{milestone_id}/editar/")
def editar_hito(
    milestone_id: str, nombre: str = Form(""), fecha: str = Form(""), completado: str = Form(""),
    usuario: str = Depends(auth.requiere_login),
):
    actual = db.get_hito(milestone_id)
    if not actual:
        return RedirectResponse(url="/", status_code=303)
    db.editar_hito(milestone_id, nombre.strip() or actual["nombre"], fecha.strip(), completado == "on")
    return _redirect_tablero(actual["proyecto_id"])
