# -*- coding: utf-8 -*-
"""Busqueda de Nexus. Copia de APP_NEXUS_BUSCADOR/app/search.py adaptada a
app_tareas (desde 15/10/2026 ya no hay una BD confluence_local aparte): una
"ficha" del catalogo es una pagina de la Wiki con fila en
wiki_pagina_metadata (alias/codigo/tecnologias/estado/rol); los archivos y
carpetas indexados viven en nexus_archivos/nexus_carpetas, y "este archivo
es de esta ficha" en nexus_referencias. Lo relacionado con una ficha sale
del grafo nexus (db.nexus_relacionados). Va por db.connect(), asi que sigue
el interruptor real/test como el resto de la app. Ver
NEXUS_contexto_arquitectura.md para el porque de TOPICS, LIKE + FULLTEXT..."""
import json
import re
import uuid
from html import unescape

import pymysql.cursors

from . import cripto
from .. import db

BOOLEAN_OPERATORS = re.compile(r'[+\-*"()~<>@\\\'`]')

# Filtros por tema CURADOS a mano: cuando la clave coincide, la sugerencia no
# hace una busqueda de texto libre (que traeria ruido de cualquier documento
# que mencione la palabra de pasada) sino que enseña exactamente estos
# proyectos, seleccionados uno a uno porque de verdad tratan de ese tema.
TOPICS: dict[str, list[str]] = {
    # cada instalacion rellena los suyos, p. ej.:
    # "backup": ["Politica de copias de seguridad", "Servidor de ficheros"],
}

# Diccionario de siglas/abreviaturas cortas. Se ofrecen como sugerencia
# clicable ("¿quieres decir...?") -- NO se mezclan solas en los resultados,
# el usuario decide si pulsa el filtro o no. Solo se usa como fallback de
# busqueda de texto libre cuando la clave NO tiene un filtro curado en TOPICS.
SYNONYMS: dict[str, str] = {}

LIKE_ESCAPE = str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"})


class _Cursor(pymysql.cursors.DictCursorMixin, db._CursorConLog):
    """Filas como dict (lo que espera nexus.html) sin perder el log de queries."""


def get_connection():
    return db.connect()


def _cursor(conn):
    return conn.cursor(_Cursor)


def like_pattern(term: str) -> str:
    """Escapa los caracteres especiales de LIKE (% _ \\) y envuelve el termino
    para busqueda de subcadena real: "ia" encuentra "media", "liado", etc."""
    return f"%{term.translate(LIKE_ESCAPE)}%"


def build_boolean_prefix(term: str) -> str:
    """Consulta FULLTEXT ... IN BOOLEAN MODE con comodin de prefijo por palabra,
    usada solo para rankear por relevancia el contenido largo (contenido_plano),
    donde un LIKE de subcadena seria demasiado lento/impreciso para ordenar."""
    words = term.split()
    clean_terms = []
    for w in words:
        wc = BOOLEAN_OPERATORS.sub("", w)
        if len(wc) >= 3:
            clean_terms.append(f"+{wc}*")
    return " ".join(clean_terms)


def _palabras(term: str) -> list[str]:
    return [w for w in (BOOLEAN_OPERATORS.sub("", x) for x in term.split()) if len(w) >= 3]


# ── fichas: paginas de Wiki con wiki_pagina_metadata ────────────────────────

_FICHA_SQL = (
    "SELECT w.id, w.titulo AS nombre, w.proyecto_id, w.contenido, m.alias, m.codigo, m.tecnologias, m.estado, "
    "m.rol, {relevancia} AS relevancia FROM wiki_paginas w JOIN wiki_pagina_metadata m ON m.pagina_id = w.id "
)
_TAG = re.compile(r"<[^>]+>")
# parrafos que la conversion del catalogo puso al principio de cada ficha y que
# ya salen aparte en la tarjeta (estado/rol, alias, tecnologias)
_YA_EN_LA_TARJETA = ("Estado:", "También:", "Tecnologías:")


def _texto(html: str) -> str:
    return unescape(_TAG.sub("", (html or "").replace("<br>", "\n"))).strip()


