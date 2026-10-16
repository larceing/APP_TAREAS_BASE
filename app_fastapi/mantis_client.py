# -*- coding: utf-8 -*-
"""Cliente minimo de la API REST de MantisBT (ver Manual_API_MantisBT_Incidencias.md
en la raiz del proyecto). Principalmente de lectura -- la unica excepcion es
move_issue(), el unico punto de toda la app que escribe en Mantis (mueve una
incidencia del pool a un proyecto de empresa y la asigna). Funciones puras de
red: no tocan la BD de la app, igual que core/docx_import.py. Errores de
configuracion/red/API se traducen a ValueError con mensaje legible para que
la vista los convierta en messages.error, en vez de dejar pasar el traceback
crudo de requests."""
from __future__ import annotations

import os

import requests

# que proyectos de Mantis son "nuestros" (el pool sin triar + las empresas a
# las que se mueve una vez categorizada) ya NO es una constante fija aqui --
# antes lo era (POOL_PROJECT_ID/EMPRESA_PROJECT_NAMES) y habia que tocar
# codigo si Mantis reorganizaba ids o se sumaba una empresa. Ahora ese mapeo
# vive en ajustes_app/empresas (ver views.py::_mantis_config) y llega a estas
# funciones como parametro -- este modulo sigue sin tocar la BD de la app.
ESTADOS_CERRADOS = {"resolved", "closed"}  # publico: tambien lo usa views.py para el historico
_TIMEOUT = 15


def _reportero_ia() -> str:
    """Cuenta de Mantis de un bot/IA que abre incidencias por su cuenta
    (MANTIS_REPORTERO_IA en .env, vacio = no hay ninguno): sus incidencias
    se cuentan aparte en el desglose de origen del SLA."""
    return os.getenv("MANTIS_REPORTERO_IA", "").strip().lower()

_PAGE_SIZE = 100
_MAX_PAGES = 50  # tope de seguridad (5000 incidencias/proyecto)

# El manual (Manual_API_MantisBT_Incidencias.md) decia que la API siempre
# devuelve el objeto COMPLETO de cada incidencia (historial de cambios,
# notas, adjuntos, custom_fields...) y que no hay forma de pedir solo unos
# campos -- FALSO: la especificacion oficial (mantisbt_openapi.yaml) SI
# documenta un parametro `select` para elegir campos, y probado contra el
# servidor real es la diferencia entre ~14s y ~0.2s por pagina en proyectos
# con mucho historico (1000+ incidencias). Con
# select, un historico asi pagina en ~3s -- ya no hace falta
# recortar por fecha del lado del cliente, se trae todo sin problema.
_SELECT_FIELDS = ",".join([
    "id", "summary", "description", "project", "category", "priority",
    "status", "reporter", "handler", "created_at", "updated_at",
])

_PRIORIDAD_MAP = {
    "baja": "Baja",
    "normal": "Normal",
    "alta": "Alta",
    "urgente": "Alta",
    "inmediata": "Alta",
}


def _base_url() -> str:
    base = os.getenv("MANTIS_BASE_URL", "").strip().rstrip("/")
    if not base:
        raise ValueError("configura MANTIS_BASE_URL en .env (ej. https://mantis.miempresa.com)")
    return base


def _token() -> str:
    token = os.getenv("MANTIS_API_TOKEN", "").strip()
    if not token:
        raise ValueError("configura MANTIS_API_TOKEN en .env (Mantis -> Mi cuenta -> API Tokens)")
    return token


def _mi_email() -> str:
    email = os.getenv("MANTIS_MY_EMAIL", "").strip().lower()
    if not email:
        raise ValueError("configura MANTIS_MY_EMAIL en .env (tu email de usuario en Mantis)")
    return email


def _mi_username() -> str:
    username = os.getenv("MANTIS_MY_USERNAME", "").strip()
    if not username:
        raise ValueError("configura MANTIS_MY_USERNAME en .env (tu usuario/login en Mantis)")
    return username


def _mapear_prioridad(label: str) -> str:
    return _PRIORIDAD_MAP.get((label or "").strip().lower(), "Normal")


