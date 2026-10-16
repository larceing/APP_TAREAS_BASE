# -*- coding: utf-8 -*-
"""Lo comun a todos los conectores: guardar su configuracion (con los
secretos cifrados), sincronizar (traer -> descartar lo ya importado -> crear
tareas por acciones.py, para que la campana y el muro lo vean igual que una
tarea creada a mano) y el hilo que lanza los que tienen intervalo.

La sincronizacion automatica solo corre con el entorno REAL activo: en el
de pruebas se pausa (a mano, desde Configuracion, funciona en los dos)."""
from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path

from .. import acciones, db, logging_setup
from ..nexus import cripto
from . import TIPOS, ConectorError

log = logging_setup.escritorio  # logs/escritorio.log: mismo sitio que el resto de servicios en segundo plano

_CIFRADO = "cifrado:"
TICK_SEGUNDOS = 60
LOCK_FILE = Path(__file__).resolve().parents[2] / "data" / "conectores.lock"


# ── configuracion ────────────────────────────────────────────────────────────

def _clave() -> str:
    clave = os.getenv("CONECTORES_CLAVE", "").strip() or os.getenv("SESSION_SECRET_KEY", "").strip()
    if not clave:
        raise ConectorError("define CONECTORES_CLAVE (o SESSION_SECRET_KEY) en el .env para poder guardar tokens cifrados")
    return clave


def preparar_config(tipo: str, formulario: dict, anterior: dict | None = None) -> str:
    """Del formulario al JSON que se guarda: solo los campos del tipo, los
    secretos cifrados, y un secreto vacio = conservar el que ya habia."""
    conector = TIPOS[tipo]
    anterior = anterior or {}
    guardado = {}
    for campo in conector.campos:
        valor = str(formulario.get(campo.clave, "") or "").strip()
        if campo.tipo == "si_no":
            valor = "1" if valor in ("1", "on", "true") else "0"
        if campo.tipo == "secreto":
            if not valor:
                if anterior.get(campo.clave):
                    guardado[campo.clave] = anterior[campo.clave]
                continue
            valor = _CIFRADO + cripto.cifrar(_clave(), valor)
        guardado[campo.clave] = valor
    return json.dumps(guardado, ensure_ascii=False)


def config_guardada(conector: dict) -> dict:
    try:
        return json.loads(conector["config"] or "{}")
    except ValueError:
        return {}


def config_en_claro(conector: dict) -> dict:
    config = config_guardada(conector)
    for clave, valor in list(config.items()):
        if isinstance(valor, str) and valor.startswith(_CIFRADO):
            claro = cripto.descifrar(_clave(), valor[len(_CIFRADO):])
            if claro is None:
                raise ConectorError(f"no se puede descifrar '{clave}': ¿ha cambiado CONECTORES_CLAVE/SESSION_SECRET_KEY? "
                                    "Vuelve a escribir el token.")
            config[clave] = claro
    return config


# ── sincronizar ──────────────────────────────────────────────────────────────

def _prioridad(texto: str) -> str:
    t = (texto or "").lower()
    if any(p in t for p in ("urgent", "immediate", "crit", "alt", "high", "inmediat")):
        return "Alta"
    if any(p in t for p in ("baj", "low", "none", "menor")):
        return "Baja"
    return "Normal"


def _usuario_por_origen(asignado: str, usuarios: list) -> int | None:
    a = (asignado or "").strip().lower()
    if not a:
        return None
    return next((u["id"] for u in usuarios if a in (u["username"].lower(), (u.get("email") or "").lower())), None)


def _descripcion(elemento) -> str:
    texto = (elemento.descripcion or "").strip()
    if elemento.url:
        texto = (texto + "\n\n" if texto else "") + f"Origen: {elemento.url}"
    return texto


def probar(conector: dict) -> str:
    tipo = TIPOS.get(conector["tipo"])
    if not tipo:
        raise ConectorError(f"tipo de conector desconocido: {conector['tipo']}")
    return tipo.probar(config_en_claro(conector))


