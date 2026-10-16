# -*- coding: utf-8 -*-
"""Importador del .csv que exporta la propia Mantis (boton "Exportar CSV"
dentro de Mantis) -- NO es el formato de la plantilla de Excel de la app (ver
excel_import.py). Copiado de core/views.py::import_tasks_from_mantis_csv,
puro (sin Django, sin dataclases de Task): trabaja sobre listas de tuplas
(id, nombre) y devuelve dicts listos para pasarle a db.crear_tarea. Nunca
revienta por una fila/columna rara -- la reporta como aviso y sigue, mismo
contrato que excel_import.py."""
from __future__ import annotations

import csv
import io
import json
import unicodedata
from datetime import datetime

IMPORT_CSV_MANTIS_MAX_SIZE_MB = 10
IMPORT_CSV_MANTIS_MAX_ROWS = 5000

_CSV_MANTIS_COL_ID = "id."
_CSV_MANTIS_COL_PROYECTO = "proyecto"
_CSV_MANTIS_COL_PRIORIDAD = "prioridad"
_CSV_MANTIS_COL_CATEGORIA = "categoria"
_CSV_MANTIS_COL_ENVIO = "fecha de envio"
_CSV_MANTIS_COL_ACTUALIZ = "actualizada"
_CSV_MANTIS_COL_RESUMEN = "resumen"
_CSV_MANTIS_COL_ESTADO = "estado"

# Igual que _PRIORIDAD_MAP en core/mantis_client.py -- no se reutiliza esa
# (privada, con guion bajo) para no depender de un detalle interno de otro
# modulo por una tabla de 5 lineas.
_PRIORIDAD_MAP = {
    "baja": "Baja", "normal": "Normal", "alta": "Alta", "urgente": "Alta", "inmediata": "Alta",
}


def _clean(v) -> str:
    return "" if v is None else str(v).strip()


def _norm(s) -> str:
    s = "" if s is None else str(s).strip()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return s.lower()


def _match_by_name(valor: str, opciones: list):
    """opciones: lista de (id_o_nombre, nombre). Devuelve (id_o_nombre, encontrado)."""
    if not valor:
        return "", True
    objetivo = _norm(valor)
    for id_, nombre in opciones:
        if _norm(nombre) == objetivo:
            return id_, True
    return "", False


def _parse_fecha(valor) -> str:
    if valor is None or valor == "":
        return ""
    s = str(valor).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return ""


def mantis_csv_estado_map(raw_json: str) -> dict:
    """{estado del CSV normalizado (_norm) -> nombre de columna del tablero
    destino}, tal como lo guarda Configuracion -> Mantis (ajustes_app, clave
    'mantis_csv.estado_map', ver routers/configuracion.py). El vocabulario
    de estados es propio de cada instalacion de Mantis, no algo fijo en
    codigo."""
    try:
        data = json.loads(raw_json or "{}")
        return {_norm(k): str(v) for k, v in data.items() if _norm(k)}
    except (ValueError, TypeError):
        return {}


