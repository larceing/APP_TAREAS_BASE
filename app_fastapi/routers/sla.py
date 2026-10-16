# -*- coding: utf-8 -*-
"""SLA -- copiado de core/views.py::sla_dashboard/sla_export/mantis_sla_data/
mantis_sincronizar_historico + core/templates/sla.html. Dos pestanas, igual
que el original: "General" (horas laborables sobre tareas reales de
`tareas`, festivos reales de Configuracion -> Calendario) y "Mantis" (en
vivo contra la API via mantis_client.py, + historico local sincronizado a
mano en mantis_incidencias_historico) -- la pestana Mantis solo aparece si
hay un proyecto destino configurado (Configuracion -> Mantis), igual que en
la app real."""
import csv
import io
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from fastapi.requests import Request
from fastapi.responses import JSONResponse, StreamingResponse

from .. import auth, db, logging_setup, mantis_client
from ..templating import templates

router = APIRouter(prefix="/sla", tags=["sla"])


def _rango_por_defecto(qp):
    date_from = qp.get("date_from", "") or (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    date_to = qp.get("date_to", "") or datetime.now().strftime("%Y-%m-%d")
    return date_from, date_to


def _construir_filas(date_from, date_to, proyecto_id, categoria):
    now_ts = db.now_text()
    today = datetime.now().date().isoformat()

    proyectos = db.load_proyectos_calendario()
    proj_map = {p["id"]: p for p in proyectos}
    tareas = db.load_tasks_for_sla(date_from, date_to, proyecto_id, categoria)
    proj_done_cols = db.done_status_names_by_project()
    festivos = db.festivos_dates()

    filas = []
    for t in tareas:
        done_cols = proj_done_cols.get(t["proyecto_id"], set())
        is_closed = bool(t["closed_at"]) or (t["status"] in done_cols)
        is_overdue = bool(t["fecha_fin"] and not is_closed and t["fecha_fin"] < today)
        end_ts = t["closed_at"] or now_ts
        lead_h = db.sla_hours(t["created_at"], end_ts, festivos)
        cycle_h = db.sla_hours(t["started_at"], end_ts, festivos) if t["started_at"] else None
        proj = proj_map.get(t["proyecto_id"])
        filas.append({
            "task": t, "proj_nombre": proj["nombre"] if proj else t["proyecto_id"],
            "is_closed": is_closed, "is_overdue": is_overdue,
            "lead_h": lead_h, "cycle_h": cycle_h,
            "lead_fmt": db.fmt_hours(lead_h), "cycle_fmt": db.fmt_hours(cycle_h),
            "created": t["created_at"][:10] if t["created_at"] else "—",
            "started": t["started_at"][:10] if t["started_at"] else "—",
            "closed": t["closed_at"][:10] if t["closed_at"] else "—",
        })
    return filas, proyectos


@router.get("/")
def ver_sla(request: Request, usuario: str = Depends(auth.requiere_login)):
    qp = request.query_params
    date_from, date_to = _rango_por_defecto(qp)
    proyecto_id = qp.get("project_id", "")
    cat_filter = qp.get("category", "")

    task_rows, proyectos = _construir_filas(date_from, date_to, proyecto_id, cat_filter)

    total = len(task_rows)
    n_closed = sum(1 for r in task_rows if r["is_closed"])
    n_open = total - n_closed
    n_overdue = sum(1 for r in task_rows if r["is_overdue"])
    closed_rows = [r for r in task_rows if r["is_closed"] and r["lead_h"] is not None]
    avg_lead = round(sum(r["lead_h"] for r in closed_rows) / len(closed_rows), 1) if closed_rows else None
    cycle_rows = [r for r in closed_rows if r["cycle_h"] is not None]
    avg_cycle = round(sum(r["cycle_h"] for r in cycle_rows) / len(cycle_rows), 1) if cycle_rows else None

    proj_stats: dict = {}
    for r in task_rows:
        pid = r["task"]["proyecto_id"]
        d = proj_stats.setdefault(pid, {"nombre": r["proj_nombre"], "total": 0, "done": 0,
                                          "open": 0, "overdue": 0, "lead_sum": 0.0, "lead_count": 0})
        d["total"] += 1
        if r["is_closed"]:
            d["done"] += 1
            if r["lead_h"] is not None:
                d["lead_sum"] += r["lead_h"]
                d["lead_count"] += 1
        else:
            d["open"] += 1
        if r["is_overdue"]:
            d["overdue"] += 1

    proj_rows = []
    for d in sorted(proj_stats.values(), key=lambda x: -x["total"]):
        avg = round(d["lead_sum"] / d["lead_count"], 1) if d["lead_count"] else None
        pct = round(d["done"] / d["total"] * 100) if d["total"] else 0
        proj_rows.append({**d, "avg_lead": db.fmt_hours(avg), "pct": pct})

    mantis_destino_actual = db.get_ajuste("mantis.proyecto_destino", "")

    return templates.TemplateResponse(request, "sla.html", {
        "usuario": usuario, "activo": "sla",
        "task_rows": sorted(task_rows, key=lambda r: r["task"]["created_at"] or "", reverse=True),
        "proj_rows": proj_rows, "total": total, "n_closed": n_closed, "n_open": n_open, "n_overdue": n_overdue,
        "avg_lead": db.fmt_hours(avg_lead), "avg_cycle": db.fmt_hours(avg_cycle),
        "date_from": date_from, "date_to": date_to, "proj_id": proyecto_id, "cat_filter": cat_filter,
        "filter_projects": sorted(proyectos, key=lambda p: p["nombre"]),
        "all_cats": db.load_distinct_task_categories(),
        "mantis_destino_actual": mantis_destino_actual,
        "mantis_empresas_con_mapeo": any(e["mantis_project_id"] for e in db.load_empresas()),
    })


@router.get("/exportar/")
def exportar_sla(request: Request, usuario: str = Depends(auth.requiere_login)):
    qp = request.query_params
    date_from, date_to = _rango_por_defecto(qp)
    proyecto_id = qp.get("project_id", "")
    cat_filter = qp.get("category", "")
    task_rows, _ = _construir_filas(date_from, date_to, proyecto_id, cat_filter)

    buf = io.StringIO()
    buf.write("﻿")  # BOM utf-8-sig, igual que el original (Excel en Windows)
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["Tarea", "Proyecto", "Categoria", "Estado", "Creada", "Iniciada", "Cerrada",
                      "Lead Time (h laborables)", "Cycle Time (h laborables)", "Vencida"])
    for r in task_rows:
        t = r["task"]
        writer.writerow([
            t["title"], r["proj_nombre"], t["category"], t["status"],
            r["created"] if r["created"] != "—" else "", r["started"] if r["started"] != "—" else "",
            r["closed"] if r["closed"] != "—" else "",
            r["lead_h"] if r["lead_h"] is not None else "", r["cycle_h"] if r["cycle_h"] is not None else "",
            "Si" if r["is_overdue"] else "No",
        ])
    buf.seek(0)
    filename = f"sla_{date_from}_{date_to}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8-sig",
                              headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/mantis/json")
