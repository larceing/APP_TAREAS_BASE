# -*- coding: utf-8 -*-
"""Datos de la portada (GET /, main.py::inicio) -- "mi dia": lo de hoy, mi
trabajo, lo que ha pasado en mis muros, el Buzon, las novedades de la
campana, el estado de los avisos de escritorio (IT) y los proyectos por
espacio. Solo junta lo que ya calculan db.py, muro.py y
escritorio_servicios.py; no vuelve a calcular nada por su cuenta."""
from datetime import date, datetime, timedelta

from . import config, db, escritorio_servicios, muro

MAX_LISTA = 8
_MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES_LARGOS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                 "septiembre", "octubre", "noviembre", "diciembre"]


def cuando(fecha_iso: str, hoy: date) -> tuple:
    """(texto, tono) legible para una fecha de vencimiento: 'venció hace 3
    meses' / 'vence hoy' / 'vence mañana' / 'vence el 5 nov'. tono:
    'vencida' | 'hoy' | 'pronto' (<= 3 dias) | ''."""
    if not fecha_iso:
        return "", ""
    try:
        f = date.fromisoformat(fecha_iso[:10])
    except ValueError:
        return fecha_iso, ""
    dias = (f - hoy).days
    if dias < 0:
        atras = -dias
        if atras == 1:
            texto = "venció ayer"
        elif atras < 14:
            texto = f"venció hace {atras} días"
        elif atras < 60:
            texto = f"venció hace {atras // 7} semanas"
        else:
            texto = f"venció hace {atras // 30} meses"
        return texto, "vencida"
    if dias == 0:
        return "vence hoy", "hoy"
    if dias == 1:
        return "vence mañana", "pronto"
    texto = f"vence el {f.day} {_MESES[f.month - 1]}" + (f" {f.year}" if f.year != hoy.year else "")
    return texto, "pronto" if dias <= 3 else ""