def _textos_ficha(contenido: str) -> tuple[str, str]:
    """(resumen, info_desarrollador) a partir de los bloques EditorJS: lo que
    hay antes de la cabecera "Info para desarrolladores" y lo de despues."""
    try:
        bloques = json.loads(contenido or "{}").get("blocks", [])
    except ValueError:
        return "", ""
    resumen, info = [], []
    destino = resumen
    for b in bloques:
        d = b.get("data", {})
        if b.get("type") == "header":
            if "desarrollador" in d.get("text", "").lower():
                destino = info
            continue
        if b.get("type") == "list":
            texto = "\n".join("- " + _texto(i if isinstance(i, str) else i.get("content", ""))
                              for i in d.get("items", []))
        else:
            texto = _texto(d.get("text", "") or d.get("code", ""))
        if texto and not texto.startswith(_YA_EN_LA_TARJETA):
            destino.append(texto)
    return "\n\n".join(resumen), "\n\n".join(info)


_NOMBRES = {
    "sistema": ("SELECT nombre FROM sistemas WHERE id=%s", ""),
    "proyecto": ("SELECT nombre FROM proyectos WHERE id=%s", "/proyecto/{id}/tablero/"),
    "empresa": ("SELECT nombre FROM empresas WHERE id=%s", ""),
    "wiki_pagina": ("SELECT titulo AS nombre, proyecto_id FROM wiki_paginas WHERE id=%s",
                    "/proyecto/{proyecto_id}/wiki/{id}/"),
    "nota": ("SELECT titulo AS nombre FROM notas WHERE id=%s", "/notas/"),
    "whiteboard": ("SELECT titulo AS nombre FROM whiteboards WHERE id=%s", "/whiteboard/{id}/editar/"),
}


def _relacionados(cur, pagina_id: str) -> list[dict]:
    """Lo que el grafo nexus dice que va con esta ficha: sus relaciones
    directas, mas los sistemas/proyectos/empresas de su grupo (no todas las
    paginas del grupo, que en sistemas grandes son decenas)."""
    salida = []
    for r in db.nexus_relacionados("wiki_pagina", pagina_id):
        if r["tipo"] not in _NOMBRES or not (r["directo"] or r["tipo"] in ("sistema", "proyecto", "empresa")):
            continue
        sql, url = _NOMBRES[r["tipo"]]
        cur.execute(sql, (r["entidad_id"],))
        fila = cur.fetchone()
        if fila:
            salida.append({"tipo": r["tipo"], "nombre": fila["nombre"], "directo": r["directo"],
                           "url": url.format(id=r["entidad_id"], proyecto_id=fila.get("proyecto_id", ""))})
    orden = {"sistema": 0, "proyecto": 1, "empresa": 2}
    return sorted(salida, key=lambda x: (orden.get(x["tipo"], 3), x["nombre"].lower()))


def _ids_credenciales(cur, pagina_id: str) -> list[str]:
    """Credenciales relacionadas DIRECTAMENTE con la ficha (arista explicita
    credencial <-> pagina), no todas las de su grupo."""
    cur.execute(
        "SELECT c.entidad_id FROM nexus_nodos p "
        "JOIN nexus_relaciones r ON r.nodo_a = p.id OR r.nodo_b = p.id "
        "JOIN nexus_nodos c ON c.id = IF(r.nodo_a = p.id, r.nodo_b, r.nodo_a) AND c.tipo = 'credencial' "
        "WHERE p.tipo = 'wiki_pagina' AND p.entidad_id = %s",
        (pagina_id,),
    )
    return [r["entidad_id"] for r in cur.fetchall()]


def _completar_fichas(cur, fichas: list[dict]) -> list[dict]:
    for f in fichas:
        f["resumen"], f["info_desarrollador"] = _textos_ficha(f.pop("contenido", ""))
        f["wiki_url"] = f"/proyecto/{f.pop('proyecto_id')}/wiki/{f['id']}/"
        f["n_credenciales"] = len(_ids_credenciales(cur, f["id"]))
        f["ubicaciones"] = _get_ubicaciones(cur, f["id"])
        f["relacionados"] = _relacionados(cur, f["id"])
    return fichas


