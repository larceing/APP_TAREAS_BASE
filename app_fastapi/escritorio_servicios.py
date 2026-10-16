# -*- coding: utf-8 -*-
"""Servicios de escritorio que corren DENTRO de la app (hilos en segundo
plano arrancados desde main.py::lifespan), en vez de como procesos sueltos:

- Recordatorio ergonomico -- antes APP_RECORDATORIO (proyecto aparte, lista
  de mensajes en messages.txt). Ahora los mensajes viven en la tabla
  recordatorio_mensajes y el resto (intervalo, horario, icono, sonido...) en
  ajustes_app con prefijo 'recordatorio.'.
- Vigilante de Mantis -- antes scripts/mantis_watcher.py (proceso aparte).
  Misma logica (aviso una sola vez por incidencia, fichero de ids ya avisados,
  clasificacion de origen para el SLA), ahora configurable: intervalo,
  formato del texto, icono por empresa, horario... (prefijo 'vigilante.';
  la pausa sigue en 'mantis.watcher_pausado', la misma clave de siempre).
- Vigia de carpeta -- vigila una carpeta cualquiera (p. ej. la cola de una
  integracion por ficheros): archivo nuevo en
  Fallidos, archivo atascado en la raiz/temp, carpeta inaccesible -- y avisa
  una sola vez de cada cosa (y de cuando se resuelve) con una nota del Buzon
  + campana (tipo 'vigia') + toast opcional. Prefijo 'vigia.'.

Todo se configura en Configuracion -> Recordatorio / Vigilante de Mantis y
se relee de la BD en cada vuelta del bucle: los cambios se aplican sin
reiniciar nada.

Siempre trabajan sobre la BD REAL (db.connect(real=True)), da igual el
toggle real/test de la web -- igual que hacia el watcher antiguo: un aviso de
escritorio solo tiene sentido para cosas de verdad. USAR_BD_REAL existe solo
para que los tests puedan dejarlo en False y quedarse en test_app_tareas.

Una sola instancia: si se arrancan dos procesos de la app a la vez (p. ej.
uno de pruebas en otro puerto), solo el primero que coge el fichero de
bloqueo lanza avisos -- el resto sirve la web igual, sin duplicar toasts.
Para desactivarlos del todo en un proceso: APP_TAREAS_SIN_ESCRITORIO=1.
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from . import config as config_app
from . import db, logging_setup, mantis_client

log = logging_setup.escritorio  # logs/escritorio.log

USAR_BD_REAL = True

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ESTADO_VIGILANTE = DATA_DIR / "mantis_watcher_state.json"  # mismo fichero que el watcher antiguo: no reavisa lo ya visto
ESTADO_VIGIA = DATA_DIR / "vigia_carpeta_estado.json"  # que archivos ya se han avisado
LOCK_FILE = DATA_DIR / "escritorio_servicios.lock"
TICK_SEGUNDOS = 15

SONIDOS = {
    "default": "Predeterminado", "reminder": "Recordatorio", "mail": "Correo",
    "sms": "Mensaje", "im": "Mensajería", "silent": "Sin sonido",
}
DIAS = [(1, "L"), (2, "M"), (3, "X"), (4, "J"), (5, "V"), (6, "S"), (7, "D")]

DEFAULTS = {
    "recordatorio": {
        "activo": "1", "intervalo_min": "15", "app_id": "Bienestar Ergonómico",
        "titulo": "Recordatorio", "duracion": "short", "sonido": "default",
        "orden": "aleatorio", "solo_horario": "", "hora_inicio": "08:00", "hora_fin": "18:00",
        "dias": "1,2,3,4,5", "saltar_festivos": "1", "icono": "recordatorio.png",
    },
    "vigilante": {
        "intervalo_min": "5", "app_id": "Vigilante de Mantis",
        "titulo": "Nueva incidencia de Mantis", "formato": "#{id} · {proyecto}\n{resumen}",
        "duracion": "long", "sonido": "default", "abrir_al_pulsar": "1",
        "solo_horario": "", "hora_inicio": "07:00", "hora_fin": "20:00", "dias": "1,2,3,4,5",
        "icono_pool": "vigilante_pool.png", "icono_defecto": "",
    },
    "vigia": {
        "activo": "1", "intervalo_min": "10", "app_id": "Vigía de carpeta", "titulo": "Vigía de carpeta",
        "duracion": "long", "sonido": "default", "solo_horario": "", "hora_inicio": "07:00",
        "hora_fin": "20:00", "dias": "1,2,3,4,5", "icono": "", "toast": "1", "destinatario": "",
        "carpeta": "", "carpetas_entrada": ".,temp",
        "carpeta_fallidos": "Fallidos", "minutos_atasco": "30",
    },
}
# variables que se pueden usar en el formato del Vigilante (se muestran en Configuracion)
VARIABLES_VIGILANTE = ["id", "resumen", "proyecto", "empresa", "categoria", "prioridad", "estado",
                       "reporta", "asignada_a", "url"]
VARIABLES_RECORDATORIO = ["categoria", "hora", "fecha"]
VARIABLES_VIGIA = ["resumen", "hora", "fecha"]


def _real() -> bool:
    return USAR_BD_REAL


def media_dir() -> Path:
    d = db.media_dir() / "escritorio"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ruta_icono(nombre: str) -> Path | None:
    if not nombre:
        return None
    ruta = media_dir() / Path(nombre).name  # solo el nombre: nunca rutas fuera de media/escritorio
    return ruta if ruta.exists() else None


# ── configuracion (ajustes_app) ──────────────────────────────────────────────

def config(seccion: str) -> dict:
    cfg = {}
    for clave, defecto in DEFAULTS[seccion].items():
        cfg[clave] = db.get_ajuste(f"{seccion}.{clave}", defecto, real=_real())
    if seccion == "vigilante":
        cfg["activo"] = "" if db.get_ajuste("mantis.watcher_pausado", "", real=_real()) == "1" else "1"
    return cfg


def guardar_config(seccion: str, valores: dict) -> None:
    for clave, valor in valores.items():
        if clave in DEFAULTS[seccion]:
            db.set_ajuste(f"{seccion}.{clave}", str(valor), real=_real())


def set_activo(seccion: str, activo: bool) -> None:
    if seccion == "vigilante":
        db.set_ajuste("mantis.watcher_pausado", "" if activo else "1", real=_real())
    else:
        db.set_ajuste(f"{seccion}.activo", "1" if activo else "", real=_real())


def estado(seccion: str) -> dict:
    return {
        "ultima": db.get_ajuste(f"{seccion}.estado_ultima", "", real=_real()),
        "resultado": db.get_ajuste(f"{seccion}.estado_resultado", "", real=_real()),
    }


def _guardar_estado(seccion: str, resultado: str) -> None:
    db.set_ajuste(f"{seccion}.estado_ultima", datetime.now().strftime("%d/%m/%Y %H:%M"), real=_real())
    db.set_ajuste(f"{seccion}.estado_resultado", resultado[:250], real=_real())


def en_horario(cfg: dict, ahora: datetime | None = None) -> bool:
    """Solo si cfg['solo_horario'] esta marcado: dia de la semana dentro de
    cfg['dias'] y hora entre hora_inicio y hora_fin (ambas HH:MM)."""
    if cfg.get("solo_horario") != "1":
        return True
    ahora = ahora or datetime.now()
    dias = {d.strip() for d in (cfg.get("dias") or "").split(",") if d.strip()}
    if str(ahora.isoweekday()) not in dias:
        return False
    hora = ahora.strftime("%H:%M")
    return (cfg.get("hora_inicio") or "00:00") <= hora < (cfg.get("hora_fin") or "23:59")


class _SafeDict(dict):
    def __missing__(self, key):  # una variable mal escrita sale tal cual, no rompe el aviso
        return "{" + key + "}"


def formatear(plantilla: str, valores: dict) -> str:
    return (plantilla or "").replace("\\n", "\n").format_map(_SafeDict(valores))


# ── toast de Windows ─────────────────────────────────────────────────────────

def mostrar_toast(app_id: str, titulo: str, mensaje: str, icono: Path | None = None,
                  duracion: str = "short", sonido: str = "default", url: str = "") -> None:
    from winotify import Notification, audio  # perezoso: solo Windows con toasts reales

    # winotify mete la ruta del icono y la URL de 'launch' sin escapar en un
    # atributo XML; la ruta de la app puede llevar "&" -- sin este
    # escape el toast falla en silencio (mismo apaño que APP_RECORDATORIO)
    toast = Notification(
        app_id=app_id or "App Tareas", title=titulo or " ", msg=mensaje or " ",
        icon=escape(str(icono), {'"': "&quot;"}) if icono else "",
        duration="long" if duracion == "long" else "short",
        launch=escape(url, {'"': "&quot;"}) if url else "",
    )
    sonidos = {"default": audio.Default, "reminder": audio.Reminder, "mail": audio.Mail,
               "sms": audio.SMS, "im": audio.IM, "silent": audio.Silent}
    toast.set_audio(sonidos.get(sonido, audio.Default), loop=False)
    toast.show()


# ── Recordatorio ─────────────────────────────────────────────────────────────

def elegir_mensaje(modo: str) -> dict | None:
    mensajes = db.load_recordatorio_mensajes(real=_real(), solo_activos=True)
    if not mensajes:
        return None
    if modo == "rotacion":
        # el menos mostrado (y entre empates, el que lleva mas sin salir) --
        # recorre toda la lista antes de repetir ninguno
        return min(mensajes, key=lambda m: (m["veces_mostrado"], m["ultimo_mostrado"] or "", m["orden"]))
    if modo == "orden":
        return min(mensajes, key=lambda m: (m["veces_mostrado"], m["orden"]))
    return random.choice(mensajes)


def enviar_recordatorio(forzar: bool = False) -> str:
    cfg = config("recordatorio")
    if not forzar:
        if cfg["activo"] != "1":
            return "desactivado"
        if not en_horario(cfg):
            return "fuera de horario"
        if cfg["saltar_festivos"] == "1" and db.hoy_es_festivo(real=_real()):
            return "hoy es festivo"
    mensaje = elegir_mensaje(cfg["orden"])
    if not mensaje:
        resultado = "no hay ningún mensaje activo"
        _guardar_estado("recordatorio", resultado)
        return resultado
    ahora = datetime.now()
    valores = {"categoria": mensaje["categoria"], "hora": ahora.strftime("%H:%M"), "fecha": ahora.strftime("%d/%m/%Y")}
    mostrar_toast(cfg["app_id"], formatear(cfg["titulo"], valores), mensaje["texto"],
                  ruta_icono(cfg["icono"]), cfg["duracion"], cfg["sonido"])
    db.marcar_recordatorio_mostrado(mensaje["id"], real=_real())
    db.set_ajuste("recordatorio.ultimo_ts", str(time.time()), real=_real())  # la cuenta del siguiente sale de aqui
    resultado = f"mostrado: {mensaje['texto'][:120]}"
    _guardar_estado("recordatorio", resultado)
    return resultado


# ── Vigilante de Mantis ──────────────────────────────────────────────────────

def _empresas_mantis() -> tuple[int, list[int], dict]:
    """(pool_id, ids de proyecto Mantis de empresas, {mantis_project_id: empresa})."""
    pool_id = int(db.get_ajuste("mantis.pool_project_id", "1", real=_real()) or 1)
    conn = db.connect(_real())
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, nombre, mantis_project_id FROM empresas WHERE mantis_project_id IS NOT NULL")
            filas = cur.fetchall()
    finally:
        conn.close()
    empresa_por_project = {r[2]: {"id": r[0], "nombre": r[1]} for r in filas}
    return pool_id, list(empresa_por_project), empresa_por_project


def icono_vigilante(cfg: dict, proyecto_id, pool_id: int, empresa_por_project: dict) -> Path | None:
    if proyecto_id == pool_id:
        return ruta_icono(cfg["icono_pool"]) or ruta_icono(cfg["icono_defecto"])
    empresa = empresa_por_project.get(proyecto_id)
    if empresa:
        propio = db.get_ajuste(f"vigilante.icono_empresa.{empresa['id']}", "", real=_real())
        if ruta_icono(propio):
            return ruta_icono(propio)
    return ruta_icono(cfg["icono_defecto"])


def _avisar_incidencia(cfg: dict, inc: dict, pool_id: int, empresa_por_project: dict) -> None:
    empresa = empresa_por_project.get(inc["proyecto_id"])
    valores = {**inc, "empresa": empresa["nombre"] if empresa else ("Sin triar" if inc["proyecto_id"] == pool_id else "")}
    mostrar_toast(
        cfg["app_id"], formatear(cfg["titulo"], valores), formatear(cfg["formato"], valores),
        icono_vigilante(cfg, inc["proyecto_id"], pool_id, empresa_por_project),
        cfg["duracion"], cfg["sonido"], inc.get("url", "") if cfg["abrir_al_pulsar"] == "1" else "",
    )


def probar_vigilante(empresa_id: str = "") -> str:
    """Aviso de ejemplo con el formato/icono actuales -- no llama a Mantis."""
    cfg = config("vigilante")
    pool_id, _, empresa_por_project = _empresas_mantis()
    proyecto_id = pool_id
    for pid, emp in empresa_por_project.items():
        if emp["id"] == empresa_id:
            proyecto_id = pid
    nombre = empresa_por_project.get(proyecto_id, {}).get("nombre", "Incidencias")
    ejemplo = {
        "id": 12345, "resumen": "Ejemplo: no se imprime el albarán", "proyecto": nombre,
        "proyecto_id": proyecto_id, "categoria": "General", "prioridad": "Alta", "estado": "nueva",
        "reporta": "Usuario de prueba", "asignada_a": "SIN ASIGNAR",
        "url": (os.getenv("MANTIS_BASE_URL", "").rstrip("/") + "/my_view_page.php") if os.getenv("MANTIS_BASE_URL") else "",
    }
    _avisar_incidencia(cfg, ejemplo, pool_id, empresa_por_project)
    return "aviso de prueba enviado"


def _cargar_ids_notificados() -> set:
    if not ESTADO_VIGILANTE.exists():
        return set()
    try:
        return set(json.loads(ESTADO_VIGILANTE.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, ValueError):
        return set()


def _guardar_ids_notificados(ids: set) -> None:
    ESTADO_VIGILANTE.parent.mkdir(parents=True, exist_ok=True)
    ESTADO_VIGILANTE.write_text(json.dumps(sorted(ids)), encoding="utf-8")


def _clasificar_y_cachear(incidencias: list[dict]) -> None:
    """Clasifica (IA/correo/manual) y guarda en mantis_origen_cache lo que no
    este ya -- igual que el watcher antiguo, para que el desglose del SLA no
    tenga que clasificar de golpe todo un rango la primera vez."""
    if not incidencias:
        return
    conn = db.connect(_real())
    try:
        with conn.cursor() as cur:
            ids = [i["id"] for i in incidencias]
            cur.execute(f"SELECT mantis_id FROM mantis_origen_cache WHERE mantis_id IN ({','.join(['%s'] * len(ids))})", ids)
            ya = {r[0] for r in cur.fetchall()}
            filas = []
            for inc in incidencias:
                if inc["id"] in ya:
                    continue
                try:
                    creada = datetime.fromisoformat(inc["creada"].strip()).replace(tzinfo=None)
                except Exception:
                    continue
                origen = mantis_client.clasificar_origen(inc["id"])
                filas.append((inc["id"], inc["proyecto_id"], creada, origen["es_ia"], origen["es_correo"]))
            if filas:
                cur.executemany(
                    "INSERT INTO mantis_origen_cache (mantis_id, proyecto_id, creada, es_ia, es_correo, clasificado_en) "
                    "VALUES (%s,%s,%s,%s,%s,NOW()) ON DUPLICATE KEY UPDATE es_ia=VALUES(es_ia), "
                    "es_correo=VALUES(es_correo), clasificado_en=VALUES(clasificado_en)", filas,
                )
        conn.commit()
    finally:
        conn.close()


def revisar_mantis() -> str:
    cfg = config("vigilante")
    if cfg["activo"] != "1":
        return "pausado"  # pausado = cero llamadas a la API de Mantis, garantizado
    if not en_horario(cfg):
        return "fuera de horario"

    primera_vez = not ESTADO_VIGILANTE.exists()  # primera vez: se registra lo abierto sin avisar
    pool_id, empresa_ids, empresa_por_project = _empresas_mantis()
    try:
        incidencias = mantis_client.fetch_pool_issues(pool_id, empresa_ids)
    except ValueError as e:
        resultado = f"no se pudo consultar Mantis: {e}"
        _guardar_estado("vigilante", resultado)
        return resultado

    ya = _cargar_ids_notificados()
    nuevas = [] if primera_vez else [i for i in incidencias if i["id"] not in ya]
    for inc in nuevas:
        try:
            _avisar_incidencia(cfg, inc, pool_id, empresa_por_project)
        except Exception:
            log.exception("no se pudo mostrar el aviso de la incidencia %s", inc.get("id"))
    try:
        _clasificar_y_cachear(incidencias if primera_vez else nuevas)
    except Exception:
        log.exception("no se pudo cachear el origen de las incidencias")

    _guardar_ids_notificados(ya | {i["id"] for i in incidencias})
    if primera_vez:
        resultado = f"primera revisión: {len(incidencias)} abiertas registradas sin avisar"
    elif nuevas:
        resultado = f"{len(nuevas)} nueva(s) avisada(s): " + ", ".join(f"#{i['id']}" for i in nuevas)
    else:
        resultado = f"sin incidencias nuevas ({len(incidencias)} abiertas)"
    _guardar_estado("vigilante", resultado)
    return resultado


# ── Vigia de carpeta (carpeta configurable) ───────────────────────────

VIGIA_IGNORAR = {"thumbs.db", "desktop.ini", ".ds_store"}
VIGIA_MAX_LINEAS = 20  # archivos listados por bloque en la nota; el resto, "... y N mas"


def _cargar_estado_vigia() -> dict:
    if not ESTADO_VIGIA.exists():
        return {}
    try:
        return json.loads(ESTADO_VIGIA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("estado del Vigía de carpeta ilegible, se empieza de cero")
        return {}


def _guardar_estado_vigia(estado: dict) -> None:
    ESTADO_VIGIA.parent.mkdir(parents=True, exist_ok=True)
    tmp = ESTADO_VIGIA.with_suffix(".tmp")
    tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ESTADO_VIGIA)


def _vigia_valido(p: Path) -> bool:
    nombre = p.name.lower()
    return p.is_file() and nombre not in VIGIA_IGNORAR and not nombre.startswith("~$")


def _vigia_archivos(carpeta: Path, subcarpeta: str, recursivo: bool) -> dict:
    """{ruta relativa a 'carpeta': mtime}. Sin recursivo, solo el primer
    nivel (la raiz contiene procesados, Fallidos... que no son la cola)."""
    base = carpeta if subcarpeta in (".", "") else carpeta / subcarpeta
    if not base.is_dir():
        return {}
    iterador = base.rglob("*") if recursivo else base.iterdir()
    return {str(p.relative_to(carpeta)): p.stat().st_mtime for p in iterador if _vigia_valido(p)}


def _vigia_hora(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%d/%m %H:%M")


def _vigia_lista(archivos: dict, ahora: float, con_edad: bool = False) -> list[str]:
    filas = []
    for nombre, ts in sorted(archivos.items(), key=lambda kv: kv[1])[:VIGIA_MAX_LINEAS]:
        if con_edad:
            minutos = int((ahora - ts) / 60)
            filas.append(f"  - {nombre} (desde {_vigia_hora(ts)}, {f'{minutos} min' if minutos < 120 else f'{minutos // 60} h'})")
        else:
            filas.append(f"  - {nombre} ({_vigia_hora(ts)})")
    if len(archivos) > VIGIA_MAX_LINEAS:
        filas.append(f"  - ... y {len(archivos) - VIGIA_MAX_LINEAS} más")
    return filas


def evaluar_vigia(estado: dict, accesible: bool, fallidos: dict, entrada: dict, ahora: float,
                minutos_atasco: int, carpeta: str = "", nombre_fallidos: str = "Fallidos") -> tuple[list[str], list[str], dict]:
    """Logica pura del Vigia de carpeta (sin disco ni BD): compara lo que hay ahora
    con lo ya avisado. Devuelve (lineas de la nota, frases cortas para la
    campana/toast, estado nuevo). Sin lineas = nada que avisar.

    - Fallidos: aviso de cada archivo nuevo; y cuando sale de Fallidos
      (revisado o reprocesado). La primera vez solo se toma la foto de lo que
      ya hay, sin dar la alarma por ello.
    - Atascados: en la cola mas de minutos_atasco; aviso al atascarse y al salir.
    - Sin acceso: una vez al perderlo y otra al recuperarlo. Mientras no hay
      acceso el resto del estado se conserva tal cual, para no dar por
      'resuelto' lo que simplemente no se ve."""
    estado = dict(estado)
    lineas, resumen = [], []

    if not accesible:
        if not estado.get("sin_acceso_desde"):
            estado["sin_acceso_desde"] = ahora
            lineas.append(f"No puedo acceder a la carpeta vigilada ({carpeta}). Mientras siga así, no se vigila nada. "
                          "Puede ser la VPN o la red, el servidor, o permisos.")
            resumen.append("sin acceso a la carpeta")
        return lineas, resumen, estado

    if estado.get("sin_acceso_desde"):
        lineas.append(f"Vuelvo a tener acceso a la carpeta vigilada (sin acceso desde {_vigia_hora(estado['sin_acceso_desde'])}).")
        resumen.append("acceso recuperado")
        estado["sin_acceso_desde"] = None

    if "fallidos" not in estado:
        if fallidos:
            lineas.append(f"Vigía de carpeta activado. Ahora mismo hay {len(fallidos)} archivo(s) en {nombre_fallidos}; "
                          "desde ahora solo avisaré de los nuevos:")
            lineas += _vigia_lista(fallidos, ahora)
        else:
            lineas.append(f"Vigía de carpeta activado. {nombre_fallidos} está vacía.")
        resumen.append("vigilancia activada")
    else:
        conocidos = estado["fallidos"]
        nuevos = {k: v for k, v in fallidos.items() if k not in conocidos}
        fuera = {k: v for k, v in conocidos.items() if k not in fallidos}
        if nuevos:
            lineas.append(f"ARCHIVO FALLIDO: {len(nuevos)} archivo(s) nuevo(s) en {nombre_fallidos}:")
            lineas += _vigia_lista(nuevos, ahora)
            resumen.append(f"{len(nuevos)} fallido(s) nuevo(s)")
        if fuera:
            lineas.append(f"Ya no están en {nombre_fallidos} ({len(fuera)}), revisados o reprocesados:")
            lineas += _vigia_lista(fuera, ahora)
            resumen.append(f"{len(fuera)} fallido(s) resuelto(s)")
    estado["fallidos"] = fallidos

    limite = ahora - minutos_atasco * 60
    atascados = {k: v for k, v in entrada.items() if v <= limite}
    avisados = estado.get("atascados") or {}
    nuevos_atascados = {k: v for k, v in atascados.items() if k not in avisados}
    desatascados = {k: v for k, v in avisados.items() if k not in atascados}
    if nuevos_atascados:
        lineas.append(f"ARCHIVO ATASCADO: {len(nuevos_atascados)} archivo(s) llevan más de {minutos_atasco} min sin procesarse:")
        lineas += _vigia_lista(nuevos_atascados, ahora, con_edad=True)
        resumen.append(f"{len(nuevos_atascados)} atascado(s)")
    if desatascados:
        lineas.append(f"Ya no están en la cola ({len(desatascados)}), parece resuelto:")
        lineas += _vigia_lista(desatascados, ahora)
        resumen.append(f"{len(desatascados)} desatascado(s)")
    estado["atascados"] = atascados
    return lineas, resumen, estado


def usuarios_activos() -> list[str]:
    """Usernames para el desplegable de destinatario -- de la BD real, no de
    db.load_usuarios() (que sigue el toggle real/test)."""
    conn = db.connect(_real())
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT username FROM auth_user WHERE is_active=1 ORDER BY username")
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def _usuario_id(username: str) -> int | None:
    if not (username or "").strip():
        return None
    conn = db.connect(_real())
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM auth_user WHERE username=%s AND is_active=1", (username.strip(),))
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()


def _avisar_vigia(cfg: dict, para_id: int, lineas: list[str], resumen: list[str]) -> int:
    """Nota del Buzon (de la persona a si misma: nace leida) + campana, que
    es lo que salta a la vista, + toast si esta activado. Devuelve el id de
    la nota. Si la BD falla, la excepcion sube y el estado no se guarda: se
    reintenta en la siguiente vuelta."""
    ahora = datetime.now()
    texto = f"[Vigía de carpeta] {ahora.strftime('%d/%m/%Y %H:%M')}\n" + "\n".join(lineas)
    corto = "Vigía de carpeta: " + " · ".join(resumen)
    nota_id = db.crear_buzon_nota(para_id, para_id, texto, real=_real())
    db.crear_notificacion(para_id, "vigia", corto, f"/buzon/#nota-{nota_id}", real=_real())
    if cfg["toast"] == "1":
        try:
            valores = {"resumen": " · ".join(resumen), "hora": ahora.strftime("%H:%M"), "fecha": ahora.strftime("%d/%m/%Y")}
            mostrar_toast(cfg["app_id"], formatear(cfg["titulo"], valores), " · ".join(resumen).capitalize(),
                          ruta_icono(cfg["icono"]), cfg["duracion"], cfg["sonido"])
        except Exception:  # el aviso ya esta en la app; un toast que falla no debe hacer reenviarlo
            log.exception("no se pudo mostrar el toast del Vigía de carpeta")
    return nota_id


def probar_vigia() -> str:
    """Nota + campana + toast de ejemplo -- no mira la carpeta ni toca el estado."""
    cfg = config("vigia")
    para_id = _usuario_id(cfg["destinatario"])
    if not para_id:
        return "falta el destinatario (o no existe ese usuario)"
    ejemplo = f"{cfg['carpeta_fallidos']}\\EJEMPLO.xml"
    _avisar_vigia(cfg, para_id, ["AVISO DE PRUEBA: así llegaría un archivo fallido.", f"  - {ejemplo} ({_vigia_hora(time.time())})"],
                ["aviso de prueba"])
    return f"nota de prueba enviada a {cfg['destinatario']}"


def revisar_vigia() -> str:
    cfg = config("vigia")
    if cfg["activo"] != "1":
        return "pausado"
    if not en_horario(cfg):
        return "fuera de horario"
    para_id = _usuario_id(cfg["destinatario"])
    if not para_id:
        resultado = "falta el destinatario (o no existe ese usuario): no se vigila"
        _guardar_estado("vigia", resultado)
        return resultado

    carpeta = Path(cfg["carpeta"])
    try:
        minutos = max(1, int(cfg["minutos_atasco"]))
    except ValueError:
        minutos = int(DEFAULTS["vigia"]["minutos_atasco"])
    fallidos, entrada = {}, {}
    try:
        accesible = carpeta.is_dir()
        if accesible:
            fallidos = _vigia_archivos(carpeta, cfg["carpeta_fallidos"], recursivo=True)
            for sub in (s.strip() for s in cfg["carpetas_entrada"].split(",") if s.strip()):
                entrada.update(_vigia_archivos(carpeta, sub, recursivo=False))
    except OSError as e:  # la red se cae a mitad de listar
        log.warning("Vigía de carpeta: error leyendo %s: %s", carpeta, e)
        accesible = False

    estado_previo = _cargar_estado_vigia()
    lineas, resumen, estado_nuevo = evaluar_vigia(estado_previo, accesible, fallidos, entrada, time.time(), minutos,
                                                str(carpeta), cfg["carpeta_fallidos"])
    if lineas:
        _avisar_vigia(cfg, para_id, lineas, resumen)
    _guardar_estado_vigia(estado_nuevo)

    if not accesible:
        resultado = "sin acceso a la carpeta" + (" (avisado)" if lineas else "")
    else:
        resultado = f"{len(fallidos)} en {cfg['carpeta_fallidos']}, {len(estado_nuevo['atascados'])} atascado(s)"
        if resumen:
            resultado += " · avisado: " + ", ".join(resumen)
    _guardar_estado("vigia", resultado)
    return resultado


# ── bucle en segundo plano ───────────────────────────────────────────────────

_parar = threading.Event()
_hilos: list[threading.Thread] = []
_lock_fh = None


def _coger_bloqueo() -> bool:
    global _lock_fh
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _lock_fh = open(LOCK_FILE, "a+")
        try:  # Windows
            import msvcrt
            msvcrt.locking(_lock_fh.fileno(), msvcrt.LK_NBLCK, 1)
        except ImportError:  # Linux/macOS (p. ej. dentro de Docker)
            import fcntl
            fcntl.flock(_lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except (ImportError, OSError):
        if _lock_fh:
            _lock_fh.close()
            _lock_fh = None
        return False


GRACIA_ARRANQUE = 120  # segundos minimos tras arrancar la app antes del primer Recordatorio


def toca_ahora(seccion: str, ahora: float, inicio: float, ultimo_intento: float, intervalo: int,
               ultimo_aviso: float = 0.0) -> bool:
    """Si hay que lanzar ya el servicio. El Recordatorio cuenta desde el
    ULTIMO AVISO QUE SALIO DE VERDAD (guardado en la BD, sobrevive a
    reinicios) -- antes contaba desde que arrancaba la app, y reiniciarla
    antes de los 15 min hacia que el aviso no saliera nunca. Ademas espera
    GRACIA_ARRANQUE tras arrancar (no salta nada mas encender el equipo).
    El Vigilante revisa enseguida y luego cada intervalo."""
    if seccion == "recordatorio":
        referencia = max(ultimo_aviso, ultimo_intento)
        return ahora - referencia >= intervalo and ahora - inicio >= min(GRACIA_ARRANQUE, intervalo)
    return ahora - ultimo_intento >= intervalo


def _bucle(seccion: str, accion) -> None:
    inicio, ultimo_intento = time.time(), 0.0
    while not _parar.is_set():
        try:
            intervalo = max(1, int(config(seccion)["intervalo_min"] or 1)) * 60
            ultimo_aviso = 0.0
            if seccion == "recordatorio":
                ultimo_aviso = float(db.get_ajuste("recordatorio.ultimo_ts", "0", real=_real()) or 0)
            if toca_ahora(seccion, time.time(), inicio, ultimo_intento, intervalo, ultimo_aviso):
                ultimo_intento = time.time()  # aunque no salga (fuera de horario...), no reintentar hasta el siguiente intervalo
                log.info("%s: %s", seccion, accion())
        except Exception:
            log.exception("error en el servicio de escritorio '%s'", seccion)
        _parar.wait(TICK_SEGUNDOS)


def arrancar() -> bool:
    if os.getenv("APP_TAREAS_SIN_ESCRITORIO") == "1":
        log.info("servicios de escritorio desactivados (APP_TAREAS_SIN_ESCRITORIO=1)")
        return False
    if not _coger_bloqueo():
        log.info("servicios de escritorio ya activos en otro proceso de la app, no se duplican")
        return False
    _parar.clear()
    servicios = [("recordatorio", enviar_recordatorio), ("vigia", revisar_vigia)]
    if config_app.modulo_activo("mantis"):  # sin Mantis no hay nada que vigilar
        servicios.append(("vigilante", revisar_mantis))
    for seccion, accion in servicios:
        hilo = threading.Thread(target=_bucle, args=(seccion, accion), name=f"escritorio-{seccion}", daemon=True)
        hilo.start()
        _hilos.append(hilo)
    log.info("servicios de escritorio arrancados (%s)", ", ".join(s for s, _ in servicios))
    return True


def parar() -> None:
    global _lock_fh
    _parar.set()
    for hilo in _hilos:
        hilo.join(timeout=5)
    _hilos.clear()
    if _lock_fh:
        _lock_fh.close()
        _lock_fh = None


def servicios_activos() -> bool:
    return any(h.is_alive() for h in _hilos)
