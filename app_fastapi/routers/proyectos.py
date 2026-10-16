# -*- coding: utf-8 -*-
"""Tableros globales Kanban/Scrum (los dos enlaces de la cabecera que hasta
ahora eran marcadores) -- copiado de core/views.py::board_kanban_global/
board_scrum_global/_render_global_board + core/templates/board_global.html.

Es la version de SOLO LECTURA que ya trae la app real para esta vista
concreta (junta las tareas de todos los proyectos de un tipo en un unico
tablero, sin crear/editar tarea ni arrastrar tarjetas entre columnas -- eso
solo existe en el tablero de un proyecto, que es una pagina mas grande y
queda pendiente, ver README). O sea que aqui no hay ninguna simplificacion
respecto al original: esta pagina en concreto YA era de solo lectura en la
app Django."""
import random
import uuid

from fastapi import APIRouter, Depends, Form
from fastapi.requests import Request
from fastapi.responses import RedirectResponse

from .. import auth, db, muro
from ..flash import flash
from ..templating import templates

router = APIRouter(tags=["proyectos"])

# Misma paleta que routers/tablero.py::COLOR_PALETTE (la que usa el
# selector de color en toda la app) -- se repite aqui, no se importa de
# tablero.py, mismo patron de duplicacion deliberada que ya existe entre
# tablero.py y configuracion.py.
COLOR_PALETTE = [
    "#2563eb", "#7c3aed", "#db2777", "#ea580c",
    "#16a34a", "#0891b2", "#9333ea", "#b45309",
    "#0f766e", "#c2410c",
]


def _darken_hex(color: str, factor: float = 0.6) -> str:
    """Puerto literal de board_hero.py::darken_hex de CS Manager (otro
    proyecto propio) -- solo para el degradado del hero de /espacios/."""
    h = color.lstrip("#")
    if len(h) != 6:
        return color
    r = max(0, int(int(h[0:2], 16) * factor))
    g = max(0, int(int(h[2:4], 16) * factor))
    b = max(0, int(int(h[4:6], 16) * factor))
    return f"#{r:02x}{g:02x}{b:02x}"


def _espacio_hero_svg(seed: str) -> str:
    """Puerto literal de board_hero.py::board_hero_svg de CS Manager --
    patron decorativo (circulos translucidos), sembrado por el id del
    espacio para que sea el mismo patron cada vez, no aleatorio de verdad.
    Solo decorativo, no sensible a seguridad."""
    rng = random.Random(seed)  # nosec B311
    w, h = 1200, 220
    parts = []
    for _ in range(10):
        cx, cy, r = rng.randint(-100, w + 100), rng.randint(-100, h + 100), rng.randint(50, 180)
        op = round(rng.uniform(0.04, 0.16), 2)
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="white" opacity="{op}"/>')
    for _ in range(35):
        cx, cy, r = rng.randint(0, w), rng.randint(0, h), rng.randint(2, 10)
        op = round(rng.uniform(0.10, 0.35), 2)
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="white" opacity="{op}"/>')
    return "\n  ".join(parts)


@router.get("/espacios/")
def espacios_listado(request: Request, usuario: str = Depends(auth.requiere_login)):
    """Listado de espacios (botón "Espacios" de la cabecera, ver
    _base.html) -- solo tarjetas (nombre, tipo, nº de proyectos/miembros),
    cada una enlaza a su detalle, mas el alta de un espacio nuevo. Sin
    filtrar por pertenencia todavía (ver CLAUDE.md, sección Espacios): se
    ven todos."""
    espacios = [e for e in db.load_espacios() if e["activo"]]
    return templates.TemplateResponse(request, "espacios.html", {
        "usuario": usuario, "activo": "espacios", "palette": COLOR_PALETTE,
        "personales": [e for e in espacios if e["es_personal"]],
        "compartidos": [e for e in espacios if not e["es_personal"]],
    })