def get_stats() -> dict:
    conn = get_connection()
    try:
        with _cursor(conn) as cur:
            cur.execute(
                "SELECT "
                "(SELECT COUNT(*) FROM nexus_archivos) AS archivos, "
                "(SELECT COUNT(*) FROM nexus_carpetas) AS carpetas, "
                "(SELECT COUNT(*) FROM wiki_paginas w WHERE NOT EXISTS "
                " (SELECT 1 FROM wiki_pagina_metadata m WHERE m.pagina_id = w.id)) AS paginas, "
                "(SELECT COUNT(*) FROM wiki_pagina_metadata) AS proyectos"
            )
            return cur.fetchone()
    finally:
        conn.close()


# Contenido "materia prima" cargado en masa sobre carpetas de proyectos:
# codigo/config/logs de proyectos, sin curar todavia en ninguna
# ficha. Se marca con rol='tecnico' al cargarlo y NO tiene ninguna fila en
# nexus_referencias -- esa combinacion es justo el criterio para distinguirlo de
# un archivo tecnico ya curado (que SI esta enlazado a una ficha). La busqueda
# principal lo EXCLUYE (para no llenar los resultados normales de ruido de codigo)
# y la busqueda dev lo usa como universo exclusivo.
_RAW_TECH_SQL = (
    "COALESCE(a.rol, '') = 'tecnico' AND NOT EXISTS "
    "(SELECT 1 FROM nexus_referencias pr WHERE pr.archivo_id = a.id)"
)
_FICHA_DE_ARCHIVO = (
    "(SELECT w.titulo FROM nexus_referencias pr JOIN wiki_paginas w ON w.id = pr.wiki_pagina_id "
    "WHERE pr.archivo_id = a.id LIMIT 1) AS proyecto"
)


def _log_busqueda(termino: str, modo: str, n_resultados: int) -> None:
    """Registra la busqueda en `nexus_busquedas_log` (sink durable, no solo
    stdout de uvicorn). Nunca debe romper una busqueda real: cualquier fallo
    aqui se ignora en silencio."""
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO nexus_busquedas_log (termino, modo, resultados) VALUES (%s, %s, %s)",
                    (termino[:500], modo, n_resultados),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def get_stats_dev() -> dict:
    conn = get_connection()
    try:
        with _cursor(conn) as cur:
            cur.execute(f"SELECT COUNT(*) AS total FROM nexus_archivos a WHERE {_RAW_TECH_SQL}")
            return cur.fetchone()
    finally:
        conn.close()


def _get_ubicaciones(cur, pagina_id: str) -> list[dict]:
    cur.execute(
        """
        SELECT 'carpeta' AS tipo, c.ruta_relativa AS ruta, NULL AS tipo_documento
        FROM nexus_referencias pr JOIN nexus_carpetas c ON c.id = pr.carpeta_id
        WHERE pr.wiki_pagina_id = %s
        UNION ALL
        SELECT 'archivo', a.ruta_relativa, a.tipo_documento
        FROM nexus_referencias pr JOIN nexus_archivos a ON a.id = pr.archivo_id
        WHERE pr.wiki_pagina_id = %s
        """,
        (pagina_id, pagina_id),
    )
    return list(cur.fetchall())


def _merge(base: list[dict], extra: list[dict], key: str) -> list[dict]:
    """Combina dos listas de resultados por clave unica, quedandose con la
    mayor relevancia si un mismo elemento aparece en ambas, y reordena."""
    by_key: dict = {}
    for item in list(base) + list(extra):
        k = item[key]
        if k not in by_key or item["relevancia"] > by_key[k]["relevancia"]:
            by_key[k] = item
    return sorted(by_key.values(), key=lambda x: x["relevancia"], reverse=True)


def _buscar_proyectos(cur, term: str) -> list[dict]:
    # 1. Subcadena real sobre nombre/alias/codigo/tecnologias (encuentra "media" al buscar "ia",
    #    o encuentra una ficha por su stack aunque la palabra no aparezca en el resumen)
    patron = like_pattern(term)
    cur.execute(
        _FICHA_SQL.format(relevancia=100)
        + "WHERE w.titulo LIKE %s ESCAPE '\\\\' OR m.alias LIKE %s ESCAPE '\\\\' "
          "OR m.codigo LIKE %s ESCAPE '\\\\' OR m.tecnologias LIKE %s ESCAPE '\\\\' LIMIT 8",
        (patron, patron, patron, patron),
    )
    resultados = list(cur.fetchall())
    # 2. Todas las palabras dentro del texto de la ficha (antes FULLTEXT sobre el
    #    resumen; con ~60 fichas un LIKE por palabra es igual de rapido)
    palabras = _palabras(term)
    if palabras:
        cur.execute(
            _FICHA_SQL.format(relevancia=50)
            + "WHERE " + " AND ".join(["w.contenido LIKE %s ESCAPE '\\\\'"] * len(palabras)) + " LIMIT 8",
            [like_pattern(p) for p in palabras],
        )
        resultados = _merge(resultados, cur.fetchall(), "id")
    return resultados[:8]


