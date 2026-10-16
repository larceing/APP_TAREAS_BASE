# -*- coding: utf-8 -*-
"""Muro de actividad de cada espacio -- fase 2 de mensajeria, inspirada en el
muro de pizarra de CS Manager (otra app interna: services/board_wall.py y
FUNCIONAL.md 6.2): un tablon que se rellena solo con lo que pasa en el
espacio, y donde los miembros tambien pueden escribir.

Eventos automaticos (mensajes de sistema, no se pueden borrar), publicados
desde los routers donde ocurre cada cosa:
- tarea creada (y a quien se asigno), asignada / reasignada
- empieza a trabajarse: sale de la PRIMERA columna del tablero hacia una
  columna que no es "hecha"
- completada: entra en una columna marcada como hecha (es_done); reabierta:
  sale de ella
- eliminada / restaurada
- proyecto creado; miembro anadido / quitado / cambio de rol
Los cambios hechos por importaciones automaticas (Mantis, Excel, API) no se
publican, para no inundar el muro. Comentarios y bloqueos de tareas no
existen todavia en la app, asi que tampoco hay eventos para ellos.

Muro por proyecto: cada mensaje del muro de un espacio puede llevar el
proyecto al que se refiere (chat_mensajes.proyecto_id). Los eventos de
tareas lo llevan siempre; lo que se escribe desde la pestana "Muro" de un
proyecto, tambien. El muro del espacio lo reune todo (con una etiqueta del
proyecto) y la pestana de cada proyecto filtra solo lo suyo: un solo
sitio donde se guarda, dos formas de verlo.

Proyectos sin espacio (legado) no tienen muro: sus eventos se ignoran.

Todo se ve en un solo sitio, /muro/ (routers/muro.py): la lista de muros
de los espacios de cada uno (con sus proyectos) y la conversacion. La app
no es de chats: no hay chats directos ni de grupo; lo de persona a persona
va por el Buzon, y los avisos de IT ("Aviso", antes "Difundir") se publican
en los muros.

Quien ve el muro:
- espacio personal: solo su dueño;
- espacio compartido: sus miembros (Admin/Editor escriben, Lector solo lee)
  y el equipo IT (lee y escribe en todos, como el admin de CS Manager).
"""
from urllib.parse import urlencode

from . import db

LEER, ESCRIBIR = "leer", "escribir"


def acceso(espacio: dict, user_id, es_it: bool):
    """None, LEER o ESCRIBIR."""
    if not espacio or not user_id:
        return None
    if espacio["es_personal"]:
        return ESCRIBIR if db.get_espacio_owner(espacio["id"]) == user_id else None
    if es_it:
        return ESCRIBIR
    rol = db.rol_en_espacio(espacio["id"], user_id)
    if rol in ("admin", "editor"):
        return ESCRIBIR
    return LEER if rol == "lector" else None


def url_muro(espacio_id: str) -> str:
    return f"/muro/?espacio={espacio_id}"


def url_muro_proyecto(proyecto_id: str) -> str:
    return f"/proyecto/{proyecto_id}/muro/"


def _nombre_usuario(user_id) -> str:
    if not user_id:
        return "alguien"
    for u in db.load_usuarios():
        if u["id"] == user_id:
            return u["nombre_completo"]
    return "alguien"


def _quien(actor) -> tuple:
    """(user_id, nombre visible) de quien hace algo. 'actor' puede ser un
    acciones.Actor (web o API: lleva su propio nombre, p. ej.
    "ana.lopez (vía API: informe)") o, por compatibilidad, un user_id suelto."""
    if hasattr(actor, "user_id"):
        return actor.user_id, actor.nombre
    return actor, _nombre_usuario(actor)


def _url_tarea(task_id: str, proyecto_id: str) -> str:
    return f"/proyecto/{proyecto_id}/tablero/?{urlencode({'abrir_tarea': task_id})}"