def hace(dt_texto: str, ahora: datetime) -> str:
    """'hace 5 min' / 'hace 3 h' / 'ayer' / '12 oct' para la actividad."""
    try:
        dt = datetime.strptime(dt_texto[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return dt_texto
    seg = (ahora - dt).total_seconds()
    if seg < 60:
        return "ahora"
    if seg < 3600:
        return f"hace {int(seg // 60)} min"
    if dt.date() == ahora.date():
        return f"hace {int(seg // 3600)} h"
    if dt.date() == ahora.date() - timedelta(days=1):
        return "ayer"
    return f"{dt.day} {_MESES[dt.month - 1]}"


def _saludo(ahora: datetime) -> str:
    return "Buenos días" if ahora.hour < 14 else ("Buenas tardes" if ahora.hour < 21 else "Buenas noches")


def datos(request, usuario: str) -> dict:
    ahora = datetime.now()
    hoy = ahora.date()
    hoy_iso = hoy.isoformat()
    user_id = db.get_user_id(usuario)
    es_it = bool(request.session.get("es_it"))
    yo = next((u for u in db.load_usuarios() if u["id"] == user_id), None)
    nombre = (yo["nombre_completo"].split()[0] if yo and yo["nombre_completo"] != yo["username"] else usuario)

    # ── tareas ──
    tareas = db.load_home_overview()
    hechas = db.done_status_names_by_project()
    pendientes = [t for t in tareas if t["status"] not in hechas.get(t["proyecto_id"], {"Hecha"})]
    for t in pendientes:
        t["cuando"], t["tono"] = cuando(t["fecha_fin"], hoy)
    vencidas = sorted([t for t in pendientes if t["fecha_fin"] and t["fecha_fin"] < hoy_iso], key=lambda t: t["fecha_fin"])
    ids_vencidas = {t["task_id"] for t in vencidas}
    alta = sorted([t for t in pendientes if t["priority"] == "Alta" and t["task_id"] not in ids_vencidas],
                  key=lambda t: (t["fecha_fin"] or "9999"))
    mias = sorted([t for t in pendientes if user_id and t["asignado_a"] == user_id],
                  key=lambda t: (t["fecha_fin"] or "9999", t["priority"] != "Alta"))
    tareas_hoy = [t for t in pendientes if t["fecha_fin"] == hoy_iso]

    # ── reuniones de hoy (con hora) ──
    reuniones = []
    for r in db.load_reuniones_calendario(usuario, hoy_iso, hoy_iso):
        ini = str(r["fecha_inicio"])
        reuniones.append({**r, "hora": ini[11:16] if len(ini) >= 16 else ""})
    reuniones.sort(key=lambda r: r["hora"])

    # ── muros ──
    mis_muros = [m for m in muro.muros_de(user_id, es_it) if m["propio"]] if user_id else []
    actividad = db.load_actividad_muros([m["id"] for m in mis_muros], MAX_LISTA)
    for a in actividad:
        a["hace"] = hace(a["creado_en"], ahora)

    # ── buzon y novedades ──
    buzon_nuevas, buzon_vencen, novedades = [], [], []
    if user_id:
        buzon_nuevas = [n for n in db.load_buzon(user_id, "recibidas") if not n["leida"]][:4]
        limite = (hoy + timedelta(days=7)).isoformat()
        propias = db.load_buzon(user_id, "propias") + db.load_buzon(user_id, "recibidas")
        buzon_vencen = sorted([n for n in propias if n["vence_en"] and n["vence_en"] <= limite],
                              key=lambda n: n["vence_en"])[:4]
        for n in buzon_vencen:
            n["cuando"], n["tono"] = cuando(n["vence_en"], hoy)
        novedades = [n for n in db.resumen_notificaciones(user_id, 12)["ultimas"] if not n["leida"]][:5]
        for n in novedades:
            n["hace"] = hace(n["creada_en"], ahora)

    # ── avisos de escritorio (solo IT) ──
    servicios = []
    if es_it and config.modulo_activo("escritorio"):
        for clave, titulo, enlace in (("recordatorio", "Recordatorio", "recordatorio"),
                                      ("vigilante", "Vigilante de Mantis", "vigilante"),
                                      ("vigia", "Vigía de carpeta", "vigia")):
            if clave == "vigilante" and not config.modulo_activo("mantis"):
                continue
            try:
                cfg, est = escritorio_servicios.config(clave), escritorio_servicios.estado(clave)
            except Exception:
                continue
            servicios.append({"titulo": titulo, "activo": cfg.get("activo") == "1", "ultima": est["ultima"],
                              "resultado": est["resultado"], "url": f"/configuracion/?tipo={enlace}"})

    # ── proyectos por espacio ──
    pend_por_proy, venc_por_proy = {}, {}
    for t in pendientes:
        pend_por_proy[t["proyecto_id"]] = pend_por_proy.get(t["proyecto_id"], 0) + 1
    for t in vencidas:
        venc_por_proy[t["proyecto_id"]] = venc_por_proy.get(t["proyecto_id"], 0) + 1
    # todos los proyectos activos, agrupados por su espacio (hoy cualquiera ve
    # todos los proyectos, ver CLAUDE.md): primero mis espacios (con su
    # contador del muro), luego el resto y al final los que no tienen espacio
    sin_leer = {m["id"]: m["sin_leer"] for m in mis_muros}
    activos = db.load_proyectos_calendario()
    por_espacio = {}
    for e in db.load_espacios():
        if e["activo"]:
            por_espacio[e["id"]] = {"nombre": e["nombre"], "color": e["color"], "id": e["id"], "personal": e["es_personal"],
                                    "sin_leer": sin_leer.get(e["id"], 0), "mio": e["id"] in sin_leer, "proyectos": []}
    sueltos = {"nombre": "Sin espacio", "color": "#94a3b8", "id": "", "personal": False, "sin_leer": 0, "mio": False,
               "proyectos": []}
    for p in activos:
        espacio_id = db.get_proyecto(p["id"])["espacio_id"]
        destino = por_espacio.get(espacio_id, sueltos)
        destino["proyectos"].append({**p, "pendientes": pend_por_proy.get(p["id"], 0),
                                     "vencidas": venc_por_proy.get(p["id"], 0)})
    grupos = sorted(por_espacio.values(), key=lambda g: (not g["mio"], not g["personal"], g["nombre"].lower())) + [sueltos]
    grupos = [g for g in grupos if g["proyectos"]]

    return {
        "usuario": usuario, "activo": None, "nombre": nombre, "es_it_usuario": es_it,
        "saludo": _saludo(ahora),
        "fecha_larga": f"{_DIAS[hoy.weekday()].capitalize()}, {hoy.day} de {_MESES_LARGOS[hoy.month - 1]}",
        "hoy": hoy_iso, "reuniones": reuniones, "tareas_hoy": tareas_hoy,
        "total_pendientes": len(pendientes), "total_vencidas": len(vencidas), "total_alta": len(alta),
        "mias": mias[:MAX_LISTA], "total_mias": len(mias),
        "vencidas": vencidas[:MAX_LISTA], "alta": alta[:MAX_LISTA],
        "actividad": actividad, "hay_muros": bool(mis_muros),
        "buzon_nuevas": buzon_nuevas, "buzon_vencen": buzon_vencen, "novedades": novedades,
        "servicios": servicios, "grupos": grupos,
    }
