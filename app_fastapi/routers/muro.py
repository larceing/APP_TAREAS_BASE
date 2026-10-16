# -*- coding: utf-8 -*-
"""Muro de actividad (ver muro.py para que se publica solo y quien lo ve).
Un solo sitio para la conversacion de la app -- no hay chats aparte:

- /muro/                pagina central: lista de mis muros (espacios y sus
                        proyectos, con contadores) + la conversacion elegida
                        (?espacio=<id>[&proyecto=<id>]). Aqui tambien el
                        "Aviso" de IT a varios espacios a la vez.
- /proyecto/<id>/muro/  pestana "Muro" dentro de un proyecto (mismo muro,
                        filtrado a ese proyecto).
- /espacio/<id>/muro/   solo API (+ redirige a /muro/?espacio=<id>).

Las rutas de la conversacion (mensajes, escribir/, mensaje/<id>/borrar/,
deshacer/, silenciar/) son las mismas bajo /espacio/<id>/muro/ y
/proyecto/<id>/muro/; las usa static/js/sala_chat.js.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.requests import Request
from fastapi.responses import JSONResponse, RedirectResponse

from .. import auth, db, muro
from ..flash import flash
from ..templating import templates

router = APIRouter(prefix="/espacio/{espacio_id}/muro", tags=["muro"])
router_proyecto = APIRouter(prefix="/proyecto/{proyecto_id}/muro", tags=["muro"])
router_central = APIRouter(prefix="/muro", tags=["muro"])

CONTENIDO_MAX = 4000

# Plantillas rapidas del Aviso (las mismas 4 de CS Manager, FUNCIONAL.md 6.3);
# al pulsar una se marcan todos los espacios como destino.
PLANTILLAS_AVISO = [
    ("⚠️ Parada", "⚠️ El sistema se va a PARAR en breve. Por favor, guarda tu trabajo y cierra sesión."),
    ("🔄 Reinicio", "🔄 El sistema se va a REINICIAR en breve. Por favor, guarda tu trabajo. Volverá a estar disponible en unos minutos."),
    ("🔧 Mantenimiento", "🔧 Mantenimiento programado. El sistema no estará disponible durante un periodo breve. Os avisaremos cuando esté listo."),
    ("✅ Disponible", "✅ El sistema ya está disponible. Podéis continuar con vuestro trabajo con normalidad."),
]
DURACIONES_AVISO = {"1": 1, "3": 3, "7": 7, "0": None}  # dias; 0 = sin caducidad


def _es_it(request: Request) -> bool:
    return bool(request.session.get("es_it"))


def _contexto(request: Request, espacio_id: str, usuario: str):
    espacio = db.get_espacio(espacio_id)
    user_id = db.get_user_id(usuario)
    nivel = muro.acceso(espacio, user_id, _es_it(request))
    return espacio, user_id, nivel


def _exigir(request: Request, espacio_id: str, usuario: str, nivel_minimo: str):
    espacio, user_id, nivel = _contexto(request, espacio_id, usuario)
    if nivel is None or (nivel_minimo == muro.ESCRIBIR and nivel != muro.ESCRIBIR):
        raise HTTPException(status_code=403, detail="No tienes acceso a este muro.")
    return espacio, user_id, nivel


def _proyecto_con_muro(proyecto_id: str) -> dict:
    proyecto = db.get_proyecto(proyecto_id)
    if not proyecto or not proyecto["espacio_id"]:
        raise HTTPException(status_code=404, detail="Este proyecto no está en ningún espacio, así que no tiene muro.")
    return proyecto


def _mensajes(espacio_id: str, user_id: int, proyecto_id: str = None) -> JSONResponse:
    sala_id = db.get_or_create_sala_muro(espacio_id)
    lista = db.load_chat_mensajes(sala_id, user_id, proyecto_id=proyecto_id)
    if lista:
        db.marcar_chat_leido(sala_id, user_id, lista[-1]["id"], proyecto_id=proyecto_id)
    return JSONResponse({"mensajes": lista})


async def _escribir(request: Request, espacio_id: str, user_id: int, usuario: str, proyecto_fijo: str = None) -> JSONResponse:
    datos = await request.json()
    contenido = str(datos.get("contenido", "")).strip()[:CONTENIDO_MAX]
    if not contenido:
        return JSONResponse({"ok": False, "error": "El mensaje está vacío."}, status_code=400)
    proyecto_id = proyecto_fijo
    if proyecto_id is None and datos.get("proyecto_id"):
        # desde el muro del espacio se puede elegir un proyecto, pero solo de ESTE espacio
        validos = {p["id"] for p in db.load_proyectos_por_espacio(espacio_id)}
        proyecto_id = datos["proyecto_id"] if datos["proyecto_id"] in validos else None
    nombre = next((u["nombre_completo"] for u in db.load_usuarios() if u["id"] == user_id), usuario)
    mensaje_id = muro.escribir(espacio_id, user_id, nombre, contenido, proyecto_id=proyecto_id)
    return JSONResponse({"ok": True, "id": mensaje_id})


def _mensaje_del_muro(espacio_id: str, mensaje_id: int) -> None:
    m = db.get_chat_mensaje(mensaje_id)
    if not m or m["sala_id"] != db.get_or_create_sala_muro(espacio_id):
        raise HTTPException(status_code=404)


def _silenciar(espacio_id: str, user_id: int) -> JSONResponse:
    sala_id = db.get_or_create_sala_muro(espacio_id)
    silenciada = not db.get_chat_lectura(sala_id, user_id)["silenciada"]
    db.set_chat_silenciada(sala_id, user_id, silenciada)
    return JSONResponse({"ok": True, "silenciada": silenciada})


# ── muro del espacio ─────────────────────────────────────────────────────────

@router.get("/")
def ver_muro(espacio_id: str, usuario: str = Depends(auth.requiere_login)):
    """El muro de un espacio se ve en la pagina central."""
    return RedirectResponse(url=muro.url_muro(espacio_id), status_code=303)


@router.get("/mensajes")
def mensajes(request: Request, espacio_id: str, usuario: str = Depends(auth.requiere_login)):
    _, user_id, _ = _exigir(request, espacio_id, usuario, muro.LEER)
    return _mensajes(espacio_id, user_id)


@router.post("/escribir/")
async def escribir(request: Request, espacio_id: str, usuario: str = Depends(auth.requiere_login)):
    _, user_id, _ = _exigir(request, espacio_id, usuario, muro.ESCRIBIR)
    return await _escribir(request, espacio_id, user_id, usuario)


@router.post("/mensaje/{mensaje_id}/borrar/")
def borrar(request: Request, espacio_id: str, mensaje_id: int, usuario: str = Depends(auth.requiere_login)):
    _, user_id, _ = _exigir(request, espacio_id, usuario, muro.LEER)
    _mensaje_del_muro(espacio_id, mensaje_id)
    ok = db.borrar_chat_mensaje(mensaje_id, user_id)
    return JSONResponse({"ok": ok}, status_code=200 if ok else 403)


@router.post("/mensaje/{mensaje_id}/deshacer/")
def deshacer(request: Request, espacio_id: str, mensaje_id: int, usuario: str = Depends(auth.requiere_login)):
    _, user_id, _ = _exigir(request, espacio_id, usuario, muro.LEER)
    _mensaje_del_muro(espacio_id, mensaje_id)
    ok = db.deshacer_borrado_chat_mensaje(mensaje_id, user_id)
    return JSONResponse({"ok": ok}, status_code=200 if ok else 409)


@router.post("/silenciar/")
def silenciar(request: Request, espacio_id: str, usuario: str = Depends(auth.requiere_login)):
    _, user_id, _ = _exigir(request, espacio_id, usuario, muro.LEER)
    return _silenciar(espacio_id, user_id)


# ── pestana "Muro" de un proyecto (mismo muro, filtrado) ─────────────────────

@router_proyecto.get("/")
def ver_muro_proyecto(request: Request, proyecto_id: str, usuario: str = Depends(auth.requiere_login)):
    proyecto = db.get_proyecto(proyecto_id)
    if not proyecto:
        return RedirectResponse(url="/", status_code=303)
    if not proyecto["espacio_id"]:
        flash(request, "error", "Este proyecto no está en ningún espacio, así que no tiene muro. Asígnale un espacio al editarlo.")
        return RedirectResponse(url=f"/proyecto/{proyecto_id}/", status_code=303)
    espacio, user_id, nivel = _contexto(request, proyecto["espacio_id"], usuario)
    if nivel is None:
        flash(request, "error", "No eres miembro del espacio de este proyecto, así que no puedes ver su muro.")
        return RedirectResponse(url=f"/proyecto/{proyecto_id}/", status_code=303)
    sala_id = db.get_or_create_sala_muro(espacio["id"])
    return templates.TemplateResponse(request, "muro_proyecto.html", {
        "usuario": usuario, "activo": "muro_proyecto", "proyecto": proyecto, "proyecto_actual": proyecto_id,
        "espacio": espacio, "user_id": user_id, "puede_escribir": nivel == muro.ESCRIBIR,
        "silenciada": db.get_chat_lectura(sala_id, user_id)["silenciada"],
        "deshacer_segundos": db.DESHACER_SEGUNDOS,
    })


@router_proyecto.get("/mensajes")
def mensajes_proyecto(request: Request, proyecto_id: str, usuario: str = Depends(auth.requiere_login)):
    proyecto = _proyecto_con_muro(proyecto_id)
    _, user_id, _ = _exigir(request, proyecto["espacio_id"], usuario, muro.LEER)
    return _mensajes(proyecto["espacio_id"], user_id, proyecto_id=proyecto_id)


@router_proyecto.post("/escribir/")
async def escribir_proyecto(request: Request, proyecto_id: str, usuario: str = Depends(auth.requiere_login)):
    proyecto = _proyecto_con_muro(proyecto_id)
    _, user_id, _ = _exigir(request, proyecto["espacio_id"], usuario, muro.ESCRIBIR)
    return await _escribir(request, proyecto["espacio_id"], user_id, usuario, proyecto_fijo=proyecto_id)


@router_proyecto.post("/mensaje/{mensaje_id}/borrar/")
def borrar_proyecto(request: Request, proyecto_id: str, mensaje_id: int, usuario: str = Depends(auth.requiere_login)):
    proyecto = _proyecto_con_muro(proyecto_id)
    _, user_id, _ = _exigir(request, proyecto["espacio_id"], usuario, muro.LEER)
    _mensaje_del_muro(proyecto["espacio_id"], mensaje_id)
    ok = db.borrar_chat_mensaje(mensaje_id, user_id)
    return JSONResponse({"ok": ok}, status_code=200 if ok else 403)


@router_proyecto.post("/mensaje/{mensaje_id}/deshacer/")
def deshacer_proyecto(request: Request, proyecto_id: str, mensaje_id: int, usuario: str = Depends(auth.requiere_login)):
    proyecto = _proyecto_con_muro(proyecto_id)
    _, user_id, _ = _exigir(request, proyecto["espacio_id"], usuario, muro.LEER)
    _mensaje_del_muro(proyecto["espacio_id"], mensaje_id)
    ok = db.deshacer_borrado_chat_mensaje(mensaje_id, user_id)
    return JSONResponse({"ok": ok}, status_code=200 if ok else 409)


@router_proyecto.post("/silenciar/")
def silenciar_proyecto(request: Request, proyecto_id: str, usuario: str = Depends(auth.requiere_login)):
    """Silencia el muro del ESPACIO entero (es uno solo): no hay silencio por proyecto."""
    proyecto = _proyecto_con_muro(proyecto_id)
    _, user_id, _ = _exigir(request, proyecto["espacio_id"], usuario, muro.LEER)
    return _silenciar(proyecto["espacio_id"], user_id)


# ── pagina central /muro/ + Aviso de IT ─────────────────────────────────────

@router_central.get("/")
def muro_central(request: Request, espacio: str = "", proyecto: str = "", usuario: str = Depends(auth.requiere_login)):
    user_id = db.get_user_id(usuario)
    es_it = _es_it(request)
    muros = muro.muros_de(user_id, es_it)
    actual = next((m for m in muros if m["id"] == espacio), None) if espacio else (muros[0] if muros else None)
    if espacio and not actual:
        flash(request, "error", "Ese espacio no existe o no eres miembro, así que no puedes ver su muro.")
        return RedirectResponse(url="/muro/", status_code=303)
    proyecto_actual = None
    if actual and proyecto:
        proyecto_actual = next((p for p in actual["proyectos"] if p["id"] == proyecto), None)
    silenciada = False
    if actual:
        silenciada = db.get_chat_lectura(db.get_or_create_sala_muro(actual["id"]), user_id)["silenciada"]
    return templates.TemplateResponse(request, "muro.html", {
        "usuario": usuario, "activo": "muro", "user_id": user_id, "muros": muros, "actual": actual,
        "proyecto_actual": proyecto_actual, "silenciada": silenciada,
        "puede_escribir": bool(actual) and actual["nivel"] == muro.ESCRIBIR,
        "miembros": db.load_miembros_espacio(actual["id"]) if actual and not actual["es_personal"] else [],
        "deshacer_segundos": db.DESHACER_SEGUNDOS,
        "es_it_usuario": es_it, "plantillas": PLANTILLAS_AVISO,
        "espacios_aviso": [e for e in db.load_espacios() if e["activo"]] if es_it else [],
    })


@router_central.post("/aviso/")
async def aviso(request: Request, usuario: str = Depends(auth.requiere_login)):
    """Aviso de IT (antes "Difundir"): mensaje destacado en los muros de los
    espacios elegidos, con caducidad opcional, y una sola notificacion por
    persona aunque este en varios de esos espacios."""
    if not _es_it(request):
        raise HTTPException(status_code=403, detail="Solo el equipo IT puede publicar avisos.")
    user_id = db.get_user_id(usuario)
    form = await request.form()
    texto = str(form.get("texto", "")).strip()[:CONTENIDO_MAX]
    dias = DURACIONES_AVISO.get(str(form.get("duracion", "1")), 1)
    validos = {e["id"] for e in db.load_espacios() if e["activo"]}
    destinos = [e for e in form.getlist("espacios") if e in validos]
    volver = str(form.get("volver", "/muro/"))
    volver = volver if volver.startswith("/muro/") else "/muro/"
    if not texto or not destinos:
        flash(request, "error", "Escribe el aviso y elige al menos un espacio.")
        return RedirectResponse(url=volver, status_code=303)
    caduca = (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S") if dias else None
    avisados = {}
    for espacio_id in destinos:
        db.crear_aviso_difundido(db.get_or_create_sala_muro(espacio_id), user_id, texto, caduca)
        for uid in db.destinatarios_muro(espacio_id):
            avisados.setdefault(uid, muro.url_muro(espacio_id))  # el enlace, al primero de sus espacios
    avisados.pop(user_id, None)
    resumen = " ".join(texto.split())
    resumen = resumen if len(resumen) <= 90 else resumen[:87] + "..."
    for uid, url in avisados.items():
        db.crear_notificacion(uid, "aviso", f"Aviso: {resumen}", url)
    flash(request, "success", f"Aviso publicado en {len(destinos)} espacio(s); {len(avisados)} persona(s) avisada(s).")
    return RedirectResponse(url=volver, status_code=303)


@router_central.post("/aviso/{mensaje_id}/borrar/")
def borrar_aviso(request: Request, mensaje_id: int, usuario: str = Depends(auth.requiere_login)):
    if not _es_it(request):
        raise HTTPException(status_code=403, detail="Solo el equipo IT puede quitar un aviso.")
    ok = db.borrar_aviso_difundido(mensaje_id)
    return JSONResponse({"ok": ok}, status_code=200 if ok else 404)