def _issue_a_dict(base_url: str, issue: dict, mi_email: str) -> dict:
    handler = issue.get("handler")
    reporter = issue.get("reporter") or {}
    return {
        "id":          issue.get("id"),
        "resumen":     issue.get("summary", ""),
        "descripcion": issue.get("description", ""),
        "proyecto":    (issue.get("project") or {}).get("name", ""),
        "proyecto_id": (issue.get("project") or {}).get("id"),
        "categoria":   (issue.get("category") or {}).get("name", ""),
        "estado":      (issue.get("status") or {}).get("label", ""),
        "estado_name": (issue.get("status") or {}).get("name", ""),
        "prioridad":   _mapear_prioridad((issue.get("priority") or {}).get("label", "")),
        "reporta":     reporter.get("real_name", ""),
        "reporta_email": reporter.get("email", ""),  # solo para sugerir empresa por dominio, ver views.py
        "reporta_soy_yo": (reporter.get("email") or "").strip().lower() == mi_email,
        "asignada_a":  handler.get("real_name", "") if handler else "SIN ASIGNAR",
        "asignada_a_soy_yo": bool(handler) and (handler.get("email") or "").strip().lower() == mi_email,
        # 'name' es el usuario/login de Mantis del handler (distinto de
        # 'real_name', el nombre para mostrar) -- lo que se compara contra
        # el mapeo de Configuracion -> Mantis cuando el handler NO soy yo,
        # ver routers/mantis.py::importar_tareas.
        "asignada_a_username": handler.get("name", "") if handler else "",
        "creada":      issue.get("created_at", ""),
        "actualizada": issue.get("updated_at", ""),
        "url":         f"{base_url}/view.php?id={issue.get('id')}",
    }


def _fetch_project_issues_raw(base_url: str, headers: dict, project_id: int) -> list[dict]:
    """Pagina un unico proyecto de Mantis hasta agotar resultados, sin
    filtrar nada (ni estado ni asignado) -- devuelve los issues tal cual los
    da la API. Pide solo los campos generales (select=...): sin eso, un
    proyecto con mucho historico tarda muchisimo por pagina. Usada tanto por
    _fetch_project_issues() (que si filtra) como por fetch_historico_mio()
    (que necesita ver tambien las resueltas/cerradas)."""
    issues_crudos: list[dict] = []
    page = 1
    while page <= _MAX_PAGES:
        try:
            resp = requests.get(
                f"{base_url}/api/rest/issues/",
                headers=headers,
                params={
                    "project_id": project_id, "page_size": _PAGE_SIZE, "page": page,
                    "select": _SELECT_FIELDS,
                },
                timeout=_TIMEOUT,
            )
        except requests.RequestException as e:
            raise ValueError(f"no se pudo contactar con Mantis ({base_url}): {e}") from e

        if resp.status_code in (401, 403):
            raise ValueError("Mantis rechazo el token (401/403) -- revisa MANTIS_API_TOKEN en .env")
        if not resp.ok:
            raise ValueError(f"Mantis devolvio un error ({resp.status_code}): {resp.text[:200]}")

        try:
            data = resp.json()
        except ValueError as e:
            raise ValueError("la respuesta de Mantis no es JSON valido") from e

        issues = data.get("issues", [])
        if not issues:
            break
        issues_crudos.extend(issues)

        if len(issues) < _PAGE_SIZE:
            break
        page += 1

    return issues_crudos


def _fetch_project_issues(base_url: str, headers: dict, project_id: int,
                           solo_mia_o_sin_asignar: bool, mi_email: str) -> list[dict]:
    """Igual que _fetch_project_issues_raw() pero excluyendo resueltas/cerradas.

    solo_mia_o_sin_asignar: en los proyectos de empresa una incidencia solo llega ahi
    porque alguien ya la movio y asigno a una persona concreta -- si esta
    asignada a otro companero Y ademas no la reporte yo, ya la esta llevando
    el, no hace falta revisarla aqui. Se incluye si: no tiene nadie asignado
    (por si acaso: no deberia pasar, pero mejor no perderla), el asignado soy
    yo, o el reportero soy yo aunque este asignada a otra persona -- para
    poder seguir una incidencia que abri yo aunque ya se la haya quedado
    otro (pedido explicito del usuario: "cualquier incidencia donde salga mi
    nombre o correo", no solo las que llevo asignadas)."""
    incidencias: list[dict] = []
    for issue in _fetch_project_issues_raw(base_url, headers, project_id):
        estado_name = (issue.get("status") or {}).get("name", "")
        if estado_name in ESTADOS_CERRADOS:
            continue
        if solo_mia_o_sin_asignar:
            handler = issue.get("handler")
            reporter = issue.get("reporter") or {}
            asignada_a_otro = bool(handler) and (handler.get("email") or "").strip().lower() != mi_email
            reportada_por_mi = (reporter.get("email") or "").strip().lower() == mi_email
            if asignada_a_otro and not reportada_por_mi:
                continue
        incidencias.append(_issue_a_dict(base_url, issue, mi_email))
    return incidencias