@router.post("/espacio/nuevo/")
def crear_espacio(nombre: str = Form(""), color: str = Form(""), usuario: str = Depends(auth.requiere_login)):
    nombre = nombre.strip()
    if not nombre:
        return RedirectResponse(url="/espacios/", status_code=303)
    espacio_id = str(uuid.uuid4())[:8]
    db.crear_espacio(espacio_id, nombre, color or COLOR_PALETTE[0], db.get_user_id(usuario))
    return RedirectResponse(url=f"/espacio/{espacio_id}/", status_code=303)


def _es_admin_espacio(espacio_id: str, usuario: str) -> bool:
    return db.puede_administrar_espacio(espacio_id, db.get_user_id(usuario))


@router.post("/espacio/{espacio_id}/editar/")
def editar_espacio(
    request: Request, espacio_id: str, nombre: str = Form(""), color: str = Form(""),
    usuario: str = Depends(auth.requiere_login),
):
    if not _es_admin_espacio(espacio_id, usuario):
        flash(request, "error", "Solo un Administrador de este espacio puede editarlo.")
        return RedirectResponse(url=f"/espacio/{espacio_id}/", status_code=303)
    nombre = nombre.strip()
    if nombre:
        db.editar_espacio(espacio_id, nombre, color or COLOR_PALETTE[0])
    return RedirectResponse(url=f"/espacio/{espacio_id}/", status_code=303)


@router.post("/espacio/{espacio_id}/proyecto/{proyecto_id}/eliminar/")
def eliminar_proyecto_de_espacio(
    request: Request, espacio_id: str, proyecto_id: str, confirmacion: str = Form(""),
    usuario: str = Depends(auth.requiere_login),
):
    """Unico sitio de toda la app donde se puede borrar un proyecto --
    antes vivia en un modal local de tablero.html, reachable solo desde un
    boton que ya se quito de la cabecera del Tablero (ver
    project_config_scope en la memoria de esta sesion). Doble confirmacion
    a proposito (showConfirm() + escribir el nombre exacto en
    'confirmacion', comprobado tambien aqui por si alguien se salta el JS):
    borrar un proyecto es mucho mas dificil de deshacer que quitar a
    alguien de un espacio."""
    if not _es_admin_espacio(espacio_id, usuario):
        flash(request, "error", "Solo un Administrador de este espacio puede eliminar un proyecto.")
        return RedirectResponse(url=f"/espacio/{espacio_id}/", status_code=303)
    proyecto = db.get_proyecto(proyecto_id)
    if not proyecto or proyecto["espacio_id"] != espacio_id:
        flash(request, "error", "Ese proyecto no pertenece a este espacio.")
        return RedirectResponse(url=f"/espacio/{espacio_id}/", status_code=303)
    if confirmacion.strip() != proyecto["nombre"]:
        flash(request, "error", "El nombre escrito no coincide -- el proyecto NO se ha eliminado.")
        return RedirectResponse(url=f"/espacio/{espacio_id}/", status_code=303)
    if db.eliminar_proyecto(proyecto_id):
        flash(request, "success", f"Proyecto «{proyecto['nombre']}» eliminado. Sus tareas pasaron a «general».")
    else:
        flash(request, "error", "Ese proyecto no se puede eliminar.")
    return RedirectResponse(url=f"/espacio/{espacio_id}/", status_code=303)


@router.post("/espacio/{espacio_id}/toggle/")
def toggle_espacio(request: Request, espacio_id: str, usuario: str = Depends(auth.requiere_login)):
    if not _es_admin_espacio(espacio_id, usuario):
        flash(request, "error", "Solo un Administrador de este espacio puede activarlo/desactivarlo.")
        return RedirectResponse(url=f"/espacio/{espacio_id}/", status_code=303)
    if not db.toggle_espacio(espacio_id):
        flash(request, "error", "Un espacio personal no se puede desactivar.")
        return RedirectResponse(url=f"/espacio/{espacio_id}/", status_code=303)
    return RedirectResponse(url="/espacios/", status_code=303)


