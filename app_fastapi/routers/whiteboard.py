# -*- coding: utf-8 -*-
"""Whiteboard: pizarra tipo Paint, global (no ligada a ningun proyecto),
reeditable. Copiado de core/views.py::whiteboard/whiteboard_editor/
whiteboard_image/whiteboard_save/whiteboard_delete + core/db_store.py
(load_whiteboards/get_whiteboard/create_whiteboard/update_whiteboard/
delete_whiteboard) + core/templates/whiteboard.html/whiteboard_editor.html +
static/js/whiteboard.js (copiado tal cual -- es JS puro, sin nada de Django
dentro, la unica pieza de esta v2 que no ha necesitado ni un cambio de
plantilla ademas del propio JS).

Simplificaciones deliberadas frente al original:
- CSRF SI esta (ver app_fastapi/csrf.py + README): el header X-CSRFToken
  que ya mandaba whiteboard.js (copiado literal del original) ahora SI se
  valida de verdad, sin haber tenido que tocar ese JS para nada.
- El widget "Pizarras sin guardar" de Configuracion -> Sistema (lista los
  borradores en localStorage con enlaces Restaurar/Descartar) no se ha
  portado -- es secundario, y el propio '?restaurar_borrador=1' de la URL
  ya funciona igual si se llega a el a mano o desde un enlace guardado.
- media/whiteboards/ (miniaturas PNG) es la MISMA carpeta que usa la app
  Django real (BASE_DIR/media), no una copia aparte -- las pizarras viven en
  la misma tabla `whiteboards` compartida, asi que sus miniaturas deben
  vivir en el mismo sitio en disco para que las dos apps las vean."""
import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.requests import Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from .. import auth, db
from ..templating import templates

router = APIRouter(tags=["whiteboard"])

WHITEBOARD_MAX_CONTENIDO_MB = 2
WHITEBOARD_MAX_THUMB_MB = 3

# Igual que core/models.py::PROJECT_PALETTE -- reutilizada aqui tal cual como
# paleta de colores del editor (swatches de la barra superior).
PALETTE = [
    "#2563eb", "#7c3aed", "#db2777", "#ea580c",
    "#16a34a", "#0891b2", "#9333ea", "#b45309",
    "#0f766e", "#c2410c",
]


def _whiteboard_dir() -> Path:
    """Subcarpeta de db.media_dir() (misma media/ que Documentos, ver
    tablero.py) -- las miniaturas de Whiteboard SI van aparte, a diferencia
    de los adjuntos de Documentos, que van sueltos en media/ directamente."""
    p = db.media_dir() / "whiteboards"
    p.mkdir(parents=True, exist_ok=True)
    return p


@router.get("/whiteboard/")
def whiteboard_home(request: Request, usuario: str = Depends(auth.requiere_login)):
    return templates.TemplateResponse(request, "whiteboard.html", {
        "usuario": usuario, "activo": "whiteboard", "whiteboards": db.load_whiteboards(),
    })


def _render_editor(request: Request, usuario: str, whiteboard_id: str = None, reunion_id_nueva: str = "",
                    agenda_fecha_nueva: str = ""):
    wb = db.get_whiteboard(whiteboard_id) if whiteboard_id else None
    try:
        contenido_obj = json.loads(wb["contenido"]) if wb and wb["contenido"] else []
    except (ValueError, TypeError):
        contenido_obj = []
    # reunion_id/agenda_fecha de una pizarra NUEVA llegan por query string
    # (desde "+ Crear whiteboard para esta reunión"/"...este día" en
    # /reunion/<id>/ y /agenda/<fecha>/) -- solo importa la primera vez
    # (whiteboard.js solo las manda si !whiteboardId); una pizarra YA
    # existente usa las suyas propias (wb["reunion_id"]/wb["agenda_fecha"]),
    # que no cambian aqui.
    reunion_id_activa = (wb["reunion_id"] if wb else reunion_id_nueva) or ""
    agenda_fecha_activa = (wb["agenda_fecha"] if wb else agenda_fecha_nueva) or ""
    reunion = db.get_reunion_calendario(reunion_id_activa) if reunion_id_activa else None
    if reunion:
        volver_url = f"/reunion/{reunion_id_activa}/"
    elif agenda_fecha_activa:
        volver_url = f"/agenda/{agenda_fecha_activa}/"
    else:
        volver_url = "/whiteboard/"
    return templates.TemplateResponse(request, "whiteboard_editor.html", {
        "usuario": usuario, "activo": "whiteboard", "whiteboard": wb,
        "contenido_obj": contenido_obj, "palette": PALETTE,
        "reunion_id_nueva": reunion_id_nueva,
        "agenda_fecha_nueva": agenda_fecha_nueva,
        "reunion_vinculada": reunion["titulo"] if reunion else None,
        "volver_url": volver_url,
    })