def _buscar_archivos(cur, term: str, bq: str) -> list[dict]:
    # Excluye la masa de codigo/tecnico sin curar (ver _RAW_TECH_SQL) -- esa
    # busqueda vive aparte en "busqueda dev" para no llenar de ruido tecnico
    # los resultados principales.
    cur.execute(
        f"""
        SELECT a.id AS id, a.nombre AS nombre, a.ruta_relativa AS ruta, a.ruta_completa AS ruta_completa,
               a.tipo_documento AS tipo_documento, a.extension AS extension,
               LEFT(COALESCE(a.descripcion, a.contenido_plano, ''), 320) AS extracto,
               100 AS relevancia,
               DATE_FORMAT(a.fecha_creacion, '%%Y-%%m-%%d') AS fecha_creacion,
               DATE_FORMAT(a.fecha_modificacion, '%%Y-%%m-%%d') AS fecha_modificacion,
               {_FICHA_DE_ARCHIVO}
        FROM nexus_archivos a
        WHERE a.nombre LIKE %s ESCAPE '\\\\' AND NOT ({_RAW_TECH_SQL})
        LIMIT 30
        """,
        (like_pattern(term),),
    )
    resultados = list(cur.fetchall())
    if bq:
        cur.execute(
            f"""
            SELECT a.id AS id, a.nombre AS nombre, a.ruta_relativa AS ruta, a.ruta_completa AS ruta_completa,
                   a.tipo_documento AS tipo_documento, a.extension AS extension,
                   LEFT(COALESCE(a.descripcion, a.contenido_plano, ''), 320) AS extracto,
                   MATCH(a.nombre, a.descripcion, a.contenido_plano) AGAINST(%s IN BOOLEAN MODE) AS relevancia,
                   DATE_FORMAT(a.fecha_creacion, '%%Y-%%m-%%d') AS fecha_creacion,
                   DATE_FORMAT(a.fecha_modificacion, '%%Y-%%m-%%d') AS fecha_modificacion,
                   {_FICHA_DE_ARCHIVO}
            FROM nexus_archivos a
            WHERE MATCH(a.nombre, a.descripcion, a.contenido_plano) AGAINST(%s IN BOOLEAN MODE)
              AND NOT ({_RAW_TECH_SQL})
            ORDER BY relevancia DESC LIMIT 30
            """,
            (bq, bq),
        )
        resultados = _merge(resultados, cur.fetchall(), "ruta")
    return resultados[:30]


def _buscar_archivos_dev(cur, term: str, bq: str) -> list[dict]:
    """Busca SOLO dentro de la masa de codigo/tecnico sin curar (ver _RAW_TECH_SQL)
    -- el universo exclusivo de la 'busqueda dev', separado a proposito de la
    busqueda principal para que un desarrollador pueda rastrear codigo/config/logs
    reales sin que la busqueda normal se llene de ese ruido."""
    cur.execute(
        f"""
        SELECT a.id AS id, a.nombre AS nombre, a.ruta_relativa AS ruta, a.ruta_completa AS ruta_completa,
               a.tipo_documento AS tipo_documento, a.extension AS extension,
               LEFT(COALESCE(a.contenido_plano, ''), 320) AS extracto,
               100 AS relevancia,
               DATE_FORMAT(a.fecha_modificacion, '%%Y-%%m-%%d') AS fecha_modificacion
        FROM nexus_archivos a
        WHERE ({_RAW_TECH_SQL}) AND a.nombre LIKE %s ESCAPE '\\\\'
        LIMIT 60
        """,
        (like_pattern(term),),
    )
    resultados = list(cur.fetchall())
    if bq:
        cur.execute(
            f"""
            SELECT a.id AS id, a.nombre AS nombre, a.ruta_relativa AS ruta, a.ruta_completa AS ruta_completa,
                   a.tipo_documento AS tipo_documento, a.extension AS extension,
                   LEFT(COALESCE(a.contenido_plano, ''), 320) AS extracto,
                   MATCH(a.nombre, a.descripcion, a.contenido_plano) AGAINST(%s IN BOOLEAN MODE) AS relevancia,
                   DATE_FORMAT(a.fecha_modificacion, '%%Y-%%m-%%d') AS fecha_modificacion
            FROM nexus_archivos a
            WHERE ({_RAW_TECH_SQL}) AND MATCH(a.nombre, a.descripcion, a.contenido_plano) AGAINST(%s IN BOOLEAN MODE)
            ORDER BY relevancia DESC LIMIT 60
            """,
            (bq, bq),
        )
        resultados = _merge(resultados, cur.fetchall(), "ruta")
    return resultados[:60]