@router.post("/espacio/{espacio_id}/miembro/anadir/")
def espacio_miembro_anadir(
    request: Request, espacio_id: str, user_id: str = Form(""), rol: str = Form("editor"),
    usuario: str = Depends(auth.requiere_login),
):
    if not _es_admin_espacio(espacio_id, usuario):
        flash(request, "error", "Solo un Administrador de este espacio puede añadir miembros.")
        return RedirectResponse(url=f"/espacio/{espacio_id}/", status_code=303)
    if user_id.strip():
        rol = rol if rol in ("admin", "editor", "lector") else "editor"
        db.agregar_miembro_espacio(espacio_id, int(user_id), rol)
        muro.miembro_anadido(espacio_id, db.get_user_id(usuario), int(user_id), rol)
    return RedirectResponse(url=f"/espacio/{espacio_id}/", status_code=303)


@router.post("/espacio/{espacio_id}/miembro/{user_id}/quitar/")
def espacio_miembro_quitar(request: Request, espacio_id: str, user_id: int, usuario: str = Depends(auth.requiere_login)):
    if not _es_admin_espacio(espacio_id, usuario):
        flash(request, "error", "Solo un Administrador de este espacio puede quitar miembros.")
        return RedirectResponse(url=f"/espacio/{espacio_id}/", status_code=303)
    db.quitar_miembro_espacio(espacio_id, user_id)
    muro.miembro_quitado(espacio_id, db.get_user_id(usuario), user_id)
    return RedirectResponse(url=f"/espacio/{espacio_id}/", status_code=303)


@router.post("/espacio/{espacio_id}/miembro/{user_id}/rol/")
def espacio_miembro_rol(
    request: Request, espacio_id: str, user_id: int, rol: str = Form(...),
    usuario: str = Depends(auth.requiere_login),
):
    if not _es_admin_espacio(espacio_id, usuario):
        flash(request, "error", "Solo un Administrador de este espacio puede cambiar roles.")
        return RedirectResponse(url=f"/espacio/{espacio_id}/", status_code=303)
    if rol in ("admin", "editor", "lector"):
        db.cambiar_rol_miembro_espacio(espacio_id, user_id, rol)
        muro.miembro_rol(espacio_id, db.get_user_id(usuario), user_id, rol)
    return RedirectResponse(url=f"/espacio/{espacio_id}/", status_code=303)


@router.get("/espacio/{espacio_id}/")
def espacio_detalle(espacio_id: str, request: Request, usuario: str = Depends(auth.requiere_login)):
    """Detalle de un espacio -- hero + tarjetas de sus proyectos (con un
    mini resumen: tipo y nº de tareas) + gestion de miembros/roles, al
    estilo del board_detail.html de CS Manager (otro proyecto propio)."""
    espacio = db.get_espacio(espacio_id)
    if not espacio:
        return RedirectResponse(url="/espacios/", status_code=303)
    proyectos = db.load_proyectos_por_espacio(espacio_id)
    tareas_por_proyecto = db.contar_tareas_por_proyecto([p["id"] for p in proyectos])
    for p in proyectos:
        p["n_tareas"] = tareas_por_proyecto.get(p["id"], 0)
    user_id = db.get_user_id(usuario)
    puede_administrar = (not espacio["es_personal"]) and db.puede_administrar_espacio(espacio_id, user_id)
    puede_editar = espacio["es_personal"] or db.puede_editar_espacio(espacio_id, user_id)
    return templates.TemplateResponse(request, "espacio_detalle.html", {
        "usuario": usuario, "activo": "espacios", "espacio": espacio, "proyectos": proyectos,
        "miembros": [] if espacio["es_personal"] else db.load_miembros_espacio(espacio_id),
        "hero_dark": _darken_hex(espacio["color"]), "hero_svg": _espacio_hero_svg(espacio_id),
        "puede_administrar": puede_administrar, "puede_editar": puede_editar,
        "usuarios": db.load_usuarios() if puede_administrar else [],
        "permisos": db.get_permisos_espacio(espacio_id) if puede_administrar else {},
        "puede_ver_muro": muro.acceso(espacio, user_id, bool(request.session.get("es_it"))) is not None,
        "muro_sin_leer": db.contar_muros_sin_leer(user_id).get(espacio_id, 0) if user_id else 0,
    })


