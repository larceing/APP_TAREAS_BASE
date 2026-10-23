# -*- coding: utf-8 -*-
"""API externa -- unicos endpoints de la app SIN sesion de login: se
autentican con la cabecera X-API-Key, comparada en cada llamada (nunca
cacheada) contra:
  1. La clave maestra fija en .env (API_IMPORT_TOKEN) -- acceso a TODOS los
     proyectos, pensada como clave de arranque/emergencia.
  2. api_tokens (Configuracion -> API), creadas desde la propia app, cada
     una opcionalmente restringida a UN proyecto. Solo se guarda su hash; el
     valor en claro se muestra una unica vez al crearla.
Sin ninguna clave configurada, los endpoints se desactivan solos.

TODO lo que cambia algo pasa por acciones.py, igual que la web: una tarea
creada por un script con datos minimos (proyecto + titulo) avisa al
asignado y sale en el muro, igual que si se creara desde el tablero; mover
una tarea a "hecha" publica "completó" en el muro; etc. Cada respuesta trae
'efectos' con lo que ha tocado (["tarea_creada", "aviso:marta", "muro"]).

Quien firma: un token tiene dueño (quien lo creo) y la API actua como esa
persona ("ana.lopez (vía API: informe)" en el muro, con sus mismos permisos de
mover/eliminar). La clave maestra y los tokens antiguos sin dueño firman
como "API · <nombre>"; esos no pueden escribir en el muro ni enviar notas.

Indice: GET /api/  (quien soy + lista de endpoints).
"""
import hashlib
import json
import os
import secrets
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from .. import acciones, db
from ..excel_import import _clean, _match_by_name, _norm, _parse_excel_fecha

router = APIRouter(prefix="/api", tags=["api-externa"])

API_IMPORT_MAX_TAREAS = 500
API_TAREAS_LISTA_LIMIT_DEFECTO = 200
API_TAREAS_LISTA_LIMIT_MAX = 1000
PRIORITIES = acciones.PRIORIDADES
MANUAL = Path(__file__).resolve().parents[2] / "docs" / "api" / "Manual_API_App_Tareas.md"

ENDPOINTS = [
    ("GET", "/api/", "quién soy (actor del token) y esta lista"),
    ("GET", "/api/manual", "el manual completo de la API (Markdown) -- empezar por aquí"),
    ("GET", "/api/dimensiones/", "proyectos con sus columnas y sprints, catálogos y usuarios"),
    ("GET", "/api/tareas/", "consultar tareas (filtros por querystring)"),
    ("GET", "/api/tareas/<id>/", "una tarea"),
    ("POST", "/api/tareas/", "crear UNA tarea: mínimo {proyecto_id, titulo}"),
    ("POST", "/api/tareas/importar/", "crear muchas tareas de golpe (un solo resumen en el muro; \"simular\": true para probar)"),
    ("POST", "/api/tareas/<id>/", "editar solo los campos que se envíen"),
    ("POST", "/api/tareas/<id>/mover/", "cambiar de columna: {status}"),
    ("POST", "/api/tareas/<id>/asignar/", "asignar: {usuario} (username o id; null = quitar)"),
    ("POST", "/api/tareas/<id>/eliminar/", "a la papelera"),
    ("POST", "/api/tareas/<id>/restaurar/", "sacar de la papelera"),
    ("POST", "/api/muro/", "escribir en un muro: {proyecto_id | espacio_id, texto}"),
    ("POST", "/api/notas/", "nota del Buzón: {para, texto, vence_en?}"),
]


# ── autenticacion y utilidades ───────────────────────────────────────────────

def _resolver_api_token(request: Request):
    """None si la clave es invalida/falta, o {"proyecto_id", "token_id",
    "nombre", "user_id"} -- proyecto_id=None es acceso a todos los
    proyectos; token_id=None identifica a la clave maestra."""
    clave = request.headers.get("X-API-Key", "")
    if not clave:
        return None
    maestra = os.getenv("API_IMPORT_TOKEN", "").strip()
    if maestra and secrets.compare_digest(clave.encode(), maestra.encode()):
        return {"proyecto_id": None, "token_id": None, "nombre": "clave maestra", "user_id": None}
    token = db.find_api_token_by_hash(hashlib.sha256(clave.encode()).hexdigest())
    if not token:
        return None
    db.marcar_api_token_usado(token["token_id"])
    return {"proyecto_id": token["proyecto_id"], "token_id": token["token_id"],
            "nombre": token["nombre"], "user_id": token.get("user_id")}


