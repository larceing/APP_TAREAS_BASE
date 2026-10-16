# -*- coding: utf-8 -*-
"""Buzon -- notas entre personas, fase 1 de mensajeria (inspirada en las
"Notas" de CS Manager, otra app interna).

- Enviar una nota a otra persona o a uno mismo (nota personal), con fecha de
  vencimiento opcional y un aviso previo (X horas/dias/semanas antes).
- Panel de arriba: notas propias. Panel de abajo: recibidas / enviadas, con
  filtro de fechas y de persona.
- Editar: solo quien la envio. Eliminar: solo quien la envio.
- Marcar como leida (una o todas): solo quien la recibio.
- Reenviar: crea una nota NUEVA (la original no cambia); si la original ya
  genero tareas, se puede desvincularlas.
- Convertir en tarea: proyecto + columna a elegir entre los proyectos donde
  se pueden crear tareas; a quien se asigna, igual criterio que CS Manager:
  IT o Admin del espacio destino -> a cualquiera; si no -> a uno mismo.

Mismo patron de formularios normales (POST + redirect) que Notas.
"""
from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.requests import Request
from fastapi.responses import RedirectResponse

from .. import acciones, auth, db, notificar
from ..flash import flash
from ..templating import templates

router = APIRouter(prefix="/buzon", tags=["buzon"])

CONTENIDO_MAX = 4000


def _user_id(usuario: str) -> int:
    user_id = db.get_user_id(usuario)
    if not user_id:
        raise HTTPException(status_code=403, detail="usuario sin ficha en auth_user")
    return user_id


def _redirect(request: Request, ancla: str = "") -> RedirectResponse:
    """Vuelve al buzon conservando los filtros que hubiera (llegan en el
    campo oculto 'volver' de cada formulario)."""
    volver = request.query_params.get("volver", "")
    destino = volver if volver.startswith("/buzon/") else "/buzon/"
    return RedirectResponse(url=destino + (f"#{ancla}" if ancla else ""), status_code=303)


def _nota_visible(nota_id: int, user_id: int) -> dict:
    nota = db.get_buzon_nota(nota_id)
    if not nota or user_id not in (nota["de_user_id"], nota["para_user_id"]):
        raise HTTPException(status_code=404)
    return nota


def _aviso(cantidad: str, unidad: str) -> tuple[int, str]:
    try:
        n = max(0, min(999, int(cantidad)))
    except ValueError:
        n = 1
    return n, unidad if unidad in db.AVISO_UNIDADES else "dias"


@router.get("/")
def ver_buzon(request: Request, vista: str = "recibidas", desde: str = "", hasta: str = "", persona: str = "",
              p_desde: str = "", p_hasta: str = "", usuario: str = Depends(auth.requiere_login)):
    user_id = _user_id(usuario)
    vista = vista if vista in ("recibidas", "enviadas") else "recibidas"
    persona_id = int(persona) if persona.isdigit() else None
    usuarios = db.load_usuarios()
    proyectos = db.load_proyectos_para_crear_tareas(user_id)
    columnas = {p["id"]: [c["nombre"] for c in db.load_board_columns(p["id"])]
                for p in proyectos}
    es_it = bool(request.session.get("es_it"))
    return templates.TemplateResponse(request, "buzon.html", {
        "usuario": usuario, "activo": "buzon", "user_id": user_id, "hoy": date.today().isoformat(),
        "propias": db.load_buzon(user_id, "propias", p_desde, p_hasta),
        "lista": db.load_buzon(user_id, vista, desde, hasta, persona_id),
        "vista": vista, "desde": desde, "hasta": hasta, "persona": persona_id, "p_desde": p_desde, "p_hasta": p_hasta,
        "usuarios": usuarios, "sin_leer": db.contar_buzon_sin_leer(user_id),
        "proyectos": proyectos, "columnas": columnas,
        # a quien puede asignar la tarea en cada proyecto: todos (IT o Admin del espacio) o solo a si mismo
        "asigna_a_cualquiera": {p["id"]: es_it or p["rol"] == "admin" for p in proyectos},
        "volver": str(request.url.path) + ("?" + request.url.query if request.url.query else ""),
        "aviso_unidades": list(db.AVISO_UNIDADES),
    })


@router.post("/enviar/")
def enviar(request: Request, para_user_id: str = Form(""), contenido: str = Form(""), vence_en: str = Form(""),
           aviso_cantidad: str = Form("1"), aviso_unidad: str = Form("dias"), usuario: str = Depends(auth.requiere_login)):
    user_id = _user_id(usuario)
    contenido = contenido.strip()[:CONTENIDO_MAX]
    para = int(para_user_id) if para_user_id.isdigit() else user_id
    if not contenido or para not in {u["id"] for u in db.load_usuarios()}:
        flash(request, "error", "Falta el contenido o el destinatario no existe.")
        return _redirect(request)
    cantidad, unidad = _aviso(aviso_cantidad, aviso_unidad)
    nota_id = db.crear_buzon_nota(user_id, para, contenido, vence_en.strip(), cantidad, unidad)
    if para != user_id:
        notificar.nota_recibida(para, usuario, contenido, nota_id)
    flash(request, "success", "Nota guardada." if para == user_id else "Nota enviada.")
    return _redirect(request, f"nota-{nota_id}")