@router.get("/whiteboard/nuevo/")
def whiteboard_new(request: Request, reunion_id: str = "", agenda_fecha: str = "",
                    usuario: str = Depends(auth.requiere_login)):
    return _render_editor(request, usuario, reunion_id_nueva=reunion_id.strip(),
                           agenda_fecha_nueva=agenda_fecha.strip())


@router.get("/whiteboard/{whiteboard_id}/editar/")
def whiteboard_edit(whiteboard_id: str, request: Request, usuario: str = Depends(auth.requiere_login)):
    wb = db.get_whiteboard(whiteboard_id)
    if not wb:
        return RedirectResponse(url="/whiteboard/", status_code=303)
    return _render_editor(request, usuario, whiteboard_id)


@router.get("/whiteboard/{whiteboard_id}/imagen/")
def whiteboard_image(whiteboard_id: str, usuario: str = Depends(auth.requiere_login)):
    wb = db.get_whiteboard(whiteboard_id)
    if not wb or not wb["thumbnail"]:
        return RedirectResponse(url="/whiteboard/", status_code=303)
    path = _whiteboard_dir() / wb["thumbnail"]
    if not path.exists():
        return RedirectResponse(url="/whiteboard/", status_code=303)
    return FileResponse(path, media_type="image/png")


@router.post("/whiteboard/guardar/")
async def whiteboard_save(
    whiteboard_id: str = Form(""), titulo: str = Form(""), contenido: str = Form("[]"),
    reunion_id: str = Form(""), agenda_fecha: str = Form(""), thumbnail: Optional[UploadFile] = File(None),
    usuario: str = Depends(auth.requiere_login),
):
    whiteboard_id = whiteboard_id.strip()
    titulo = titulo.strip() or "Sin título"
    contenido = contenido.strip() or "[]"

    if len(contenido.encode("utf-8")) > WHITEBOARD_MAX_CONTENIDO_MB * 1024 * 1024:
        return JSONResponse(
            {"ok": False, "error": f"el contenido pesa demasiado (maximo {WHITEBOARD_MAX_CONTENIDO_MB} MB)"},
            status_code=400,
        )
    try:
        json.loads(contenido)
    except (ValueError, TypeError):
        return JSONResponse({"ok": False, "error": "contenido invalido"}, status_code=400)

    existing = db.get_whiteboard(whiteboard_id) if whiteboard_id else None
    if whiteboard_id and not existing:
        return JSONResponse({"ok": False, "error": "pizarra no encontrada"}, status_code=404)

    thumbnail_filename = existing["thumbnail"] if existing else ""
    if thumbnail is not None and thumbnail.filename:
        data = await thumbnail.read()
        if len(data) > WHITEBOARD_MAX_THUMB_MB * 1024 * 1024:
            return JSONResponse(
                {"ok": False, "error": f"la miniatura pesa demasiado (maximo {WHITEBOARD_MAX_THUMB_MB} MB)"},
                status_code=400,
            )
        if not thumbnail_filename:
            thumbnail_filename = str(uuid.uuid4()) + ".png"
        (_whiteboard_dir() / thumbnail_filename).write_bytes(data)

    version_hash = hashlib.sha1(f"{whiteboard_id or 'nuevo'}-{datetime.now().isoformat()}".encode()).hexdigest()[:12]

    if existing:
        # reunion_id/agenda_fecha NO se tocan en un update -- solo se fijan
        # al crear (ver create_whiteboard mas abajo); una pizarra ya
        # existente conserva los que tuviera.
        db.update_whiteboard(whiteboard_id, titulo, contenido, thumbnail_filename, version_hash)
        wb_id = whiteboard_id
    else:
        wb_id = db.create_whiteboard(titulo, contenido, thumbnail_filename, version_hash,
                                      reunion_id.strip(), agenda_fecha.strip())

    return JSONResponse({"ok": True, "whiteboard_id": wb_id, "version_hash": version_hash})


@router.post("/whiteboard/{whiteboard_id}/eliminar/")
def whiteboard_delete(whiteboard_id: str, usuario: str = Depends(auth.requiere_login)):
    wb = db.get_whiteboard(whiteboard_id)
    if wb:
        if wb["thumbnail"]:
            path = _whiteboard_dir() / wb["thumbnail"]
            if path.exists():
                path.unlink()
        db.delete_whiteboard(whiteboard_id)
    return RedirectResponse(url="/whiteboard/", status_code=303)
