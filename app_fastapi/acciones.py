# -*- coding: utf-8 -*-
"""Acciones de la app -- UN solo sitio por cada cosa que se puede hacer con
una tarea (crear, editar, mover, asignar, eliminar, restaurar), escribir en
un muro o enviar una nota, con TODO lo que esa accion arrastra:

    validar -> guardar -> avisar en la campana -> publicar en el muro

La web (routers/tablero.py, calendario, agenda, reunion, buzon) y la API
externa (routers/api_externa.py) llaman a estas mismas funciones: una tarea
creada por un script con datos minimos sale en el muro y avisa al asignado
igual que si la hubiera creado alguien desde el tablero. Antes la API
escribia directamente en la BD y se saltaba todo eso.

Cada accion recibe un Actor (quien lo hace y por donde: web o API) y
devuelve un dict con lo que ha pasado, incluida la lista 'efectos' (p. ej.
["muro", "aviso:marta"]) -- la API la devuelve tal cual para que quien la
usa vea que una accion pequeña ha tocado varias partes de la app. Los
errores se lanzan como AccionError(mensaje, codigo HTTP).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from . import db, muro, notificar

PRIORIDADES = ["Normal", "Alta", "Baja"]


class AccionError(Exception):
    def __init__(self, mensaje: str, codigo: int = 400):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo


@dataclass
class Actor:
    """Quien hace la accion. 'nombre' es como sale en el muro y en los avisos."""
    user_id: int | None
    nombre: str
    username: str = ""
    es_it: bool = False
    via: str = "web"  # 'web' | 'api'
    efectos: list = field(default_factory=list, repr=False)

    @classmethod
    def web(cls, request, usuario: str) -> "Actor":
        user_id = db.get_user_id(usuario)
        nombre = next((u["nombre_completo"] for u in db.load_usuarios() if u["id"] == user_id), usuario)
        return cls(user_id, nombre, usuario, bool(request.session.get("es_it")) if request is not None else False)

    @classmethod
    def api(cls, token: dict) -> "Actor":
        """token: lo que devuelve api_externa._resolver_api_token. Con dueño,
        la API actua como esa persona; sin dueño (clave maestra o token
        antiguo), firma como la propia API."""
        etiqueta = token.get("nombre") or "clave maestra"
        user_id = token.get("user_id")
        if user_id:
            u = next((u for u in db.load_usuarios() if u["id"] == user_id), None)
            if u:
                return cls(user_id, f"{u['nombre_completo']} (vía API: {etiqueta})", u["username"], via="api")
        return cls(None, f"API · {etiqueta}", "", via="api")


# ── utilidades ───────────────────────────────────────────────────────────────

def _usuario_valido(user_id) -> int | None:
    if user_id in (None, ""):
        return None
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        raise AccionError(f"usuario '{user_id}' no válido")
    if user_id not in {u["id"] for u in db.load_usuarios()}:
        raise AccionError(f"no existe el usuario con id {user_id}", 404)
    return user_id


def resolver_usuario(valor) -> int | None:
    """Acepta un id o un username (lo comodo desde un script)."""
    if valor in (None, ""):
        return None
    if isinstance(valor, int) or str(valor).isdigit():
        return _usuario_valido(valor)
    u = next((u for u in db.load_usuarios() if u["username"].lower() == str(valor).strip().lower()), None)
    if not u:
        raise AccionError(f"no existe el usuario '{valor}'", 404)
    return u["id"]


def subtareas_json(valor) -> str:
    """Subtareas tal como las guarda el tablero (lista JSON de {"t": texto,
    "d": hecha}) a partir de lo comodo para un script: ["paso 1", "paso 2"]
    o [{"texto": "...", "hecho": true}]. Un str se deja tal cual (ya viene
    en el formato del tablero)."""
    import json
    if valor in (None, "", []):
        return ""
    if isinstance(valor, str):
        return valor
    if not isinstance(valor, list):
        raise AccionError("'subtareas' debe ser una lista de textos o de {texto, hecho}")
    items = []
    for s in valor:
        if isinstance(s, str) and s.strip():
            items.append({"t": s.strip()[:300], "d": False})
        elif isinstance(s, dict) and str(s.get("texto", "")).strip():
            items.append({"t": str(s["texto"]).strip()[:300], "d": bool(s.get("hecho"))})
    return json.dumps(items, ensure_ascii=False) if items else ""


def _columnas(proyecto_id: str) -> list:
    return db.load_board_columns(proyecto_id)


def _estado_valido(proyecto_id: str, estado: str | None, estricto: bool) -> str:
    """Columna real del proyecto. Sin estado -> primera columna no "hecha".
    Un estado que no existe: error si estricto, si no la primera columna."""
    columnas = _columnas(proyecto_id)
    por_defecto = next((c["nombre"] for c in columnas if not c["es_done"]), columnas[0]["nombre"] if columnas else "Pendiente")
    if not estado:
        return por_defecto
    exacta = next((c["nombre"] for c in columnas if c["nombre"] == estado), None)
    if exacta:
        return exacta
    parecida = next((c["nombre"] for c in columnas if c["nombre"].strip().lower() == estado.strip().lower()), None)
    if parecida:
        return parecida
    if estricto:
        raise AccionError(f"'{estado}' no es una columna real de este proyecto ({', '.join(c['nombre'] for c in columnas)})")
    return por_defecto


def _comprobar_permiso(actor: Actor, proyecto_id: str, permiso: str, asignado_a=None) -> None:
    """Mismas reglas que el tablero (db.puede_actuar_en_proyecto). Una clave
    de API sin dueño no tiene usuario con el que comprobar: le basta con su
    alcance de proyecto, que ya comprueba el router (igual que antes)."""
    if actor.via == "api" and actor.user_id is None:
        return
    if not db.puede_actuar_en_proyecto(proyecto_id, actor.user_id, permiso, asignado_a):
        raise AccionError("no tienes permiso para hacer esto en este proyecto", 403)


def _tarea_o_404(task_id: str) -> dict:
    t = db.get_tarea_api(task_id)
    if not t or t["borrada"]:
        raise AccionError(f"no existe la tarea '{task_id}'", 404)
    return t


def _resultado(actor: Actor, **datos) -> dict:
    efectos, actor.efectos = actor.efectos, []
    return {"ok": True, **datos, "efectos": efectos}


def _avisar_asignado(actor: Actor, asignado, task_id: str, titulo: str, proyecto_id: str) -> None:
    if notificar.tarea_asignada(asignado, actor.user_id, actor.username, task_id, titulo, proyecto_id, nombre=actor.nombre):
        username = next((u["username"] for u in db.load_usuarios() if u["id"] == asignado), str(asignado))
        actor.efectos.append(f"aviso:{username}")


def _muro(actor: Actor, publicado: bool) -> None:
    if publicado:
        actor.efectos.append("muro")


# ── tareas ───────────────────────────────────────────────────────────────────

def crear_tarea(actor: Actor, proyecto_id: str, titulo: str, *, estado: str = None, prioridad: str = "Normal",
                descripcion: str = "", proximo_paso: str = "", fecha_inicio: str = "", fecha_fin: str = "",
                categoria: str = "", empresa_id: str = "", sistema_id: str = "", iniciativa_id: str = "",
                sprint_id: str = "", asignado_a=None, subtareas: str = "", tiempo_estimado=None, tiempo_real=None,
                anclada: bool = False, mantis_id=None, reunion_id: str = "", estado_estricto: bool = False,
                publicar: bool = True, task_id: str = None) -> dict:
    """Datos minimos: proyecto y titulo. publicar=False solo para
    importaciones masivas (publican un resumen aparte, ver importar)."""
    titulo = (titulo or "").strip()[:200]
    if not titulo:
        raise AccionError("falta el título")
    if not db.get_proyecto(proyecto_id):
        raise AccionError(f"no existe el proyecto '{proyecto_id}'", 404)
    estado = _estado_valido(proyecto_id, estado, estado_estricto)
    asignado = _usuario_valido(asignado_a)
    prioridad = next((p for p in PRIORIDADES if p.lower() == (prioridad or "").strip().lower()), "Normal")
    task_id = task_id or str(uuid.uuid4())[:8]
    db.crear_tarea(
        task_id, proyecto_id, (categoria or "").strip(), titulo, estado, prioridad,
        (descripcion or "").strip(), (proximo_paso or "").strip(), (fecha_inicio or "").strip(), (fecha_fin or "").strip(),
        empresa_id=(empresa_id or "").strip(), iniciativa_id=(iniciativa_id or "").strip(), sistema_id=(sistema_id or "").strip(),
        anclada=anclada, subtareas=(subtareas or "").strip(), tiempo_estimado=tiempo_estimado, tiempo_real=tiempo_real,
        sprint_id=(sprint_id or "").strip(), mantis_id=mantis_id, reunion_id=reunion_id or "", asignado_a=asignado,
    )
    actor.efectos.append("tarea_creada")
    _avisar_asignado(actor, asignado, task_id, titulo, proyecto_id)
    if publicar:
        _muro(actor, muro.tarea_creada(task_id, actor))
    return _resultado(actor, id=task_id, proyecto_id=proyecto_id, estado=estado)


_SIN_CAMBIO = object()


def editar_tarea(actor: Actor, task_id: str, *, proyecto_id: str = None, titulo=_SIN_CAMBIO, estado=_SIN_CAMBIO,
                 prioridad=_SIN_CAMBIO, descripcion=_SIN_CAMBIO, proximo_paso=_SIN_CAMBIO, fecha_inicio=_SIN_CAMBIO,
                 fecha_fin=_SIN_CAMBIO, categoria=_SIN_CAMBIO, empresa_id=_SIN_CAMBIO, sistema_id=_SIN_CAMBIO,
                 iniciativa_id=_SIN_CAMBIO, sprint_id=_SIN_CAMBIO, asignado_a=_SIN_CAMBIO, subtareas=_SIN_CAMBIO,
                 tiempo_estimado=_SIN_CAMBIO, tiempo_real=_SIN_CAMBIO, anclada=_SIN_CAMBIO,
                 si_bloquea_cierre: str = "revertir") -> dict:
    """Edicion parcial: solo cambia lo que se pasa (desde la API basta con
    {"prioridad": "Alta"}); el modal del tablero pasa todo. Si el nuevo
    estado es "hecho" y el proyecto exige subtareas completas y quedan
    pendientes: si_bloquea_cierre='revertir' (tablero: se guarda lo demas y
    el estado se queda como estaba) o 'error' (API: 409)."""
    actual = _tarea_o_404(task_id)
    _, antes_estado, subtareas_antes, antes_asignado = db.tarea_estado_actual(task_id)
    proyecto_id = proyecto_id or actual["proyecto_id"]
    if proyecto_id != actual["proyecto_id"] and not db.get_proyecto(proyecto_id):
        raise AccionError(f"no existe el proyecto '{proyecto_id}'", 404)

    def v(nuevo, clave):
        return actual[clave] if nuevo is _SIN_CAMBIO else nuevo

    nuevo_titulo = (v(titulo, "titulo") or "").strip()[:200]
    if not nuevo_titulo:
        raise AccionError("el título no puede quedar vacío")
    nuevo_estado = antes_estado if estado is _SIN_CAMBIO else _estado_valido(proyecto_id, estado, actor.via == "api")
    nuevas_subtareas = subtareas_antes if subtareas is _SIN_CAMBIO else (subtareas or "")
    if nuevo_estado != antes_estado and db.bloquea_cierre_por_subtareas(proyecto_id, nuevo_estado, nuevas_subtareas):
        if si_bloquea_cierre == "error":
            raise AccionError("no se puede cerrar: quedan subtareas sin completar", 409)
        nuevo_estado = antes_estado
    nuevo_asignado = antes_asignado if asignado_a is _SIN_CAMBIO else _usuario_valido(asignado_a)
    prioridad_v = v(prioridad, "prioridad")
    prioridad_v = next((p for p in PRIORIDADES if p.lower() == (prioridad_v or "").lower()), "Normal")

    db.editar_tarea(
        task_id, proyecto_id, (v(categoria, "categoria") or "").strip(), nuevo_titulo, nuevo_estado, prioridad_v,
        (v(descripcion, "descripcion") or "").strip(), (v(proximo_paso, "proximo_paso") or "").strip(),
        (v(fecha_inicio, "fecha_inicio") or "").strip(), (v(fecha_fin, "fecha_fin") or "").strip(),
        empresa_id=(v(empresa_id, "empresa_id") or "").strip(), iniciativa_id=(v(iniciativa_id, "iniciativa_id") or "").strip(),
        sistema_id=(v(sistema_id, "sistema_id") or "").strip(), anclada=bool(v(anclada, "anclada")),
        subtareas=None if subtareas is _SIN_CAMBIO else (subtareas or "").strip(),
        tiempo_estimado=None if tiempo_estimado is _SIN_CAMBIO else (tiempo_estimado or None),
        tiempo_real=None if tiempo_real is _SIN_CAMBIO else (tiempo_real or None),
        sprint_id=(v(sprint_id, "sprint_id") or "").strip(), asignado_a=nuevo_asignado,
    )
    actor.efectos.append("tarea_editada")
    if nuevo_asignado and nuevo_asignado != antes_asignado:
        _avisar_asignado(actor, nuevo_asignado, task_id, nuevo_titulo, proyecto_id)
    _muro(actor, muro.tarea_cambiada(task_id, actor, antes_estado, antes_asignado))
    return _resultado(actor, id=task_id, estado=nuevo_estado)


def mover_tarea(actor: Actor, task_id: str, estado: str, antes_de: str = "") -> dict:
    """Cambiar de columna (arrastrar en el tablero o API). Columna exacta;
    cerrar con subtareas pendientes en un proyecto que lo prohibe -> 409."""
    proyecto_id, antes_estado, subtareas, asignado = db.tarea_estado_actual(task_id)
    if not proyecto_id:
        raise AccionError(f"no existe la tarea '{task_id}'", 404)
    _comprobar_permiso(actor, proyecto_id, "editores_mueven_tareas_ajenas", asignado)
    estado = _estado_valido(proyecto_id, estado, estricto=True)
    if estado != antes_estado and db.bloquea_cierre_por_subtareas(proyecto_id, estado, subtareas):
        raise AccionError("no se puede cerrar: quedan subtareas sin completar", 409)
    if not db.reordenar_tarea(task_id, estado, antes_de or ""):
        raise AccionError("no se pudo mover la tarea", 409)
    actor.efectos.append("tarea_movida")
    if estado != antes_estado:
        _muro(actor, muro.tarea_cambiada(task_id, actor, antes_estado, asignado))
    return _resultado(actor, id=task_id, estado=estado)


def asignar_tarea(actor: Actor, task_id: str, user_id) -> dict:
    """user_id None = quitar la asignacion."""
    return editar_tarea(actor, task_id, asignado_a=user_id)


def eliminar_tarea(actor: Actor, task_id: str) -> dict:
    proyecto_id, _, _, asignado = db.tarea_estado_actual(task_id)
    if not proyecto_id:
        raise AccionError(f"no existe la tarea '{task_id}'", 404)
    _comprobar_permiso(actor, proyecto_id, "editores_eliminan_tareas_ajenas", asignado)
    db.toggle_borrada_tarea(task_id, True)
    actor.efectos.append("tarea_eliminada")
    _muro(actor, muro.tarea_eliminada(task_id, actor))
    return _resultado(actor, id=task_id)


def restaurar_tarea(actor: Actor, task_id: str) -> dict:
    t = db.get_tarea_resumen(task_id)
    if not t:
        raise AccionError(f"no existe la tarea '{task_id}'", 404)
    db.toggle_borrada_tarea(task_id, False)
    actor.efectos.append("tarea_restaurada")
    _muro(actor, muro.tarea_eliminada(task_id, actor, restaurada=True))
    return _resultado(actor, id=task_id)


def importar_resumen(actor: Actor, proyecto_id: str, n: int, origen: str) -> None:
    """Tras una importacion masiva con crear_tarea(..., publicar=False)."""
    _muro(actor, muro.tareas_importadas(proyecto_id, actor, n, origen))


# ── muro y buzon ─────────────────────────────────────────────────────────────

def escribir_en_muro(actor: Actor, texto: str, *, espacio_id: str = None, proyecto_id: str = None) -> dict:
    """En el muro de un espacio o en el de un proyecto (que es el de su
    espacio, etiquetado). Mismas reglas que la web: Admin/Editor (o IT)."""
    texto = (texto or "").strip()[:4000]
    if not texto:
        raise AccionError("el mensaje está vacío")
    if proyecto_id:
        proyecto = db.get_proyecto(proyecto_id)
        if not proyecto:
            raise AccionError(f"no existe el proyecto '{proyecto_id}'", 404)
        if not proyecto["espacio_id"]:
            raise AccionError("este proyecto no está en ningún espacio, así que no tiene muro", 409)
        espacio_id = proyecto["espacio_id"]
    espacio = db.get_espacio(espacio_id) if espacio_id else None
    if not espacio:
        raise AccionError("falta el espacio o el proyecto", 400 if not espacio_id else 404)
    if actor.user_id is None:
        raise AccionError("para escribir en un muro hace falta un token con dueño (créalo de nuevo en Configuración → API)", 403)
    if muro.acceso(espacio, actor.user_id, actor.es_it) != muro.ESCRIBIR:
        raise AccionError("no puedes escribir en este muro", 403)
    mensaje_id = muro.escribir(espacio_id, actor.user_id, actor.nombre, texto, proyecto_id=proyecto_id)
    actor.efectos.append("muro")
    return _resultado(actor, id=mensaje_id, espacio_id=espacio_id, proyecto_id=proyecto_id)


def enviar_nota(actor: Actor, para, texto: str, *, vence_en: str = "", aviso_cantidad: int = 1,
                aviso_unidad: str = "dias") -> dict:
    """Nota del Buzon de 'actor' a 'para' (id o username; vacio = a si mismo)."""
    if actor.user_id is None:
        raise AccionError("para enviar notas hace falta un token con dueño (créalo de nuevo en Configuración → API)", 403)
    texto = (texto or "").strip()[:4000]
    if not texto:
        raise AccionError("la nota está vacía")
    para_id = resolver_usuario(para) or actor.user_id
    nota_id = db.crear_buzon_nota(actor.user_id, para_id, texto, (vence_en or "").strip(),
                                  max(0, int(aviso_cantidad or 0)), aviso_unidad)
    actor.efectos.append("nota")
    if para_id != actor.user_id:
        notificar.nota_recibida(para_id, actor.username, texto, nota_id, nombre=actor.nombre)
        actor.efectos.append(f"aviso:{next((u['username'] for u in db.load_usuarios() if u['id'] == para_id), para_id)}")
    return _resultado(actor, id=nota_id)