def _publicar_en_proyecto(proyecto_id: str, actor_id, texto: str, url: str = "") -> bool:
    proyecto = db.get_proyecto(proyecto_id)
    if not proyecto or not proyecto["espacio_id"]:
        return False
    sala_id = db.get_or_create_sala_muro(proyecto["espacio_id"])
    db.crear_chat_mensaje(sala_id, actor_id, texto, url, es_sistema=True, proyecto_id=proyecto_id)
    return True


def publicar_en_espacio(espacio_id: str, actor_id, texto: str, url: str = "", proyecto_id: str = None) -> bool:
    sala_id = db.get_or_create_sala_muro(espacio_id)
    db.crear_chat_mensaje(sala_id, actor_id, texto, url, es_sistema=True, proyecto_id=proyecto_id)
    return True


def escribir(espacio_id: str, autor_id: int, autor_nombre: str, contenido: str, proyecto_id: str = None) -> int:
    """Mensaje de una persona: se guarda y avisa en la campana a los demas
    miembros que no hayan silenciado el muro (una sola notificacion sin leer
    por muro y persona, para no llenar la campana si hay conversacion). Si
    es de un proyecto, el aviso lleva a la pestana Muro de ese proyecto."""
    sala_id = db.get_or_create_sala_muro(espacio_id)
    mensaje_id = db.crear_chat_mensaje(sala_id, autor_id, contenido, proyecto_id=proyecto_id)
    if proyecto_id:
        donde, url = f"«{db.get_proyecto(proyecto_id)['nombre']}»", url_muro_proyecto(proyecto_id)
    else:
        donde, url = f"el muro de {db.get_espacio(espacio_id)['nombre']}", url_muro(espacio_id)
    resumen = " ".join(contenido.split())
    resumen = resumen if len(resumen) <= 70 else resumen[:67] + "..."
    for uid in db.miembros_a_avisar_muro(espacio_id, sala_id, autor_id):
        if not db.tiene_notificacion_sin_leer(uid, url):
            db.crear_notificacion(uid, "muro", f"{autor_nombre} en {donde}: {resumen}", url)
    return mensaje_id


# ── eventos de tareas (devuelven True si han publicado algo) ────────────────

def tarea_creada(task_id: str, actor) -> bool:
    actor_id, nombre = _quien(actor)
    t = db.get_tarea_resumen(task_id)
    if not t:
        return False
    texto = f"{nombre} creó la tarea «{t['titulo']}»"
    if t["asignado_a"] and t["asignado_a"] != actor_id:
        texto += f" y se la asignó a {_nombre_usuario(t['asignado_a'])}"
    return _publicar_en_proyecto(t["proyecto_id"], actor_id, texto, _url_tarea(task_id, t["proyecto_id"]))


def tarea_cambiada(task_id: str, actor, antes_estado: str, antes_asignado) -> bool:
    """Llamar DESPUES de guardar, con el estado y el asignado de ANTES."""
    actor_id, nombre = _quien(actor)
    t = db.get_tarea_resumen(task_id)
    if not t:
        return False
    url = _url_tarea(task_id, t["proyecto_id"])
    publicado = False
    if t["asignado_a"] and t["asignado_a"] != antes_asignado:
        if t["asignado_a"] == actor_id:
            texto = f"{nombre} se asignó «{t['titulo']}»"
        else:
            verbo = "reasignó" if antes_asignado else "asignó"
            texto = f"{nombre} {verbo} «{t['titulo']}» a {_nombre_usuario(t['asignado_a'])}"
        publicado = _publicar_en_proyecto(t["proyecto_id"], actor_id, texto, url) or publicado
    if antes_estado and t["estado"] != antes_estado:
        columnas = db.load_board_columns(t["proyecto_id"])
        hechas = {c["nombre"] for c in columnas if c["es_done"]}
        primera = columnas[0]["nombre"] if columnas else None
        if t["estado"] in hechas and antes_estado not in hechas:
            texto = f"{nombre} completó «{t['titulo']}»"
        elif antes_estado in hechas and t["estado"] not in hechas:
            texto = f"{nombre} reabrió «{t['titulo']}»"
        elif antes_estado == primera and t["estado"] not in hechas:
            texto = f"{nombre} empezó a trabajar en «{t['titulo']}»"
        else:
            return publicado
        publicado = _publicar_en_proyecto(t["proyecto_id"], actor_id, texto, url) or publicado
    return publicado