def fetch_pool_issues(pool_project_id: int, empresa_project_ids: list[int]) -> list[dict]:
    """Incidencias no resueltas/cerradas de los proyectos donde puede acabar
    una incidencia "nuestra": el pool (sin filtrar por asignado, ahi todavia
    no se sabe a quien tocara) + las empresas (solo las asignadas a mi o sin
    asignar -- ver _fetch_project_issues). Un mismo issue solo puede estar en
    un proyecto de Mantis a la vez, asi que no hay duplicados entre ellos.

    pool_project_id/empresa_project_ids ya no son constantes fijas de este
    modulo -- los decide el usuario en Configuracion (ver
    views.py::_mantis_config), pueden cambiar sin tocar codigo."""
    base_url = _base_url()
    # este servidor Mantis rechaza "Bearer <token>" (403) -- solo acepta el
    # token a secas, aunque el manual de la API diga que ambos formatos valen
    headers = {"Authorization": _token()}
    mi_email = _mi_email()

    incidencias: list[dict] = []
    for project_id in [pool_project_id, *empresa_project_ids]:
        solo_mia = project_id != pool_project_id
        incidencias.extend(_fetch_project_issues(base_url, headers, project_id, solo_mia, mi_email))
    return incidencias


def fetch_historico_mio(project_ids: list[int]) -> list[dict]:
    """Todas las incidencias (cualquier estado, incluidas resueltas/cerradas)
    de los proyectos indicados que AHORA MISMO tienen mi email como handler --
    para guardar en local y poder calcular tiempos de resolucion reales, algo
    que fetch_pool_issues() no puede dar porque excluye las resueltas a
    proposito (por rendimiento). No incluye lo que tuve asignado y ya se
    reasigno a otra persona -- Mantis no expone ese historial sin pedir
    history[] por incidencia, una llamada por incidencia que no compensa
    aqui. Comprobado que filter_id=assigned no sirve de atajo: solo devuelve
    lo asignado y abierto ahora, no el historico (ver Manual_API_MantisBT_Incidencias.md)."""
    base_url = _base_url()
    headers = {"Authorization": _token()}
    mi_email = _mi_email()

    incidencias: list[dict] = []
    for project_id in project_ids:
        for issue in _fetch_project_issues_raw(base_url, headers, project_id):
            handler = issue.get("handler")
            if not handler or (handler.get("email") or "").strip().lower() != mi_email:
                continue
            incidencias.append(_issue_a_dict(base_url, issue, mi_email))
    return incidencias


def fetch_todas_las_incidencias(project_ids: list[int]) -> list[dict]:
    """Todas las incidencias (cualquier estado, cualquier asignado -- a
    diferencia de fetch_historico_mio(), que solo trae lo mio) de los
    proyectos indicados. Pensada para analizar el equipo completo, no una
    sola persona -- usada por el desglose de origen del SLA (ver
    views.py::mantis_origen_desglose), donde se filtra despues por fecha de
    creacion en Python (la API no admite filtro de fecha en la URL, ver
    Manual_API_MantisBT_Incidencias.md seccion 0)."""
    base_url = _base_url()
    headers = {"Authorization": _token()}
    mi_email = _mi_email()

    incidencias: list[dict] = []
    for project_id in project_ids:
        for issue in _fetch_project_issues_raw(base_url, headers, project_id):
            incidencias.append(_issue_a_dict(base_url, issue, mi_email))
    return incidencias


