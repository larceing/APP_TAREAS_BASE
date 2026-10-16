# -*- coding: utf-8 -*-
"""Wiki por proyecto -- copiado de core/views.py::wiki_home/wiki_page/
wiki_page_edit/wiki_page_delete/wiki_page_import_docx + core/wiki_store.py +
core/templates/wiki.html/wiki_edit.html. Cada pagina guarda un documento
EditorJS (mismo editor, mismos bloques activados, cargado desde archivos
estaticos locales igual que la app real -- ver README) y se convierte a
HTML en el servidor al mostrarla (wiki_store.render_content), nunca en el
cliente.

"Importar desde Word" reutiliza docx_import.py (copiado de core/docx_import.py,
confirmado sin nada de Django dentro, mismo criterio que mantis_client.py) --
solo necesita un objeto tipo-archivo con .name/.size ademas de poder leerse,
que UploadFile de FastAPI no ofrece tal cual, de ahi el envoltorio _DocxUpload."""
import json
import re
import uuid
from io import BytesIO

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.requests import Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from .. import auth, db, logging_setup, wiki_store
from ..flash import flash
from ..templating import templates

router = APIRouter(prefix="/proyecto/{project_id}/wiki", tags=["wiki"])

# Imagenes insertadas en el contenido de una pagina (bloque "image" de
# EditorJS, ver wiki_store.render_content -- el renderizador YA sabia
# pintar este bloque, solo faltaba la herramienta en el editor + estos dos
# endpoints). Subcarpeta propia de db.media_dir(), mismo patron que
# whiteboard.py::_whiteboards_dir().
WIKI_IMG_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}
_WIKI_IMG_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|jpeg|gif|webp)$")


def _wiki_images_dir():
    d = db.media_dir() / "wiki_images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _redirect(project_id: str, page_id: str = "") -> RedirectResponse:
    url = f"/proyecto/{project_id}/wiki/{page_id}/" if page_id else f"/proyecto/{project_id}/wiki/"
    return RedirectResponse(url=url, status_code=303)


@router.post("/subir-imagen/")
async def wiki_image_upload(
    project_id: str, image: UploadFile = File(...), usuario: str = Depends(auth.requiere_login),
):
    """Subida por @editorjs/image (config.endpoints.byFile, campo 'image') --
    respuesta con la forma exacta que esa herramienta espera:
    {success: 1, file: {url: ...}} o {success: 0} si se rechaza."""
    if not db.puede_actuar_en_proyecto(project_id, db.get_user_id(usuario), "editores_gestionan_documentos_wiki"):
        return JSONResponse({"success": 0})
    nombre = image.filename or ""
    ext = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
    if ext not in WIKI_IMG_EXTS:
        return JSONResponse({"success": 0})
    data = await image.read()
    filename = f"{uuid.uuid4().hex}.{ext}"
    (_wiki_images_dir() / filename).write_bytes(data)
    return JSONResponse({"success": 1, "file": {"url": f"/proyecto/{project_id}/wiki/imagen/{filename}"}})


@router.get("/imagen/{filename}")
def wiki_image_serve(project_id: str, filename: str, usuario: str = Depends(auth.requiere_login)):
    """Sirve una imagen subida desde el editor -- sin filename= en
    FileResponse a proposito, para que NO vaya con Content-Disposition:
    attachment (rompería el <img src=...> del contenido renderizado, que
    espera poder mostrarla inline)."""
    if not _WIKI_IMG_NAME_RE.match(filename):
        return RedirectResponse(url="/", status_code=303)
    path = _wiki_images_dir() / filename
    if not path.exists():
        return RedirectResponse(url="/", status_code=303)
    return FileResponse(path)


@router.get("/")
def wiki_home(project_id: str, request: Request, usuario: str = Depends(auth.requiere_login)):
    proyecto = db.get_proyecto(project_id)
    if not proyecto:
        return RedirectResponse(url="/", status_code=303)
    pages = wiki_store.list_pages(project_id)
    return templates.TemplateResponse(request, "wiki.html", {
        "usuario": usuario, "activo": "wiki", "proyecto": proyecto, "proyecto_actual": project_id,
        "wiki_tree": wiki_store.build_tree(pages), "wiki_pages": pages,
        "current_page": None, "page_html": "", "breadcrumb": [],
    })


@router.get("/nueva/")
def wiki_page_new_form(project_id: str, request: Request, parent: str = "", usuario: str = Depends(auth.requiere_login)):
    return _form_editor(project_id, request, usuario, page_id=None, parent_default=parent)


@router.get("/{page_id}/")
def wiki_page(project_id: str, page_id: str, request: Request, usuario: str = Depends(auth.requiere_login)):
    proyecto = db.get_proyecto(project_id)
    if not proyecto:
        return RedirectResponse(url="/", status_code=303)
    page = wiki_store.get_page(page_id)
    if not page:
        return _redirect(project_id)
    pages = wiki_store.list_pages(project_id)
    tree = wiki_store.build_tree(pages)

    # el nodo del arbol que corresponde a esta pagina, para poder listar sus
    # subpaginas (children) igual que hace la app real con current_page.children
    tree_by_id = {n["page_id"]: n for n in _flatten(tree)}
    current_con_hijos = tree_by_id.get(page_id, {**page, "children": []})

    breadcrumb = []
    p = page
    while p:
        breadcrumb.insert(0, p)
        pid = p.get("parent_id", "")
        p = wiki_store.get_page(pid) if pid else None

    return templates.TemplateResponse(request, "wiki.html", {
        "usuario": usuario, "activo": "wiki", "proyecto": proyecto, "proyecto_actual": project_id,
        "wiki_tree": tree, "wiki_pages": pages,
        "current_page": current_con_hijos,
        "page_html": wiki_store.render_content(page.get("content", {}), project_id),
        "breadcrumb": breadcrumb,
    })


