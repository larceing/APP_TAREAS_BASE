# -*- coding: utf-8 -*-
"""Configuracion -> Conectores (modulo opcional MODULO_CONECTORES): alta,
edicion, prueba y sincronizacion a mano de los conectores de entrada. El
panel lo pinta configuracion.html (tipo=conectores); aqui solo los POST.
Solo IT, como el resto de Configuracion."""
from fastapi import APIRouter, Depends
from fastapi.requests import Request
from fastapi.responses import RedirectResponse

from .. import auth, db
from ..conectores import TIPOS, ConectorError, motor
from ..flash import flash

router = APIRouter(prefix="/configuracion/conectores", tags=["conectores"], dependencies=[Depends(auth.requiere_it)])


def _volver(editar: str = "") -> RedirectResponse:
    return RedirectResponse(url="/configuracion/?tipo=conectores" + (f"&editar={editar}" if editar else ""), status_code=303)


@router.post("/guardar/")
async def guardar(request: Request, usuario: str = Depends(auth.requiere_login)):
    form = await request.form()
    tipo = form.get("tipo", "")
    if tipo not in TIPOS:
        flash(request, "error", "Tipo de conector desconocido.")
        return _volver()
    conector_id = form.get("conector_id") or motor.nuevo_id()
    anterior = db.get_conector(conector_id)
    nombre = (form.get("nombre") or "").strip()[:150] or TIPOS[tipo].nombre
    try:
        config = motor.preparar_config(tipo, {k[4:]: v for k, v in form.items() if k.startswith("cfg_")},
                                       motor.config_guardada(anterior) if anterior else None)
        TIPOS[tipo].validar(motor.config_en_claro({"config": config}))
        intervalo = max(0, min(1440, int(form.get("intervalo_min") or 0)))
    except ConectorError as e:
        flash(request, "error", str(e))
        return _volver(conector_id if anterior else "")
    except ValueError:
        flash(request, "error", "El intervalo tiene que ser un número de minutos.")
        return _volver(conector_id if anterior else "")
    db.guardar_conector(conector_id, nombre, tipo, config, form.get("proyecto_id", ""), (form.get("estado_inicial") or "").strip(),
                        int(form["asignar_a"]) if (form.get("asignar_a") or "").isdigit() else None, intervalo)
    flash(request, "success", f"Conector '{nombre}' guardado. Pulsa \"Probar\" para comprobar la conexión.")
    return _volver()


@router.post("/{conector_id}/probar/")
def probar(request: Request, conector_id: str, usuario: str = Depends(auth.requiere_login)):
    conector = db.get_conector(conector_id)
    if conector:
        try:
            flash(request, "success", f"{conector['nombre']}: {motor.probar(conector)}")
        except ConectorError as e:
            flash(request, "error", f"{conector['nombre']}: {e}")
    return _volver()


@router.post("/{conector_id}/sincronizar/")
def sincronizar(request: Request, conector_id: str, usuario: str = Depends(auth.requiere_login)):
    resultado = motor.sincronizar(conector_id)
    flash(request, "success" if resultado["ok"] else "error", resultado["mensaje"])
    return _volver()


@router.post("/{conector_id}/activo/")
def activar(request: Request, conector_id: str, usuario: str = Depends(auth.requiere_login)):
    db.toggle_conector(conector_id)
    return _volver()


@router.post("/{conector_id}/eliminar/")
def eliminar(request: Request, conector_id: str, usuario: str = Depends(auth.requiere_login)):
    db.eliminar_conector(conector_id)
    flash(request, "success", "Conector eliminado. Las tareas que ya creó se quedan donde estaban.")
    return _volver()