def fetch_actualizadas_desde(desde_iso: str | None) -> list[dict]:
    """Incidencias de TODOS los proyectos (sin project_id -- un unico listado
    global) cuyo updated_at es >= desde_iso, o todo el historico si
    desde_iso es None. Para el espejo local del desglose de origen del SLA
    (db.upsert_mantis_espejo): comprobado contra el servidor real que el
    listado sale ordenado por updated_at DESCENDENTE, asi que se pagina hasta
    la primera pagina que ya cae entera antes de desde_iso y se corta ahi --
    una puesta al dia normal es 1-2 paginas (~0.5s), no las ~200 del
    historico entero (~19k incidencias, ~1-2 min). Mover de proyecto,
    reasignar o cambiar categoria actualiza updated_at en Mantis, asi que
    esas incidencias tambien vuelven a salir aqui, no solo las nuevas."""
    from datetime import datetime

    base_url = _base_url()
    headers = {"Authorization": _token()}
    mi_email = _mi_email()
    corte = datetime.fromisoformat(desde_iso) if desde_iso else None

    incidencias: list[dict] = []
    page = 1
    while page <= 1000:  # tope de seguridad (100k incidencias)
        try:
            resp = requests.get(
                f"{base_url}/api/rest/issues/", headers=headers,
                params={"page_size": _PAGE_SIZE, "page": page, "select": _SELECT_FIELDS},
                timeout=_TIMEOUT,
            )
        except requests.RequestException as e:
            raise ValueError(f"no se pudo contactar con Mantis ({base_url}): {e}") from e
        if resp.status_code in (401, 403):
            raise ValueError("Mantis rechazo el token (401/403) -- revisa MANTIS_API_TOKEN en .env")
        if not resp.ok:
            raise ValueError(f"Mantis devolvio un error ({resp.status_code}): {resp.text[:200]}")
        issues = resp.json().get("issues", [])
        if not issues:
            break
        llego_al_corte = False
        for issue in issues:
            if corte and datetime.fromisoformat(issue.get("updated_at", "")) < corte:
                llego_al_corte = True
                break
            incidencias.append(_issue_a_dict(base_url, issue, mi_email))
        if llego_al_corte or len(issues) < _PAGE_SIZE:
            break
        page += 1
    return incidencias


def clasificar_origen(issue_id: int) -> dict:
    """Para el desglose de origen del SLA: a partir del DETALLE COMPLETO de
    una incidencia (una unica llamada, sin `select`, igual patron que
    fue_creada_por_ia) decide en un solo viaje:
    - es_ia: el PRIMER evento del historial lo creo el bot/IA de MANTIS_REPORTERO_IA (mismo criterio
      que fue_creada_por_ia -- el campo reporter no sirve, el bot se
      reasigna a si misma el informador real al crear el ticket).
    - es_correo: la descripcion empieza literalmente por 'Email from:' --
      sello que deja el conector de correo->incidencia de esta instalacion
      de Mantis. Comprobado contra incidencias reales (ver conversacion/
      analisis de Configuracion -> SLA): cuando no aparece este sello no
      hay ninguna otra señal fiable en la API para saber si vino por
      correo, así que se considera dada de alta a mano.
    Si algo falla (red, formato) se asume que NO es IA y NO es correo (cae
    en "manual") -- es solo un dato de clasificacion para un informe, nunca
    debe romperlo."""
    base_url = _base_url()
    headers = {"Authorization": _token()}
    try:
        resp = requests.get(f"{base_url}/api/rest/issues/{issue_id}", headers=headers, timeout=_TIMEOUT)
        if not resp.ok:
            return {"es_ia": False, "es_correo": False}
        data = resp.json()
        issue = data.get("issues", [data])[0] if isinstance(data.get("issues"), list) else data
        historial = issue.get("history") or []
        creador = (historial[0].get("user") or {}).get("name", "") if historial else ""
        es_ia = bool(_reportero_ia()) and creador.strip().lower() == _reportero_ia()
        es_correo = (issue.get("description") or "").strip().lower().startswith("email from:")
        return {"es_ia": es_ia, "es_correo": es_correo}
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return {"es_ia": False, "es_correo": False}