def _flatten(nodes: list) -> list:
    out = []
    for n in nodes:
        out.append(n)
        out.extend(_flatten(n.get("children", [])))
    return out


@router.get("/{page_id}/editar/")
def wiki_page_edit_form(project_id: str, page_id: str, request: Request, usuario: str = Depends(auth.requiere_login)):
    return _form_editor(project_id, request, usuario, page_id=page_id, parent_default="")


def _form_editor(project_id: str, request: Request, usuario: str, page_id, parent_default: str):
    proyecto = db.get_proyecto(project_id)
    if not proyecto:
        return RedirectResponse(url="/", status_code=303)
    page = wiki_store.get_page(page_id) if page_id else None
    pages = wiki_store.list_pages(project_id)
    return templates.TemplateResponse(request, "wiki_edit.html", {
        "usuario": usuario, "activo": "wiki", "proyecto": proyecto, "proyecto_actual": project_id,
        "wiki_pages": pages, "current_page": page, "page_id": page_id or "",
        "current_page_content": page["content"] if page else {"time": 0, "blocks": [], "version": "2.29.0"},
        "common_emojis": wiki_store.COMMON_EMOJIS,
        "default_parent_id": parent_default or (page.get("parent_id", "") if page else ""),
    })


@router.post("/nueva/")
def wiki_page_new_submit(
    project_id: str, title: str = Form("Sin título"), icon: str = Form("📄"),
    parent_id: str = Form(""), content: str = Form("{}"), usuario: str = Depends(auth.requiere_login),
):
    try:
        content_dict = json.loads(content)
    except Exception:
        content_dict = {"blocks": []}
    nueva = wiki_store.create_page(project_id, title.strip() or "Sin título", parent_id.strip(), icon.strip() or "📄", content_dict)
    return _redirect(project_id, nueva["page_id"])


@router.post("/{page_id}/editar/")
def wiki_page_edit_submit(
    request: Request, project_id: str, page_id: str, title: str = Form("Sin título"), icon: str = Form("📄"),
    parent_id: str = Form(""), content: str = Form("{}"), usuario: str = Depends(auth.requiere_login),
):
    if not db.puede_actuar_en_proyecto(project_id, db.get_user_id(usuario), "editores_gestionan_documentos_wiki"):
        flash(request, "error", "No tienes permiso para editar la Wiki de este proyecto.")
        return _redirect(project_id, page_id)
    try:
        content_dict = json.loads(content)
    except Exception:
        content_dict = {"blocks": []}
    wiki_store.update_page(page_id, title=title.strip() or "Sin título", icon=icon.strip() or "📄",
                            content=content_dict, parent_id=parent_id.strip())
    return _redirect(project_id, page_id)


@router.post("/{page_id}/eliminar/")
def wiki_page_delete(request: Request, project_id: str, page_id: str, usuario: str = Depends(auth.requiere_login)):
    if not db.puede_actuar_en_proyecto(project_id, db.get_user_id(usuario), "editores_gestionan_documentos_wiki"):
        flash(request, "error", "No tienes permiso para eliminar páginas de la Wiki de este proyecto.")
        return _redirect(project_id)
    wiki_store.delete_page(page_id)
    return _redirect(project_id)


class _DocxUpload(BytesIO):
    """BytesIO con .name/.size añadidos -- lo que espera core/docx_import.py::
    import_docx_to_editorjs (pensado para un UploadedFile de Django, que ya
    trae esos dos atributos) y lo que necesita python-docx por dentro
    (Document() lee el .docx como un zip, hace falta .seek()/.tell() ademas
    de .read(), que BytesIO ya trae de serie -- por eso hereda de BytesIO en
    vez de reenviar cada metodo a mano, a diferencia de excel_import.py, que
    recibe nombre/tamaño como parametros aparte en vez de como atributos."""

    def __init__(self, data: bytes, name: str):
        super().__init__(data)
        self.name = name
        self.size = len(data)


@router.post("/importar-word/")
async def wiki_page_import_docx(
    request: Request,
    project_id: str, docx_file: UploadFile = File(...), parent_id: str = Form(""),
    usuario: str = Depends(auth.requiere_login),
):
    """Igual que core/views.py::wiki_page_import_docx, incluidos sus 3
    mensajes flash (error de lectura / avisos de la conversión / éxito)."""
    proyecto = db.get_proyecto(project_id)
    if not proyecto:
        return RedirectResponse(url="/", status_code=303)
    data = await docx_file.read()
    upload = _DocxUpload(data, docx_file.filename or "")
    try:
        from ..docx_import import import_docx_to_editorjs  # import diferido: solo se carga al usarse, no en el arranque de la app
        content, titulo, avisos = import_docx_to_editorjs(upload)
    except ValueError as e:
        flash(request, "error", f"No se pudo importar el Word: {e}")
        logging_setup.errores.error(f"{usuario} | POST .../wiki/importar-word/ -> {e}")
        return _redirect(project_id)
    pagina = wiki_store.create_page(project_id, titulo, parent_id.strip(), "📄", content)
    if avisos:
        flash(request, "warning", "; ".join(avisos))
    flash(request, "success", "Documento importado. Revisa el contenido antes de guardar.")
    return _redirect(project_id, pagina["page_id"])