@router.post("/espacio/{espacio_id}/permisos/")
def editar_permisos_espacio_route(
    request: Request, espacio_id: str,
    editores_mueven_tareas_ajenas: str = Form(""), editores_eliminan_tareas_ajenas: str = Form(""),
    editores_gestionan_columnas: str = Form(""), editores_editan_apariencia: str = Form(""),
    editores_gestionan_documentos_wiki: str = Form(""), usuario: str = Depends(auth.requiere_login),
):
    if not _es_admin_espacio(espacio_id, usuario):
        flash(request, "error", "Solo un Administrador de este espacio puede cambiar sus permisos.")
        return RedirectResponse(url=f"/espacio/{espacio_id}/", status_code=303)
    db.editar_permisos_espacio(
        espacio_id,
        editores_mueven_tareas_ajenas=bool(editores_mueven_tareas_ajenas),
        editores_eliminan_tareas_ajenas=bool(editores_eliminan_tareas_ajenas),
        editores_gestionan_columnas=bool(editores_gestionan_columnas),
        editores_editan_apariencia=bool(editores_editan_apariencia),
        editores_gestionan_documentos_wiki=bool(editores_gestionan_documentos_wiki),
    )
    return RedirectResponse(url=f"/espacio/{espacio_id}/", status_code=303)


def _render_global_board(request: Request, usuario: str, tipo: str, activo: str, titulo: str, icono: str):
    proyectos = db.load_proyectos_por_tipo(tipo)
    proyecto_ids = [p["id"] for p in proyectos]
    proj_map = {p["id"]: p for p in proyectos}
    done_names_por_proyecto = db.done_status_names_by_project()

    qp = request.query_params
    view = qp.get("view", "Activas")
    if view not in ("Activas", "Todas", "Hechas", "Borradas"):
        view = "Activas"
    query = qp.get("q", "").strip().lower()

    def es_hecha(t):
        return t["status"] in done_names_por_proyecto.get(t["proyecto_id"], {"Hecha"})

    if view == "Borradas":
        visibles = db.load_tasks_por_proyectos(proyecto_ids, borrada=True, query=query)
    else:
        todas = db.load_tasks_por_proyectos(proyecto_ids, borrada=False, query=query)
        if view == "Activas":
            visibles = [t for t in todas if not es_hecha(t)]
        elif view == "Hechas":
            visibles = [t for t in todas if es_hecha(t)]
        else:
            visibles = todas
    visibles.sort(key=lambda t: (t["orden"], t["title"].lower()))

    all_cols = db.board_columns_union(proyecto_ids)
    if view == "Activas":
        disp_cols = [c for c in all_cols if not c["es_done"]]
    elif view == "Hechas":
        disp_cols = [c for c in all_cols if c["es_done"]]
    elif view == "Borradas":
        disp_cols = []
    else:
        disp_cols = all_cols

    board_data = [
        {"name": c["nombre"], "color": c["color"], "tasks": [t for t in visibles if t["status"] == c["nombre"]]}
        for c in disp_cols
    ]
    if view == "Borradas":
        board_data.append({"name": "Borrada", "color": "#6b7280", "tasks": visibles})

    return templates.TemplateResponse(request, "board_global.html", {
        "usuario": usuario, "activo": activo, "icono": icono, "page_title": titulo,
        "board_data": board_data, "view": view, "query": qp.get("q", ""),
        "proj_map": proj_map, "views": ["Activas", "Todas", "Hechas", "Borradas"],
    })


@router.get("/kanban/")
def kanban_global(request: Request, usuario: str = Depends(auth.requiere_login)):
    return _render_global_board(request, usuario, "kanban", "kanban_global", "Todos los proyectos Kanban", "columns")


@router.get("/scrum/")
def scrum_global(request: Request, usuario: str = Depends(auth.requiere_login)):
    return _render_global_board(request, usuario, "scrum", "scrum_global", "Todos los proyectos Scrum", "layers")