def _patch_issue(issue_id: int, body: dict) -> None:
    base_url = _base_url()
    headers = {"Authorization": _token()}
    try:
        resp = requests.patch(f"{base_url}/api/rest/issues/{issue_id}",
                               headers=headers, json=body, timeout=_TIMEOUT)
    except requests.RequestException as e:
        raise ValueError(f"no se pudo actualizar la incidencia #{issue_id} en Mantis: {e}") from e
    if not resp.ok:
        raise ValueError(f"Mantis rechazo actualizar la incidencia #{issue_id} ({resp.status_code}): {resp.text[:200]}")


def fue_creada_por_ia(issue_id: int) -> bool:
    """Si la incidencia la creo el bot/IA de la empresa (MANTIS_REPORTERO_IA), a partir del
    HISTORIAL (no del campo reporter): el bot se reasigna a si misma como
    informador real en el mismisimo instante de crear el ticket (comprobado
    en el historial de una incidencia real), asi que por el momento en que
    cualquiera la consulta el campo reporter YA muestra a la persona real,
    nunca al bot -- el primer evento del historial (tipo "issue-new") es
    la unica forma fiable de saber quien la creo de verdad.

    Requiere el detalle completo de la incidencia (sin `select`, una unica
    llamada por id) -- solo se llama UNA VEZ por incidencia, al importarla
    a una tarea local (ver views.py::mantis_importar_tareas), nunca en el
    listado ni en el vigilante de fondo, para no multiplicar llamadas a la
    API. Si algo falla (red, formato inesperado) se asume que NO es de la
    IA -- es solo un dato de filtrado, no debe romper la importacion."""
    base_url = _base_url()
    headers = {"Authorization": _token()}
    try:
        resp = requests.get(f"{base_url}/api/rest/issues/{issue_id}", headers=headers, timeout=_TIMEOUT)
        if not resp.ok:
            return False
        data = resp.json()
        issue = data.get("issues", [data])[0] if isinstance(data.get("issues"), list) else data
        historial = issue.get("history") or []
        if not historial:
            return False
        creador = (historial[0].get("user") or {}).get("name", "")
        return bool(_reportero_ia()) and creador.strip().lower() == _reportero_ia()
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return False


def set_reporter(issue_id: int, username: str) -> None:
    """Corrige el informador (reporter) de una incidencia -- p.ej. cuando se
    abrio a nombre propio pero la peticion real vino de otra persona, y se
    quiere dejar constancia de quien pidio el trabajo sin tocar quien lo
    esta llevando (el handler no se toca, solo el campo reporter). Un unico
    PATCH, mismo patron que _patch_issue()/move_issue()."""
    _patch_issue(issue_id, {"reporter": {"name": username}})


def resolve_issue(issue_id: int, nota: str, resolution: str = "fixed") -> None:
    """Resuelve una incidencia real en Mantis -- DOS llamadas, en este orden
    (comprobado contra el servidor real, ver Manual_API_MantisBT_Incidencias.md
    seccion 9 y el historial de incidencias resueltas a mano):
    1. PATCH status=resolved + resolution=<resolution>, EN EL MISMO PATCH
       (igual que move_issue() con handler+status: son un unico evento de
       historial, no dos, si van en el mismo cuerpo).
    2. POST una nota a /api/rest/issues/{id}/notes -- Mantis NO impone esto
       por API (a diferencia de la interfaz web, que obliga a escribir algo
       al resolver desde el formulario), pero el historial real de
       incidencias resueltas a mano muestra que SIEMPRE se deja una nota en
       el mismo instante que el cambio de estado; se replica aqui para
       mantener la misma practica, no porque la API lo exija.

    Si el PATCH triunfa pero la nota falla, la incidencia SE QUEDA resuelta
    sin nota (no hay forma de deshacer el PATCH desde aqui) -- el error se
    relanza para que el llamador se entere y anada la nota a mano si hace
    falta. Segunda funcion de este modulo, junto a move_issue(), que escribe
    en Mantis."""
    _patch_issue(issue_id, {"status": {"name": "resolved"}, "resolution": {"name": resolution}})
    base_url = _base_url()
    headers = {"Authorization": _token()}
    try:
        resp = requests.post(f"{base_url}/api/rest/issues/{issue_id}/notes",
                              headers=headers, json={"text": nota}, timeout=_TIMEOUT)
    except requests.RequestException as e:
        raise ValueError(f"incidencia #{issue_id}: se marco resuelta pero la nota fallo -- {e}") from e
    if not resp.ok:
        raise ValueError(f"incidencia #{issue_id}: se marco resuelta pero Mantis rechazo la nota "
                          f"({resp.status_code}): {resp.text[:200]}")


