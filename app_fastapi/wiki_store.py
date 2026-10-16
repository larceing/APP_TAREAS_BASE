# -*- coding: utf-8 -*-
"""Copiado de core/wiki_store.py -- mismo modelo (cada pagina guarda un
documento EditorJS como JSON en `contenido`, arbol via `parent_id`) y el
mismo saneado del HTML embebido inline (EditorJS mete negrita/cursiva/
enlace/marcador como HTML dentro del propio texto de un bloque, asi que no
se puede escapar a ciegas sin romper ese formato -- se limpia con una lista
blanca de etiquetas via `bleach`, igual que el original)."""
import json
import uuid
from html import escape
from urllib.parse import urlparse

import bleach

from . import db

_INLINE_TAGS = ["b", "i", "strong", "em", "u", "s", "mark", "code", "a", "br"]
_INLINE_ATTRS = {"a": ["href"], "mark": ["class"], "code": ["class"]}
_INLINE_PROTOCOLS = ["http", "https", "mailto"]


def _clean(text) -> str:
    return bleach.clean(text or "", tags=_INLINE_TAGS, attributes=_INLINE_ATTRS,
                         protocols=_INLINE_PROTOCOLS, strip=True)


def _safe_url(url) -> str:
    url = (url or "").strip()
    if url and urlparse(url).scheme not in ("http", "https", ""):
        return ""
    return escape(url)


COMMON_EMOJIS = [
    "📄", "📝", "📋", "📌", "📎", "📊", "📈", "💡", "⚡", "🔧", "🛠", "🎯", "🚀", "✅",
    "⚠", "🔑", "🔒", "💬", "📣", "🌟", "🏆", "🎨", "🖥", "📱", "🌐", "🔗", "📚", "📖",
    "🗒", "🗂", "📁", "🧩", "🧪", "🔬", "🎓", "👥", "🤝", "❓", "🆕", "💾", "⚙", "📐",
]

_COLUMNS = "id, proyecto_id, parent_id, titulo, icono, orden, contenido, creada_en, actualizada_en"


def _row_to_page(row) -> dict:
    return {
        "page_id": row[0], "proyecto": row[1], "parent_id": row[2] or "",
        "title": row[3], "icon": row[4], "orden": row[5],
        "content": json.loads(row[6]) if row[6] else {},
        "created_at": db._fmt_datetime(row[7]), "updated_at": db._fmt_datetime(row[8]),
    }


def list_pages(project_id: str) -> list:
    conn = db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {_COLUMNS} FROM wiki_paginas WHERE proyecto_id=%s", (project_id,))
            pages = [_row_to_page(r) for r in cur.fetchall()]
    finally:
        conn.close()
    return sorted(pages, key=lambda p: (p["orden"], p["title"].lower()))


def get_page(page_id: str):
    conn = db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {_COLUMNS} FROM wiki_paginas WHERE id=%s", (page_id,))
            row = cur.fetchone()
            return _row_to_page(row) if row else None
    finally:
        conn.close()