def search_dev(term: str) -> dict:
    """Busqueda dev: SOLO dentro del contenido tecnico/codigo cargado en masa
    (ver _RAW_TECH_SQL), separada de la busqueda principal a proposito."""
    term = term.strip()
    if not term:
        return {"archivos": []}

    bq = build_boolean_prefix(term)
    conn = get_connection()
    try:
        with _cursor(conn) as cur:
            archivos = _buscar_archivos_dev(cur, term, bq)
        _log_busqueda(term, "dev", len(archivos))
        return {"archivos": archivos}
    finally:
        conn.close()


def filtrar_por_tema(clave: str) -> dict:
    """Devuelve solo las fichas curadas a mano para este tema (ej. "ia"),
    con sus ubicaciones -- no es una busqueda de texto, es una lista fija
    seleccionada porque de verdad tratan de ese tema."""
    nombres = TOPICS.get(clave.strip().lower(), [])
    if not nombres:
        return {"proyectos": [], "archivos": [], "sugerencia": None, "sugerencia_termino": None}

    conn = get_connection()
    try:
        with _cursor(conn) as cur:
            placeholders = ", ".join(["%s"] * len(nombres))
            cur.execute(_FICHA_SQL.format(relevancia=100) + f"WHERE w.titulo IN ({placeholders})", tuple(nombres))
            proyectos = _completar_fichas(cur, list(cur.fetchall()))
        return {"proyectos": proyectos, "archivos": [], "sugerencia": None, "sugerencia_termino": None}
    finally:
        conn.close()


def search_catalogo(term: str) -> dict:
    """Fichas + archivos indexados. Las paginas de Wiki (incluidas las que
    antes eran la wiki propia de confluence_local) las busca el router con
    db.search_wiki_pages, una sola vez."""
    term = term.strip()
    term_clean = term.lower()
    if not term:
        return {"proyectos": [], "archivos": [], "sugerencia": None, "sugerencia_termino": None,
                "sugerencia_tema": None}

    bq = build_boolean_prefix(term)
    tema_curado = term_clean if term_clean in TOPICS else None
    expansion = None if tema_curado else SYNONYMS.get(term_clean)

    conn = get_connection()
    try:
        with _cursor(conn) as cur:
            proyectos = _completar_fichas(cur, _buscar_proyectos(cur, term))
            archivos = _buscar_archivos(cur, term, bq)

        if tema_curado:
            sugerencia = f'¿Ver solo los proyectos de "{tema_curado.upper()}"?'
        elif expansion:
            sugerencia = f'¿Quieres decir "{expansion}"?'
        else:
            sugerencia = None

        _log_busqueda(term, "normal", len(proyectos) + len(archivos))

        return {
            "proyectos": proyectos,
            "archivos": archivos,
            "sugerencia": sugerencia,
            "sugerencia_termino": expansion,
            "sugerencia_tema": tema_curado,
        }
    finally:
        conn.close()