def create_issue(project_id: int, summary: str, description: str, category: str,
                 priority: str = "normal", severity: str = "major", handler_username: str = None) -> int:
    """Crea una incidencia en Mantis y devuelve su id. priority/severity son
    los 'name' internos de Mantis (priority: low/normal/high/urgent/immediate;
    severity: minor/major/crash/block...), category el nombre tal cual sale
    en el proyecto (p. ej. "ERP Local - BA"). Con handler_username queda
    asignada a esa persona (estado 'asignado'); el informador es siempre el
    dueño del token -- para otro, set_reporter() despues. Escribe en Mantis:
    solo con una peticion explicita y el texto confirmado."""
    base_url = _base_url()
    headers = {"Authorization": _token()}
    body = {
        "summary": summary, "description": description, "project": {"id": project_id},
        "category": {"name": category}, "priority": {"name": priority}, "severity": {"name": severity},
    }
    if handler_username:
        body["handler"] = {"name": handler_username}
        body["status"] = {"name": "assigned"}
    try:
        resp = requests.post(f"{base_url}/api/rest/issues/", headers=headers, json=body, timeout=_TIMEOUT)
    except requests.RequestException as e:
        raise ValueError(f"no se pudo crear la incidencia en Mantis: {e}") from e
    if not resp.ok:
        raise ValueError(f"Mantis rechazo crear la incidencia ({resp.status_code}): {resp.text[:300]}")
    return resp.json()["issue"]["id"]


def add_relationship(issue_id: int, target_id: int, tipo: str = "related-to") -> None:
    """Relaciona dos incidencias (tipo: related-to, duplicate-of, parent-of...)."""
    base_url = _base_url()
    headers = {"Authorization": _token()}
    try:
        resp = requests.post(f"{base_url}/api/rest/issues/{issue_id}/relationships/", headers=headers,
                             json={"issue": {"id": target_id}, "type": {"name": tipo}}, timeout=_TIMEOUT)
    except requests.RequestException as e:
        raise ValueError(f"no se pudo relacionar #{issue_id} con #{target_id}: {e}") from e
    if not resp.ok:
        raise ValueError(f"Mantis rechazo relacionar #{issue_id} con #{target_id} ({resp.status_code}): {resp.text[:200]}")


def move_issue(issue_id: int, project_id: int) -> None:
    """Mueve una incidencia del pool a un proyecto de empresa y la asigna al
    usuario del token (MANTIS_MY_USERNAME) -- DOS PATCH:
    1. project (mover de proyecto).
    2. handler + status=assigned, EN EL MISMO PATCH.

    Comprobado contra el historial real de incidencias movidas a mano por la
    interfaz web: project_id siempre es un evento de historial aparte, pero
    handler y el cambio de estado "nueva -> asignado" ocurren siempre en el
    mismo instante exacto -- son una unica accion en Mantis, no dos. La
    primera version de esta funcion solo mandaba handler (sin status) y el
    estado se quedaba en "nueva" varios minutos hasta que algo externo lo
    corregia -- justo la inconsistencia que esto evita.

    Unico punto de toda la app que escribe en Mantis. El llamador es
    responsable de comprobar antes que la incidencia es del pool "Incidencias"
    y esta sin asignar -- esta funcion no vuelve a comprobarlo, mueve lo que
    se le pida."""
    mi_username = _mi_username()
    _patch_issue(issue_id, {"project": {"id": project_id}})
    try:
        _patch_issue(issue_id, {"handler": {"name": mi_username}, "status": {"name": "assigned"}})
    except ValueError as e:
        raise ValueError(f"incidencia #{issue_id}: se movio de proyecto pero NO se pudo asignar -- {e}") from e