def _match_prioridad(raw: str) -> str:
    raw = (raw or "").strip()
    return next((p for p in PRIORITIES if p.lower() == raw.lower()), "Normal")


def _error(mensaje: str, codigo: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": mensaje}, status_code=codigo)


def _no_autorizado():
    return _error("clave de API invalida o no configurada", 401)


async def _cuerpo(request: Request):
    """dict del cuerpo JSON, o una JSONResponse de error."""
    try:
        body = json.loads(await request.body() or b"{}")
    except ValueError:
        return _error("cuerpo JSON invalido")
    if not isinstance(body, dict):
        return _error("el cuerpo debe ser un objeto JSON")
    return body


def _ejecutar(funcion, *args, **kwargs) -> JSONResponse:
    try:
        return JSONResponse(funcion(*args, **kwargs))
    except acciones.AccionError as e:
        return _error(e.mensaje, e.codigo)


def _tarea_del_token(auth: dict, task_id: str):
    """Proyecto de la tarea si este token puede tocarla, o una respuesta 404
    (una tarea de OTRO proyecto responde 404, no 403: no se confirma que
    exista un id ajeno)."""
    t = db.get_tarea_api(task_id)
    if not t or (auth["proyecto_id"] and t["proyecto_id"] != auth["proyecto_id"]):
        return None
    return t


class _Catalogos:
    """Emparejado por NOMBRE (nunca crea catalogos nuevos), igual que la
    importacion desde Excel -- compartido por crear una y crear muchas."""

    def __init__(self, project_id: str):
        self.cat = [(c["nombre"], c["nombre"]) for c in db.load_categorias_globales()]
        self.sis = [(s["id"], s["nombre"]) for s in db.load_sistemas() if s["activo"]]
        self.emp = [(e["empresa_id"], e["nombre"]) for e in db.load_empresas() if e["activo"]]
        self.ini = [(i["id"], i["nombre"]) for i in db.load_iniciativas() if i["activo"]]
        self.spr = [(s["sprint_id"], s["nombre"]) for s in db.load_sprints(project_id)]

    def campos(self, raw: dict, avisos: list, etiqueta: str) -> dict:
        res = {}
        for clave, opciones, destino, texto in (
            ("categoria", self.cat, "categoria", "Categoría"), ("sistema", self.sis, "sistema_id", "Sistema"),
            ("empresa", self.emp, "empresa_id", "Empresa"), ("iniciativa", self.ini, "iniciativa_id", "Iniciativa"),
            ("sprint", self.spr, "sprint_id", "Sprint"),
        ):
            valor, ok = _match_by_name(_clean(raw.get(clave)), opciones)
            if not ok:
                avisos.append(f"{etiqueta}{texto} '{raw.get(clave)}' no encontrado, se deja vacío")
            res[destino] = valor
        return res


# ── consulta ─────────────────────────────────────────────────────────────────

@router.get("/")
def api_indice(request: Request):
    auth = _resolver_api_token(request)
    if not auth:
        return _no_autorizado()
    actor = acciones.Actor.api(auth)
    return JSONResponse({
        "ok": True, "actor": actor.nombre, "usuario": actor.username or None,
        "proyecto_restringido": auth["proyecto_id"],
        "manual": "GET /api/manual (Markdown, misma cabecera X-API-Key) -- léelo antes de crear nada",
        "endpoints": [{"metodo": m, "ruta": r, "que_hace": d} for m, r, d in ENDPOINTS],
    })


@router.get("/manual")
def api_manual(request: Request):
    """El manual de la API en Markdown, para que un agente (p. ej. Claude)
    que solo tiene la URL y la clave sepa usarla sin mas explicaciones."""
    if not _resolver_api_token(request):
        return _no_autorizado()
    if not MANUAL.exists():
        return _error("manual no encontrado en el servidor", 404)
    return PlainTextResponse(MANUAL.read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8")


@router.get("/dimensiones/")
def api_dimensiones(request: Request):
    """Catalogos para construir las llamadas sin adivinar nombres: proyectos
    (con sus columnas de tablero REALES) y sus sprints, categorias/empresas/
    sistemas/iniciativas globales y usuarios (para asignar). Con un token
    restringido a un proyecto, solo se devuelve ESE proyecto."""
    auth = _resolver_api_token(request)
    if not auth:
        return _no_autorizado()

    proyectos_todos = db.load_proyectos_basico()
    if auth["proyecto_id"]:
        proyectos_todos = [p for p in proyectos_todos if p["id"] == auth["proyecto_id"]]

    proyectos = []
    for p in proyectos_todos:
        sprints = db.load_sprints(p["id"]) if p["tipo"] == "scrum" else []
        proyectos.append({
            "id": p["id"], "nombre": p["nombre"], "tipo": p["tipo"], "estado": p["estado"],
            "columnas": [c["nombre"] for c in db.load_board_columns(p["id"])],
            "sprints": [{"id": s["sprint_id"], "nombre": s["nombre"], "estado": s["estado"]} for s in sprints],
        })

    return JSONResponse({
        "prioridades": PRIORITIES,
        "categorias": [c["nombre"] for c in db.load_categorias_globales()],
        "empresas": [{"id": e["empresa_id"], "nombre": e["nombre"]} for e in db.load_empresas() if e["activo"]],
        "sistemas": [{"id": s["id"], "nombre": s["nombre"], "empresa_id": s["empresa_id"]}
                     for s in db.load_sistemas() if s["activo"]],
        "iniciativas": [{"id": i["id"], "nombre": i["nombre"]} for i in db.load_iniciativas() if i["activo"]],
        "usuarios": [{"id": u["id"], "usuario": u["username"], "nombre": u["nombre_completo"]} for u in db.load_usuarios()],
        "proyectos": proyectos,
    })


@router.get("/tareas/")
def api_tareas_lista(request: Request):
    """Consulta de tareas, con filtros opcionales por querystring:
    proyecto_id, status, empresa_id, categoria, mantis_id, solo_mantis
    (0/1), incluir_borradas (0/1), actualizada_desde ('AAAA-MM-DD'), limit
    (200 por defecto, 1000 maximo), offset. Ordenadas por actualizada_en
    descendente (sincronizacion incremental)."""
    auth = _resolver_api_token(request)
    if not auth:
        return _no_autorizado()

    qp = request.query_params
    proyecto_id = qp.get("proyecto_id", "").strip()
    if auth["proyecto_id"]:
        if proyecto_id and proyecto_id != auth["proyecto_id"]:
            return _error("este token solo puede consultar un proyecto concreto", 403)
        proyecto_id = auth["proyecto_id"]
    if proyecto_id and not db.get_proyecto(proyecto_id):
        return _error(f"no existe el proyecto '{proyecto_id}'", 404)

    mantis_id = None
    mantis_id_raw = qp.get("mantis_id", "").strip()
    if mantis_id_raw:
        try:
            mantis_id = int(mantis_id_raw)
        except ValueError:
            return _error("'mantis_id' debe ser un entero")

    try:
        limit = min(int(qp.get("limit", API_TAREAS_LISTA_LIMIT_DEFECTO)), API_TAREAS_LISTA_LIMIT_MAX)
        offset = max(int(qp.get("offset", 0)), 0)
    except ValueError:
        return _error("'limit'/'offset' deben ser enteros")
    limit = max(limit, 1)

    tareas, total = db.load_tareas_api(
        proyecto_id=proyecto_id, status=qp.get("status", "").strip(), empresa_id=qp.get("empresa_id", "").strip(),
        categoria=qp.get("categoria", "").strip(), mantis_id=mantis_id,
        solo_mantis=qp.get("solo_mantis", "0").strip() == "1",
        incluir_borradas=qp.get("incluir_borradas", "0").strip() == "1",
        actualizada_desde=qp.get("actualizada_desde", "").strip(), limit=limit, offset=offset,
    )
    return JSONResponse({"ok": True, "total": total, "tareas": tareas})


@router.get("/tareas/{task_id}/")
def api_tarea_detalle(task_id: str, request: Request):
    auth = _resolver_api_token(request)
    if not auth:
        return _no_autorizado()
    tarea = _tarea_del_token(auth, task_id)
    if not tarea:
        return _error(f"no existe la tarea '{task_id}'", 404)
    return JSONResponse({"ok": True, "tarea": tarea})


# ── crear ────────────────────────────────────────────────────────────────────

@router.post("/tareas/")
async def api_tarea_crear(request: Request):
    """Crear UNA tarea. Minimo: {"proyecto_id": "...", "titulo": "..."}.
    Opcional: status, prioridad, descripcion, proximo_paso, fecha_inicio,
    fecha_fin, asignado (username o id), categoria/sistema/empresa/
    iniciativa/sprint (por nombre), mantis_id. Un status que no existe cae en
    la primera columna (con aviso), igual que importar."""
    auth = _resolver_api_token(request)
    if not auth:
        return _no_autorizado()
    body = await _cuerpo(request)
    if isinstance(body, JSONResponse):
        return body
    project_id = str(body.get("proyecto_id", "")).strip()
    if not project_id:
        return _error("falta 'proyecto_id'")
    if auth["proyecto_id"] and project_id != auth["proyecto_id"]:
        return _error("este token solo puede crear tareas en un proyecto concreto", 403)
    if not db.get_proyecto(project_id):
        return _error(f"no existe el proyecto '{project_id}'", 404)
    avisos = []
    campos = _Catalogos(project_id).campos(body, avisos, "")
    try:
        asignado = acciones.resolver_usuario(body.get("asignado"))
        mantis_id = int(body["mantis_id"]) if body.get("mantis_id") not in (None, "") else None
    except acciones.AccionError as e:
        return _error(e.mensaje, e.codigo)
    except (TypeError, ValueError):
        return _error("'mantis_id' debe ser un entero")
    if mantis_id and mantis_id in db.tareas_mantis_ids_importadas():
        return _error(f"ya hay una tarea del Mantis {mantis_id}", 409)
    try:
        r = acciones.crear_tarea(
            acciones.Actor.api(auth), project_id, _clean(body.get("titulo")), estado=_clean(body.get("status")) or None,
            prioridad=_match_prioridad(_clean(body.get("prioridad"))), descripcion=_clean(body.get("descripcion")),
            proximo_paso=_clean(body.get("proximo_paso")), fecha_inicio=_parse_excel_fecha(body.get("fecha_inicio")),
            fecha_fin=_parse_excel_fecha(body.get("fecha_fin")), asignado_a=asignado, mantis_id=mantis_id,
            subtareas=acciones.subtareas_json(body.get("subtareas")), **campos,
        )
    except acciones.AccionError as e:
        return _error(e.mensaje, e.codigo)
    status_pedido = _clean(body.get("status"))
    if status_pedido and _norm(status_pedido) != _norm(r["estado"]):
        avisos.append(f"status '{status_pedido}' no es una columna real del proyecto, se usó '{r['estado']}'")
    return JSONResponse({**r, "avisos": avisos}, status_code=201)


@router.post("/tareas/importar/")
async def api_tareas_importar(request: Request):
    """Crear muchas tareas de golpe -- cuerpo {"proyecto_id": "...",
    "tareas": [{"titulo": "...", ...mismos campos que POST /api/tareas/}]}.
    Tolerante fila a fila (una invalida se omite con aviso). Omite titulos
    ya existentes en el proyecto y mantis_id ya importados en cualquier
    proyecto. Cada tarea avisa a su asignado, pero el muro recibe UN solo
    resumen ("importó N tareas"), no un mensaje por tarea.
    "simular": true -> valida todo y devuelve lo que se crearia
    ('se_crearian') y los avisos, SIN crear nada ni avisar a nadie."""
    auth = _resolver_api_token(request)
    if not auth:
        return _no_autorizado()
    body = await _cuerpo(request)
    if isinstance(body, JSONResponse):
        return body

    project_id = str(body.get("proyecto_id", "")).strip()
    tareas_in = body.get("tareas")
    if not project_id:
        return _error("falta 'proyecto_id'")
    if auth["proyecto_id"] and project_id != auth["proyecto_id"]:
        return _error("este token solo puede crear tareas en un proyecto concreto", 403)
    if not isinstance(tareas_in, list) or not tareas_in:
        return _error("'tareas' debe ser una lista no vacia")
    if len(tareas_in) > API_IMPORT_MAX_TAREAS:
        return _error(f"maximo {API_IMPORT_MAX_TAREAS} tareas por llamada")
    if not db.get_proyecto(project_id):
        return _error(f"no existe el proyecto '{project_id}'", 404)

    actor = acciones.Actor.api(auth)
    simular = body.get("simular") is True
    se_crearian = []
    catalogos = _Catalogos(project_id)
    titulos_existentes = {_norm(t["title"]) for t in db.load_tasks_para_tablero(project_id, borrada=False)}
    ids_mantis_ya_importadas = db.tareas_mantis_ids_importadas()

    creadas, avisos, efectos = 0, [], []
    for idx, raw in enumerate(tareas_in):
        if not isinstance(raw, dict):
            avisos.append(f"tarea {idx}: no es un objeto, omitida")
            continue
        titulo = _clean(raw.get("titulo"))
        etiqueta = f"tarea {idx} ({titulo}): "
        if not titulo:
            avisos.append(f"tarea {idx}: sin 'titulo', omitida")
            continue
        if _norm(titulo) in titulos_existentes:
            avisos.append(f"{etiqueta}ya existe una tarea con este titulo en el proyecto, omitida")
            continue

        mantis_id = None
        if raw.get("mantis_id") not in (None, ""):
            try:
                mantis_id = int(raw.get("mantis_id"))
            except (TypeError, ValueError):
                avisos.append(f"{etiqueta}'mantis_id' invalido ({raw.get('mantis_id')!r}), se ignora")
            else:
                if mantis_id in ids_mantis_ya_importadas:
                    avisos.append(f"{etiqueta}mantis_id {mantis_id} ya importado antes, omitida")
                    continue

        try:
            asignado = acciones.resolver_usuario(raw.get("asignado"))
        except acciones.AccionError as e:
            avisos.append(f"{etiqueta}{e.mensaje}, se deja sin asignar")
            asignado = None
        campos = catalogos.campos(raw, avisos, etiqueta)
        try:
            subtareas = acciones.subtareas_json(raw.get("subtareas"))
        except acciones.AccionError as e:
            avisos.append(f"{etiqueta}{e.mensaje}, se crea sin subtareas")
            subtareas = ""
        if simular:
            estado = acciones._estado_valido(project_id, _clean(raw.get("status")) or None, estricto=False)
            if _clean(raw.get("status")) and _norm(_clean(raw.get("status"))) != _norm(estado):
                avisos.append(f"{etiqueta}status '{_clean(raw.get('status'))}' no es una columna real del proyecto, se usaría '{estado}'")
            se_crearian.append({"titulo": titulo, "status": estado, "asignado_a": asignado,
                                "subtareas": len(json.loads(subtareas)) if subtareas else 0})
            titulos_existentes.add(_norm(titulo))
            if mantis_id:
                ids_mantis_ya_importadas.add(mantis_id)
            continue
        try:
            r = acciones.crear_tarea(
                actor, project_id, titulo, estado=_clean(raw.get("status")) or None,
                prioridad=_match_prioridad(_clean(raw.get("prioridad"))), descripcion=_clean(raw.get("descripcion")),
                proximo_paso=_clean(raw.get("proximo_paso")), fecha_inicio=_parse_excel_fecha(raw.get("fecha_inicio")),
                fecha_fin=_parse_excel_fecha(raw.get("fecha_fin")), asignado_a=asignado, mantis_id=mantis_id,
                subtareas=subtareas, publicar=False, **campos,
            )
        except acciones.AccionError as e:
            avisos.append(f"{etiqueta}{e.mensaje}, omitida")
            continue
        status_pedido = _clean(raw.get("status"))
        if status_pedido and _norm(status_pedido) != _norm(r["estado"]):
            avisos.append(f"{etiqueta}status '{status_pedido}' no es una columna real del proyecto, se usó '{r['estado']}'")
        efectos += [e for e in r["efectos"] if e.startswith("aviso:")]
        creadas += 1
        titulos_existentes.add(_norm(titulo))
        if mantis_id:
            ids_mantis_ya_importadas.add(mantis_id)

    if simular:
        return JSONResponse({"ok": True, "simulacion": True, "se_crearian": se_crearian, "avisos": avisos, "efectos": []})
    acciones.importar_resumen(actor, project_id, creadas, "vía API")
    efectos = ([f"tareas_creadas:{creadas}"] if creadas else []) + efectos + actor.efectos
    actor.efectos = []
    return JSONResponse({"ok": True, "creadas": creadas, "avisos": avisos, "efectos": efectos})


# ── cambiar una tarea ────────────────────────────────────────────────────────

_EDITABLES = {
    "titulo": "titulo", "descripcion": "descripcion", "proximo_paso": "proximo_paso", "prioridad": "prioridad",
    "status": "estado", "fecha_inicio": "fecha_inicio", "fecha_fin": "fecha_fin",
}


@router.post("/tareas/{task_id}/")
async def api_tarea_editar(task_id: str, request: Request):
    """Editar SOLO los campos que se envien: titulo, descripcion,
    proximo_paso, prioridad, status, fecha_inicio, fecha_fin, asignado
    (username/id; null = quitar). Cambiar 'status' a una columna "hecha" con
    subtareas pendientes en un proyecto que lo prohibe -> 409."""
    auth = _resolver_api_token(request)
    if not auth:
        return _no_autorizado()
    if not _tarea_del_token(auth, task_id):
        return _error(f"no existe la tarea '{task_id}'", 404)
    body = await _cuerpo(request)
    if isinstance(body, JSONResponse):
        return body
    cambios = {destino: body[origen] for origen, destino in _EDITABLES.items() if origen in body}
    for fecha in ("fecha_inicio", "fecha_fin"):
        if fecha in cambios:
            cambios[fecha] = _parse_excel_fecha(cambios[fecha])
    try:
        if "asignado" in body:
            cambios["asignado_a"] = acciones.resolver_usuario(body["asignado"])
        if not cambios:
            return _error(f"nada que cambiar; campos admitidos: {', '.join(list(_EDITABLES) + ['asignado'])}")
        return JSONResponse(acciones.editar_tarea(acciones.Actor.api(auth), task_id, si_bloquea_cierre="error", **cambios))
    except acciones.AccionError as e:
        return _error(e.mensaje, e.codigo)


@router.post("/tareas/{task_id}/mover/")
async def api_tarea_mover(task_id: str, request: Request):
    """{"status": "..."} -- nombre EXACTO (o con otras mayusculas) de una
    columna real de su mismo proyecto; si no existe, 400. Cerrar con
    subtareas pendientes en un proyecto que lo prohibe -> 409."""
    auth = _resolver_api_token(request)
    if not auth:
        return _no_autorizado()
    body = await _cuerpo(request)
    if isinstance(body, JSONResponse):
        return body
    new_status = str(body.get("status", "")).strip()
    if not new_status:
        return _error("falta 'status'")
    if not _tarea_del_token(auth, task_id):
        return _error(f"no existe la tarea '{task_id}'", 404)
    return _ejecutar(acciones.mover_tarea, acciones.Actor.api(auth), task_id, new_status)


@router.post("/tareas/{task_id}/asignar/")
async def api_tarea_asignar(task_id: str, request: Request):
    """{"usuario": "username" | id | null}."""
    auth = _resolver_api_token(request)
    if not auth:
        return _no_autorizado()
    if not _tarea_del_token(auth, task_id):
        return _error(f"no existe la tarea '{task_id}'", 404)
    body = await _cuerpo(request)
    if isinstance(body, JSONResponse):
        return body
    if "usuario" not in body:
        return _error("falta 'usuario' (username, id, o null para quitar la asignación)")
    try:
        user_id = acciones.resolver_usuario(body["usuario"])
    except acciones.AccionError as e:
        return _error(e.mensaje, e.codigo)
    return _ejecutar(acciones.asignar_tarea, acciones.Actor.api(auth), task_id, user_id)


@router.post("/tareas/{task_id}/eliminar/")
def api_tarea_eliminar(task_id: str, request: Request):
    auth = _resolver_api_token(request)
    if not auth:
        return _no_autorizado()
    if not _tarea_del_token(auth, task_id):
        return _error(f"no existe la tarea '{task_id}'", 404)
    return _ejecutar(acciones.eliminar_tarea, acciones.Actor.api(auth), task_id)


@router.post("/tareas/{task_id}/restaurar/")
def api_tarea_restaurar(task_id: str, request: Request):
    auth = _resolver_api_token(request)
    if not auth:
        return _no_autorizado()
    t = db.get_tarea_resumen(task_id)
    if not t or (auth["proyecto_id"] and t["proyecto_id"] != auth["proyecto_id"]):
        return _error(f"no existe la tarea '{task_id}'", 404)
    return _ejecutar(acciones.restaurar_tarea, acciones.Actor.api(auth), task_id)


# ── muro y buzon ─────────────────────────────────────────────────────────────

@router.post("/muro/")
async def api_muro(request: Request):
    """{"proyecto_id": "..." | "espacio_id": "...", "texto": "..."} -- como
    escribir en el muro desde la web, firmado por el dueño del token. Un
    token restringido a un proyecto solo puede escribir en el de ese proyecto."""
    auth = _resolver_api_token(request)
    if not auth:
        return _no_autorizado()
    body = await _cuerpo(request)
    if isinstance(body, JSONResponse):
        return body
    proyecto_id = _clean(body.get("proyecto_id")) or None
    espacio_id = _clean(body.get("espacio_id")) or None
    if auth["proyecto_id"] and proyecto_id != auth["proyecto_id"]:
        return _error("este token solo puede escribir en el muro de su proyecto", 403)
    try:
        r = acciones.escribir_en_muro(acciones.Actor.api(auth), _clean(body.get("texto")),
                                      espacio_id=espacio_id, proyecto_id=proyecto_id)
    except acciones.AccionError as e:
        return _error(e.mensaje, e.codigo)
    return JSONResponse(r, status_code=201)


@router.post("/notas/")
async def api_nota(request: Request):
    """{"para": "username" | id, "texto": "...", "vence_en": "AAAA-MM-DD"?,
    "aviso_cantidad": 1?, "aviso_unidad": "horas|dias|semanas"?} -- nota del
    Buzon del dueño del token ('para' vacio = a si mismo). No disponible
    para tokens restringidos a un proyecto (una nota no es de ningun proyecto)."""
    auth = _resolver_api_token(request)
    if not auth:
        return _no_autorizado()
    if auth["proyecto_id"]:
        return _error("un token restringido a un proyecto no puede enviar notas", 403)
    body = await _cuerpo(request)
    if isinstance(body, JSONResponse):
        return body
    try:
        r = acciones.enviar_nota(
            acciones.Actor.api(auth), body.get("para"), _clean(body.get("texto")),
            vence_en=_parse_excel_fecha(body.get("vence_en")), aviso_cantidad=body.get("aviso_cantidad", 1),
            aviso_unidad=str(body.get("aviso_unidad", "dias")),
        )
    except acciones.AccionError as e:
        return _error(e.mensaje, e.codigo)
    except (TypeError, ValueError):
        return _error("'aviso_cantidad' debe ser un número")
    return JSONResponse(r, status_code=201)