def import_tasks_from_mantis_csv(
    fileobj, nombre_archivo: str, tamano: int, categorias: list, empresas: list,
    estado_map: dict, default_status: str, iniciativa_id: str,
    done_column_names: set, ids_ya_importadas: set, base_url: str = "",
) -> tuple:
    """Lee el .csv que exporta la propia Mantis -- trae columnas en español
    propias de Mantis (Id., Proyecto, Informador, Asignada a, Prioridad,
    Categoria, Fecha de envio, Actualizada, Resumen, Estado, Resolucion...).
    Devuelve (nuevas, avisos): 'nuevas' es una lista de dicts con las claves
    que espera db.crear_tarea. estado_map ya normalizado (_norm) de
    estado_csv -> nombre de columna; un estado sin mapear cae en
    default_status y se avisa -- nunca se inventa una columna nueva. Si la
    columna resultante esta en done_column_names, se marca cerrada usando
    'Actualizada' como fecha de cierre (no hay otro dato de cierre real en
    este export)."""
    if not nombre_archivo.lower().endswith(".csv"):
        raise ValueError("el archivo debe ser un .csv (el que exporta la propia Mantis)")
    if tamano > IMPORT_CSV_MANTIS_MAX_SIZE_MB * 1024 * 1024:
        raise ValueError(f"el archivo pesa demasiado (maximo {IMPORT_CSV_MANTIS_MAX_SIZE_MB} MB)")

    raw = fileobj.read()
    texto = None
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            texto = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if texto is None:
        raise ValueError("no se pudo leer la codificacion del archivo (se probo UTF-8 y Windows-1252)")

    reader = csv.DictReader(io.StringIO(texto))
    if not reader.fieldnames:
        raise ValueError("el archivo esta vacio")
    col_by_norm = {_norm(c): c for c in reader.fieldnames}
    faltantes = [c for c in (_CSV_MANTIS_COL_ID, _CSV_MANTIS_COL_RESUMEN, _CSV_MANTIS_COL_ESTADO) if c not in col_by_norm]
    if faltantes:
        raise ValueError(f"no se encontraron las columnas {', '.join(faltantes)} -- ¿es el CSV que exporta Mantis?")

    filas = list(reader)
    if len(filas) > IMPORT_CSV_MANTIS_MAX_ROWS:
        raise ValueError(f"el archivo tiene {len(filas)} filas, el maximo por importacion es {IMPORT_CSV_MANTIS_MAX_ROWS}")

    def get(row, col_name):
        real = col_by_norm.get(col_name)
        return row.get(real) if real else None

    cat_opciones = [(c, c) for c in categorias]
    emp_opciones = [(e["empresa_id"], e["nombre"]) for e in empresas if e["activo"]]
    ids_vistos = set(ids_ya_importadas)

    nuevas = []
    avisos = []
    for n, row in enumerate(filas, start=2):
        id_raw = _clean(get(row, _CSV_MANTIS_COL_ID))
        try:
            mantis_id = int(id_raw)
        except ValueError:
            avisos.append(f"fila {n}: 'Id.' invalido ({id_raw!r}), omitida")
            continue
        if mantis_id in ids_vistos:
            avisos.append(f"fila {n} (#{mantis_id}): ya se habia importado antes, omitida")
            continue

        titulo = _clean(get(row, _CSV_MANTIS_COL_RESUMEN))
        if not titulo:
            avisos.append(f"fila {n} (#{mantis_id}): sin 'Resumen', omitida")
            continue

        estado_raw = _norm(get(row, _CSV_MANTIS_COL_ESTADO))
        status = estado_map.get(estado_raw, default_status)
        if estado_raw and estado_raw not in estado_map:
            avisos.append(
                f"fila {n} (#{mantis_id}): estado '{_clean(get(row, _CSV_MANTIS_COL_ESTADO))}' sin mapear, "
                f"se usó '{default_status}' -- añádelo en Configuración → Mantis"
            )

        categoria, cat_ok = _match_by_name(_clean(get(row, _CSV_MANTIS_COL_CATEGORIA)), cat_opciones)
        if not cat_ok:
            avisos.append(f"fila {n} (#{mantis_id}): Categoria '{get(row, _CSV_MANTIS_COL_CATEGORIA)}' no encontrada, se deja vacia")

        empresa_id, emp_ok = _match_by_name(_clean(get(row, _CSV_MANTIS_COL_PROYECTO)), emp_opciones)
        if not emp_ok:
            avisos.append(f"fila {n} (#{mantis_id}): Empresa '{get(row, _CSV_MANTIS_COL_PROYECTO)}' no encontrada, se deja vacia")

        prioridad = _PRIORIDAD_MAP.get(_norm(_clean(get(row, _CSV_MANTIS_COL_PRIORIDAD))), "Normal")
        fecha_inicio = _parse_fecha(get(row, _CSV_MANTIS_COL_ENVIO))
        cerrada_en = ""
        if status in done_column_names:
            fecha_cierre = _parse_fecha(get(row, _CSV_MANTIS_COL_ACTUALIZ))
            cerrada_en = f"{fecha_cierre} 00:00:00" if fecha_cierre else ""

        pie = f"\n\n---\nMantis #{mantis_id}"
        if base_url:
            pie += f" — {base_url}/view.php?id={mantis_id}"

        nuevas.append({
            "category": categoria, "title": titulo, "status": status,
            "description": pie.strip(), "next_step": "", "priority": prioridad,
            "fecha_inicio": fecha_inicio, "fecha_fin": "",
            "empresa_id": empresa_id, "iniciativa_id": iniciativa_id,
            "mantis_id": mantis_id, "cerrada_en": cerrada_en,
        })
        ids_vistos.add(mantis_id)

    return nuevas, avisos