@router.post("/{nota_id}/editar/")
def editar(request: Request, nota_id: int, contenido: str = Form(""), vence_en: str = Form(""),
           aviso_cantidad: str = Form("1"), aviso_unidad: str = Form("dias"), usuario: str = Depends(auth.requiere_login)):
    user_id = _user_id(usuario)
    nota = _nota_visible(nota_id, user_id)
    if nota["de_user_id"] != user_id:
        raise HTTPException(status_code=403, detail="solo quien envió la nota puede editarla")
    contenido = contenido.strip()[:CONTENIDO_MAX]
    if contenido:
        cantidad, unidad = _aviso(aviso_cantidad, aviso_unidad)
        db.editar_buzon_nota(nota_id, contenido, vence_en.strip(), cantidad, unidad)
        flash(request, "success", "Nota actualizada.")
    return _redirect(request, f"nota-{nota_id}")


@router.post("/{nota_id}/leida/")
def marcar_leida(request: Request, nota_id: int, usuario: str = Depends(auth.requiere_login)):
    user_id = _user_id(usuario)
    nota = _nota_visible(nota_id, user_id)
    if nota["para_user_id"] == user_id:
        db.marcar_buzon_leida(nota_id, user_id, not nota["leida"])
    return _redirect(request, f"nota-{nota_id}")


@router.post("/leer-todas/")
def leer_todas(request: Request, usuario: str = Depends(auth.requiere_login)):
    n = db.marcar_buzon_todas_leidas(_user_id(usuario))
    flash(request, "success", f"{n} nota(s) marcada(s) como leída(s).")
    return _redirect(request)


@router.post("/{nota_id}/eliminar/")
def eliminar(request: Request, nota_id: int, usuario: str = Depends(auth.requiere_login)):
    user_id = _user_id(usuario)
    nota = _nota_visible(nota_id, user_id)
    if nota["de_user_id"] != user_id:
        raise HTTPException(status_code=403, detail="solo quien envió la nota puede eliminarla")
    db.eliminar_buzon_nota(nota_id)
    flash(request, "success", "Nota eliminada.")
    return _redirect(request)


@router.post("/{nota_id}/reenviar/")
def reenviar(request: Request, nota_id: int, para_user_id: str = Form(""), contenido: str = Form(""),
             vence_en: str = Form(""), aviso_cantidad: str = Form("1"), aviso_unidad: str = Form("dias"),
             desvincular: str = Form(""), usuario: str = Depends(auth.requiere_login)):
    user_id = _user_id(usuario)
    _nota_visible(nota_id, user_id)
    contenido = contenido.strip()[:CONTENIDO_MAX]
    para = int(para_user_id) if para_user_id.isdigit() else None
    if not contenido or para not in {u["id"] for u in db.load_usuarios()}:
        flash(request, "error", "Falta el contenido o el destinatario no existe.")
        return _redirect(request)
    cantidad, unidad = _aviso(aviso_cantidad, aviso_unidad)
    nueva_id = db.crear_buzon_nota(user_id, para, contenido, vence_en.strip(), cantidad, unidad, reenviada_de=nota_id)
    if desvincular:
        db.desvincular_tareas_de_nota(nota_id)
    if para != user_id:
        notificar.nota_recibida(para, usuario, contenido, nueva_id, reenviada=True)
    flash(request, "success", "Nota reenviada.")
    return _redirect(request, f"nota-{nueva_id}")


@router.post("/{nota_id}/a-tarea/")
def convertir_en_tarea(request: Request, nota_id: int, proyecto_id: str = Form(""), estado: str = Form(""),
                       titulo: str = Form(""), descripcion: str = Form(""), asignado_a: str = Form(""),
                       usuario: str = Depends(auth.requiere_login)):
    user_id = _user_id(usuario)
    _nota_visible(nota_id, user_id)
    proyecto = next((p for p in db.load_proyectos_para_crear_tareas(user_id) if p["id"] == proyecto_id), None)
    titulo = titulo.strip()[:200]
    if not proyecto or not titulo:
        flash(request, "error", "Elige un proyecto donde puedas crear tareas y escribe un título.")
        return _redirect(request, f"nota-{nota_id}")
    # mismo criterio que CS Manager: IT o Admin del espacio destino asignan a
    # quien quieran; el resto se la asigna siempre a si mismo, aunque el
    # formulario mandara otra cosa
    puede_asignar = bool(request.session.get("es_it")) or proyecto["rol"] == "admin"
    asignado = int(asignado_a) if (puede_asignar and asignado_a.isdigit()) else user_id
    tarea_id = acciones.crear_tarea(acciones.Actor.web(request, usuario), proyecto_id, titulo, estado=estado,
                                    descripcion=descripcion, asignado_a=asignado)["id"]
    db.vincular_nota_tarea(nota_id, tarea_id)
    flash(request, "success", f"Tarea creada en {proyecto['nombre']}.")
    return RedirectResponse(url=f"/proyecto/{proyecto_id}/tablero/?{urlencode({'abrir_tarea': tarea_id})}", status_code=303)