def sincronizar(conector_id: str) -> dict:
    """{"ok", "nuevas", "ya_importadas", "mensaje"}; deja el resultado
    guardado en el propio conector. Nunca lanza: un fallo del origen se
    devuelve (y se guarda) como mensaje."""
    conector = db.get_conector(conector_id)
    if not conector:
        return {"ok": False, "nuevas": 0, "ya_importadas": 0, "mensaje": "no existe el conector"}
    try:
        if not conector["proyecto_id"] or not db.get_proyecto(conector["proyecto_id"]):
            raise ConectorError("no tiene proyecto destino (o se ha eliminado)")
        tipo = TIPOS.get(conector["tipo"])
        if not tipo:
            raise ConectorError(f"tipo de conector desconocido: {conector['tipo']}")
        elementos = tipo.traer(config_en_claro(conector))
        ya = db.conector_ids_importados(conector_id)
        usuarios = db.load_usuarios()
        actor = acciones.Actor(None, f"Conector · {conector['nombre']}", via="api")
        nuevas = 0
        for e in elementos:
            if e.id_externo in ya:
                continue
            resultado = acciones.crear_tarea(
                actor, conector["proyecto_id"], e.titulo, estado=conector["estado_inicial"] or None,
                prioridad=_prioridad(e.prioridad), descripcion=_descripcion(e), fecha_fin=e.fecha_fin,
                asignado_a=_usuario_por_origen(e.asignado, usuarios) or conector["asignar_a"], publicar=False,
            )
            if db.registrar_conector_elemento(conector_id, e.id_externo, resultado["id"]):
                nuevas += 1
            else:  # otro proceso se adelanto con este mismo elemento
                db.toggle_borrada_tarea(resultado["id"], True)
        if nuevas:
            acciones.importar_resumen(actor, conector["proyecto_id"], nuevas, conector["nombre"])
        mensaje = f"{nuevas} tarea(s) nueva(s), {len(elementos) - nuevas} ya importada(s)"
        db.marcar_sync_conector(conector_id, mensaje, True)
        return {"ok": True, "nuevas": nuevas, "ya_importadas": len(elementos) - nuevas, "mensaje": mensaje}
    except (ConectorError, acciones.AccionError) as e:
        mensaje = getattr(e, "mensaje", None) or str(e)
    except Exception as e:  # el origen puede devolver cualquier cosa: que no tumbe el hilo
        log.exception("conector %s: error inesperado", conector_id)
        mensaje = f"error inesperado: {e}"
    db.marcar_sync_conector(conector_id, mensaje, False)
    return {"ok": False, "nuevas": 0, "ya_importadas": 0, "mensaje": mensaje}


def nuevo_id() -> str:
    return str(uuid.uuid4())[:8]


# ── hilo de fondo ────────────────────────────────────────────────────────────

_parar = threading.Event()
_hilo: threading.Thread | None = None
_lock_fh = None


def _coger_bloqueo() -> bool:
    """Un solo proceso sincroniza (mismo criterio que escritorio_servicios)."""
    global _lock_fh
    try:
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        _lock_fh = open(LOCK_FILE, "a+")
        try:
            import msvcrt
            msvcrt.locking(_lock_fh.fileno(), msvcrt.LK_NBLCK, 1)
        except ImportError:
            import fcntl
            fcntl.flock(_lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        if _lock_fh:
            _lock_fh.close()
            _lock_fh = None
        return False


def _bucle() -> None:
    while not _parar.is_set():
        try:
            if db.entorno_actual() == "real":
                for c in db.conectores_pendientes():
                    log.info("conector %s (%s): %s", c["nombre"], c["conector_id"], sincronizar(c["conector_id"])["mensaje"])
        except Exception:
            log.exception("error en el bucle de conectores")
        _parar.wait(TICK_SEGUNDOS)


def arrancar() -> bool:
    global _hilo
    if os.getenv("APP_TAREAS_SIN_ESCRITORIO") == "1" or not _coger_bloqueo():
        return False
    _parar.clear()
    _hilo = threading.Thread(target=_bucle, name="conectores", daemon=True)
    _hilo.start()
    log.info("sincronización automática de conectores arrancada")
    return True


def parar() -> None:
    global _hilo, _lock_fh
    _parar.set()
    if _hilo:
        _hilo.join(timeout=5)
        _hilo = None
    if _lock_fh:
        _lock_fh.close()
        _lock_fh = None