def create_page(proyecto: str, title: str, parent_id: str = "", icon: str = "📄", content: dict = None) -> dict:
    parent_id = parent_id or None
    content = content or {"time": 0, "blocks": [], "version": "2.29.0"}
    page_id = str(uuid.uuid4())[:8]
    conn = db.connect()
    try:
        with conn.cursor() as cur:
            # NULL-safe (<=>): un parent_id de NULL debe agrupar con otras
            # paginas raiz, no quedar fuera del MAX() como haria "=".
            cur.execute(
                "SELECT COALESCE(MAX(orden), -1) + 1 FROM wiki_paginas WHERE proyecto_id=%s AND parent_id <=> %s",
                (proyecto, parent_id),
            )
            orden = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO wiki_paginas (id, proyecto_id, parent_id, titulo, icono, orden, contenido) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (page_id, proyecto, parent_id, title, icon or "📄", orden, json.dumps(content, ensure_ascii=False)),
            )
            db._nexus_crear_nodo(cur, "wiki_pagina", page_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_page(page_id)


def update_page(page_id: str, title: str = None, icon: str = None, content: dict = None, parent_id: str = None):
    conn = db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT titulo, icono, contenido, parent_id FROM wiki_paginas WHERE id=%s", (page_id,))
            row = cur.fetchone()
            if row is None:
                return None
            new_title = title if title is not None else row[0]
            new_icon = icon if icon is not None else row[1]
            new_content = content if content is not None else (json.loads(row[2]) if row[2] else {})
            new_parent = (parent_id or None) if parent_id is not None else row[3]
            cur.execute(
                "UPDATE wiki_paginas SET titulo=%s, icono=%s, contenido=%s, parent_id=%s WHERE id=%s",
                (new_title, new_icon, json.dumps(new_content, ensure_ascii=False), new_parent, page_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_page(page_id)


def delete_page(page_id: str) -> None:
    # ON DELETE SET NULL en wiki_paginas.parent_id reasigna solas las
    # paginas hijas a raiz -- no hace falta limpiarlas a mano aqui.
    conn = db.connect()
    try:
        with conn.cursor() as cur:
            db._nexus_eliminar_nodo(cur, "wiki_pagina", page_id)
            cur.execute("DELETE FROM wiki_paginas WHERE id=%s", (page_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def build_tree(pages: list) -> list:
    by_id = {p["page_id"]: {**p, "children": []} for p in pages}
    roots: list = []
    for p in pages:
        pid = p.get("parent_id", "")
        if pid and pid in by_id:
            by_id[pid]["children"].append(by_id[p["page_id"]])
        else:
            roots.append(by_id[p["page_id"]])
    return roots


def render_content(content: dict, proyecto_id: str = "") -> str:
    if not content:
        return ""
    blocks = content.get("blocks", [])
    parts: list = []
    for block in blocks:
        t = block.get("type", "")
        d = block.get("data", {})
        if t == "tareasVivas":
            solo_pendientes = d.get("filtro", "pendientes") != "todas"
            tareas = db.load_tareas_vivo_wiki(proyecto_id, solo_pendientes) if proyecto_id else []
            titulo = "Tareas pendientes" if solo_pendientes else "Todas las tareas"
            if not tareas:
                cuerpo = "<p class='wk-tareas-vivas-empty'>Sin tareas que mostrar ahora mismo.</p>"
            else:
                items = "".join(
                    f"<li><a href='/proyecto/{escape(proyecto_id)}/tablero/?abrir_tarea={escape(ta['task_id'])}'>"
                    f"{_clean(ta['title'])}</a><span class='wk-tareas-vivas-estado'>{_clean(ta['status'])}</span></li>"
                    for ta in tareas
                )
                cuerpo = f"<ul class='wk-tareas-vivas-list'>{items}</ul>"
            parts.append(
                f"<div class='wk-tareas-vivas'><div class='wk-tareas-vivas-titulo'>📋 {titulo} ({len(tareas)})"
                f"</div>{cuerpo}</div>"
            )
            continue
        if t == "header":
            lvl = min(max(d.get("level", 2), 1), 6)
            parts.append(f"<h{lvl} class='wk-h wk-h{lvl}'>{_clean(d.get('text', ''))}</h{lvl}>")
        elif t == "paragraph":
            parts.append(f"<p class='wk-p'>{_clean(d.get('text', ''))}</p>")
        elif t == "list":
            tag = "ol" if d.get("style") == "ordered" else "ul"
            items = "".join(f"<li>{_clean(i)}</li>" for i in d.get("items", []))
            parts.append(f"<{tag} class='wk-list'>{items}</{tag}>")
        elif t == "checklist":
            items_html = ""
            for item in d.get("items", []):
                done = "wk-check-done" if item.get("checked") else ""
                box = "✓" if item.get("checked") else ""
                items_html += f"<li class='wk-check-item {done}'><span class='wk-check-box'>{box}</span>{_clean(item.get('text', ''))}</li>"
            parts.append(f"<ul class='wk-checklist'>{items_html}</ul>")
        elif t == "code":
            parts.append(f"<pre class='wk-code'><code>{escape(d.get('code', ''))}</code></pre>")
        elif t == "quote":
            caption = f"<cite>{_clean(d.get('caption', ''))}</cite>" if d.get("caption") else ""
            align = d.get("alignment", "left")
            parts.append(f"<blockquote class='wk-quote wk-quote-{align}'><p>{_clean(d.get('text', ''))}</p>{caption}</blockquote>")
        elif t == "delimiter":
            parts.append("<div class='wk-delimiter'>* * *</div>")
        elif t == "table":
            rows = d.get("content", [])
            with_hdr = d.get("withHeadings", False)
            rows_html = ""
            for i, row in enumerate(rows):
                tag = "th" if (i == 0 and with_hdr) else "td"
                cells = "".join(f"<{tag}>{_clean(cell)}</{tag}>" for cell in row)
                rows_html += f"<tr>{cells}</tr>"
            parts.append(f"<div class='wk-table-wrap'><table class='wk-table'><tbody>{rows_html}</tbody></table></div>")
        elif t == "image":
            url = _safe_url(d.get("file", {}).get("url", ""))
            caption_raw = d.get("caption", "")
            extra = " ".join(filter(None, [
                "wk-img-border" if d.get("withBorder") else "",
                "wk-img-bg" if d.get("withBackground") else "",
                "wk-img-stretch" if d.get("stretched") else "",
            ]))
            cap_html = f"<figcaption>{_clean(caption_raw)}</figcaption>" if caption_raw else ""
            parts.append(f"<figure class='wk-image {extra}'><img src='{url}' alt='{escape(bleach.clean(caption_raw or '', tags=[], strip=True))}'>{cap_html}</figure>")
        elif t == "warning":
            parts.append(f"<div class='wk-warning'><strong>{_clean(d.get('title', ''))}</strong><p>{_clean(d.get('message', ''))}</p></div>")
    return "\n".join(parts)