def listar_tecnologias() -> dict:
    """Agrega el campo `tecnologias` (texto libre separado por comas) de TODAS
    las fichas en una vista de 'que necesidades tecnologicas hay en el
    catalogo' -- a diferencia de TOPICS (listas fijas curadas a mano por tema),
    esto es un agregado real y vivo: crece solo segun se rellena el campo
    `tecnologias` de cada ficha, sin mantenimiento manual."""
    conn = get_connection()
    try:
        with _cursor(conn) as cur:
            cur.execute("SELECT w.id, w.titulo AS nombre, m.tecnologias FROM wiki_pagina_metadata m "
                        "JOIN wiki_paginas w ON w.id = m.pagina_id WHERE m.tecnologias != ''")
            rows = cur.fetchall()
    finally:
        conn.close()

    agregados: dict[str, list[dict]] = {}
    for r in rows:
        for tech in r["tecnologias"].split(","):
            tech = tech.strip()
            if not tech:
                continue
            agregados.setdefault(tech, []).append({"id": r["id"], "nombre": r["nombre"]})

    lista = [
        {"tecnologia": k, "n_proyectos": len(v), "proyectos": sorted(v, key=lambda p: p["nombre"])}
        for k, v in agregados.items()
    ]
    lista.sort(key=lambda x: (-x["n_proyectos"], x["tecnologia"].lower()))
    return {"tecnologias": lista}


# ── credenciales: cifradas, colgadas de una ficha via el grafo nexus ────────

def listar_credenciales(pagina_id: str) -> list[dict]:
    """Lista las credenciales de una ficha SIN el valor -- solo la etiqueta,
    usuario y notas, para que se pueda ver 'que hay' sin desbloquear nada."""
    conn = get_connection()
    try:
        with _cursor(conn) as cur:
            ids = _ids_credenciales(cur, pagina_id)
            if not ids:
                return []
            cur.execute(
                f"SELECT id, etiqueta, usuario, notas FROM credenciales WHERE id IN ({', '.join(['%s'] * len(ids))}) "
                "ORDER BY etiqueta",
                ids,
            )
            return list(cur.fetchall())
    finally:
        conn.close()


def crear_credencial(pagina_id: str, etiqueta: str, usuario: str | None, notas: str | None, password: str,
                     secreto: str) -> str:
    """Cifra `secreto` con AES-256-GCM (clave derivada de `password` via PBKDF2,
    ver cripto.py) y guarda solo el blob cifrado -- el servidor nunca persiste
    el secreto ni la contrasena en claro. La credencial gana su nodo nexus y
    una arista directa con la ficha."""
    valor_cifrado = cripto.cifrar(password, secreto)
    credencial_id = str(uuid.uuid4())[:8]
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO credenciales (id, etiqueta, usuario, valor, notas) VALUES (%s, %s, %s, %s, %s)",
                (credencial_id, etiqueta, usuario, valor_cifrado, notas),
            )
            db._nexus_relacionar(cur, ("credencial", credencial_id), ("wiki_pagina", pagina_id))
        conn.commit()
        return credencial_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ver_credencial(credencial_id: str, password: str) -> dict:
    """Intenta descifrar el valor guardado con la contrasena recibida. AES-GCM
    es quien realmente decide si la contrasena es correcta (falla la
    verificacion de integridad si no lo es) -- no hay bypass posible aunque se
    manipule la fila a mano. Nunca revela si el id existe o no via el mensaje
    de error (mismo error generico para 'no existe' y 'contrasena incorrecta')."""
    conn = get_connection()
    try:
        with _cursor(conn) as cur:
            cur.execute(
                "SELECT etiqueta, usuario, valor, notas FROM credenciales WHERE id = %s",
                (credencial_id,),
            )
            row = cur.fetchone()
        if not row:
            return {"ok": False}
        secreto = cripto.descifrar(password, row["valor"])
        if secreto is None:
            return {"ok": False}
        return {
            "ok": True,
            "etiqueta": row["etiqueta"],
            "usuario": row["usuario"],
            "valor": secreto,
            "notas": row["notas"],
        }
    finally:
        conn.close()


def eliminar_credencial(credencial_id: str, password: str) -> bool:
    """Borra la fila SOLO si la contrasena descifra correctamente su valor --
    mismo guardian real (AES-GCM) que `ver_credencial`, no un hash aparte."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT valor FROM credenciales WHERE id = %s", (credencial_id,))
            row = cur.fetchone()
            if not row or cripto.descifrar(password, row[0]) is None:
                return False
            db._nexus_eliminar_nodo(cur, "credencial", credencial_id)
            cur.execute("DELETE FROM credenciales WHERE id = %s", (credencial_id,))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