def mantis_sla_json(usuario: str = Depends(auth.requiere_login)):
    pool_id, empresa_project_ids = db.get_mantis_config()
    try:
        incidencias = mantis_client.fetch_pool_issues(pool_id, empresa_project_ids)
    except Exception as e:
        logging_setup.errores.exception(f"{usuario} | GET /sla/mantis/json -> fallo Mantis: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    mias = [i for i in incidencias if i.get("asignada_a_soy_yo")]
    for inc in mias:
        inc["open_h"] = db.mantis_open_hours(inc["creada"])
        inc["open_fmt"] = db.fmt_hours(inc["open_h"])
    mias.sort(key=lambda i: i["creada"])

    horas_validas = [i["open_h"] for i in mias if i["open_h"] is not None]
    avg_open = round(sum(horas_validas) / len(horas_validas), 1) if horas_validas else None

    por_proyecto = []
    for nombre in sorted({i["proyecto"] for i in mias}):
        del_proyecto = [i for i in mias if i["proyecto"] == nombre]
        horas = [i["open_h"] for i in del_proyecto if i["open_h"] is not None]
        avg = round(sum(horas) / len(horas), 1) if horas else None
        por_proyecto.append({"proyecto": nombre, "total": len(del_proyecto), "avg_open_fmt": db.fmt_hours(avg)})

    return JSONResponse({
        "ok": True, "total": len(mias), "avg_open_fmt": db.fmt_hours(avg_open),
        "por_proyecto": por_proyecto, "incidencias": mias, "historico": _mantis_historico_resumen(),
        "umbral_ambar_h": float(db.get_ajuste("mantis.umbral_ambar_horas", "24") or 24),
        "umbral_rojo_h": float(db.get_ajuste("mantis.umbral_rojo_horas", "72") or 72),
    })


def _mantis_historico_resumen() -> dict:
    filas = db.load_mantis_historico()
    resueltas = [f for f in filas if f["resuelta_en"] is not None]
    horas = [(f["resuelta_en"] - f["creada"]).total_seconds() / 3600 for f in resueltas]
    avg_resolucion = round(sum(horas) / len(horas), 1) if horas else None

    por_proyecto = []
    for nombre in sorted({f["proyecto"] for f in resueltas}):
        del_proyecto = [f for f in resueltas if f["proyecto"] == nombre]
        h = [(f["resuelta_en"] - f["creada"]).total_seconds() / 3600 for f in del_proyecto]
        por_proyecto.append({"proyecto": nombre, "total": len(del_proyecto),
                              "avg_resolucion_fmt": db.fmt_hours(round(sum(h) / len(h), 1))})

    ultimo_sync = max((f["ultima_sync"] for f in filas), default=None)
    return {
        "total": len(resueltas), "avg_resolucion_fmt": db.fmt_hours(avg_resolucion),
        "por_proyecto": por_proyecto,
        "ultimo_sync": ultimo_sync.strftime("%Y-%m-%d %H:%M") if ultimo_sync else None,
    }


@router.post("/mantis/sincronizar/")
def sincronizar_mantis_historico(usuario: str = Depends(auth.requiere_login)):
    pool_id, empresa_project_ids = db.get_mantis_config()
    try:
        incidencias = mantis_client.fetch_historico_mio([pool_id, *empresa_project_ids])
    except Exception as e:
        logging_setup.errores.exception(f"{usuario} | POST /sla/mantis/sincronizar/ -> fallo Mantis: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    sync_ts = db.now_text()
    rows = []
    for inc in incidencias:
        creada = db.mantis_iso_a_naive(inc["creada"])
        actualizada = db.mantis_iso_a_naive(inc["actualizada"])
        if not creada or not actualizada:
            continue
        resuelta_en = actualizada if inc["estado_name"] in mantis_client.ESTADOS_CERRADOS else None
        rows.append({
            "mantis_id": inc["id"], "proyecto": inc["proyecto"], "categoria": inc["categoria"],
            "prioridad": inc["prioridad"], "resumen": inc["resumen"],
            "estado_name": inc["estado_name"], "estado_label": inc["estado"],
            "creada": creada, "actualizada": actualizada, "resuelta_en": resuelta_en,
        })

    db.upsert_mantis_historico(rows, sync_ts)
    return JSONResponse({"ok": True, "total": len(rows)})