def tarea_eliminada(task_id: str, actor, restaurada: bool = False) -> bool:
    actor_id, nombre = _quien(actor)
    t = db.get_tarea_resumen(task_id)
    if not t:
        return False
    verbo = "restauró" if restaurada else "eliminó"
    return _publicar_en_proyecto(t["proyecto_id"], actor_id, f"{nombre} {verbo} la tarea «{t['titulo']}»",
                                 _url_tarea(task_id, t["proyecto_id"]) if restaurada else "")


def tareas_importadas(proyecto_id: str, actor, n: int, origen: str = "") -> bool:
    """Una importacion masiva (API, Excel...) publica UN resumen, no un
    mensaje por tarea: con 500 tareas el muro quedaria inservible."""
    if n <= 0:
        return False
    actor_id, nombre = _quien(actor)
    texto = f"{nombre} importó {n} tarea{'s' if n != 1 else ''}" + (f" ({origen})" if origen else "")
    return _publicar_en_proyecto(proyecto_id, actor_id, texto, f"/proyecto/{proyecto_id}/tablero/")


# ── eventos de proyecto y miembros ───────────────────────────────────────────

def proyecto_creado(proyecto_id: str, actor) -> bool:
    actor_id, nombre = _quien(actor)
    p = db.get_proyecto(proyecto_id)
    if p and p["espacio_id"]:
        return publicar_en_espacio(p["espacio_id"], actor_id, f"{nombre} creó el proyecto «{p['nombre']}»",
                                   f"/proyecto/{proyecto_id}/", proyecto_id=proyecto_id)
    return False


_ROLES = {"admin": "Admin", "editor": "Editor", "lector": "Lector"}


def miembro_anadido(espacio_id: str, actor, user_id: int, rol: str) -> bool:
    actor_id, nombre = _quien(actor)
    return publicar_en_espacio(espacio_id, actor_id,
                               f"{nombre} añadió a {_nombre_usuario(user_id)} al espacio como {_ROLES.get(rol, rol)}")


def miembro_quitado(espacio_id: str, actor, user_id: int) -> bool:
    actor_id, nombre = _quien(actor)
    return publicar_en_espacio(espacio_id, actor_id, f"{nombre} quitó a {_nombre_usuario(user_id)} del espacio")


def miembro_rol(espacio_id: str, actor, user_id: int, rol: str) -> bool:
    actor_id, nombre = _quien(actor)
    return publicar_en_espacio(espacio_id, actor_id,
                               f"{nombre} cambió el rol de {_nombre_usuario(user_id)} a {_ROLES.get(rol, rol)}")


def muros_de(user_id, es_it: bool) -> list:
    """Muros que este usuario puede ver, para la lista de /muro/: cada
    espacio con su nivel de acceso, sus proyectos, cuantos mensajes de otros
    tiene sin leer y su ultima actividad. Primero los que tienen algo sin
    leer, luego por actividad. 'propio' = es miembro o dueño (IT ve ademas
    el resto, aparte)."""
    sin_leer = db.contar_muros_sin_leer(user_id) if user_id else {}
    actividad = db.actividad_muros()
    muros = []
    for e in db.load_espacios():
        if not e["activo"]:
            continue
        nivel_propio = acceso(e, user_id, False)
        nivel = nivel_propio or (acceso(e, user_id, True) if es_it else None)
        if nivel is None:
            continue
        muros.append({
            **e, "nivel": nivel, "propio": nivel_propio is not None,
            "sin_leer": sin_leer.get(e["id"], 0), "actividad": actividad.get(e["id"], ""),
            "proyectos": db.load_proyectos_por_espacio(e["id"]),
        })
    muros.sort(key=lambda m: m["actividad"], reverse=True)          # orden estable: primero por actividad...
    muros.sort(key=lambda m: (not m["propio"], m["sin_leer"] == 0))  # ...y encima, los propios con algo sin leer
    return muros
