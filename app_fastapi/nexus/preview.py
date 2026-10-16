# -*- coding: utf-8 -*-
"""Vista previa (miniatura JPEG) de un archivo del catalogo -- imagen o
primera pagina de un PDF. Copia de APP_NEXUS_BUSCADOR/app/preview.py, con
un unico cambio: el nombre del fichero temporal de _render_image() usaba un
nombre fijo ('tmp.jpg') que podia pisarse entre dos peticiones concurrentes
en el proceso original (una app de un solo usuario, sin mucho trafico
simultaneo); aqui vive dentro de app_fastapi, con mas trafico real, asi que
usa un nombre unico por llamada (uuid4) para evitar esa condicion de
carrera."""
import uuid
from pathlib import Path

from .. import db

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / ".cache" / "nexus_previews"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp"}
THUMB_SIZE = (220, 220)


def _get_archivo(archivo_id: int):
    conn = db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT ruta_completa, extension FROM nexus_archivos WHERE id = %s",
                (archivo_id,),
            )
            fila = cur.fetchone()
            return {"ruta_completa": fila[0], "extension": fila[1]} if fila else None
    finally:
        conn.close()


def _render_image(path: str) -> bytes:
    from PIL import Image  # import diferido: solo se carga al usarse, no en el arranque de la app
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail(THUMB_SIZE)
        buf_path = CACHE_DIR / f"tmp-{uuid.uuid4().hex}.jpg"
        im.save(buf_path, "JPEG", quality=78)
        data = buf_path.read_bytes()
        buf_path.unlink(missing_ok=True)
        return data


def _render_pdf(path: str) -> bytes:
    import pymupdf as fitz  # "fitz" es el nombre legacy de este mismo paquete; diferido como PIL arriba
    # Abrir como stream de bytes: fitz.open(path) falla en Windows con rutas
    # que llevan tildes/enes (ver bug ya documentado en extract_docs.py).
    with open(path, "rb") as f:
        data = f.read()
    doc = fitz.open(stream=data, filetype="pdf")
    page = doc[0]
    zoom = min(THUMB_SIZE[0] / page.rect.width, THUMB_SIZE[1] / page.rect.height)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    img_bytes = pix.tobytes("jpeg")
    doc.close()
    return img_bytes


def get_preview(archivo_id: int) -> bytes | None:
    cache_path = CACHE_DIR / f"{archivo_id}.jpg"
    if cache_path.exists():
        return cache_path.read_bytes()

    row = _get_archivo(archivo_id)
    if not row:
        return None
    ext = (row["extension"] or "").lower()
    path = row["ruta_completa"]

    try:
        if ext in IMAGE_EXTS:
            data = _render_image(path)
        elif ext == ".pdf":
            data = _render_pdf(path)
        else:
            return None
    except Exception:
        return None

    cache_path.write_bytes(data)
    return data
