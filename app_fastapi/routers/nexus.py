# -*- coding: utf-8 -*-
"""Nexus: buscador del catalogo documental (antes la BD `confluence_local`, hoy dentro de app_tareas), portado
desde APP_NEXUS_BUSCADOR (app suelta en el puerto 8011, sin login) como una
pestaña mas de esta app -- ver PROPUESTA_NEXUS_EN_APP_TAREAS.md para el
porque. search.py/preview.py/cripto.py en app_fastapi/nexus/ son copia
literal del codigo original; lo unico que cambia es el transporte (rutas
FastAPI con prefix="/nexus" en vez de "/api/...", porque ese prefijo esta
reservado en esta app para la API externa autenticada con X-API-Key y
EXENTA de CSRF -- Nexus si necesita CSRF en sus POST de credenciales) y la
seguridad (antes la app entera era publica sin login; aqui exige sesion, y
opcionalmente solo IT, ver _requiere_acceso_nexus).

Niveles de acceso (seccion 2.5 de la propuesta):
- Busqueda/stats/tema/tecnologias/preview: segun el ajuste configurable
  'nexus.acceso' (Configuracion -> Nexus) -- 'it' (por defecto) o 'todos'.
- Modo dev (stats-dev/buscar-dev) y credenciales cifradas: SIEMPRE IT, sin
  importar ese ajuste -- no son navegables desde el acceso general nunca."""
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from .. import auth, db
from ..nexus import preview, search
from ..templating import templates

router = APIRouter(prefix="/nexus", tags=["nexus"])

# Limite de intentos por credencial (en memoria -- se resetea si se reinicia
# el proceso; suficiente para frenar fuerza bruta casual, no un atacante que
# controla el propio servidor). 5 fallos -> bloqueo de 60s antes de poder
# reintentar esa misma credencial otra vez. Copia del original
# (APP_NEXUS_BUSCADOR/app/main.py).
MAX_INTENTOS = 5
BLOQUEO_SEGUNDOS = 60
_intentos_fallidos: dict[str, list[float]] = defaultdict(list)


def _bloqueado(credencial_id: str) -> float | None:
    ahora = time.time()
    intentos = [t for t in _intentos_fallidos[credencial_id] if ahora - t < BLOQUEO_SEGUNDOS]
    _intentos_fallidos[credencial_id] = intentos
    if len(intentos) >= MAX_INTENTOS:
        return BLOQUEO_SEGUNDOS - (ahora - intentos[0])
    return None


def _registrar_fallo(credencial_id: str) -> None:
    _intentos_fallidos[credencial_id].append(time.time())


def _limpiar_intentos(credencial_id: str) -> None:
    _intentos_fallidos.pop(credencial_id, None)


class VerCredencialRequest(BaseModel):
    password: str


class CrearCredencialRequest(BaseModel):
    etiqueta: str
    usuario: str | None = None
    notas: str | None = None
    password: str
    secreto: str


def _requiere_acceso_nexus(request: Request, usuario: str = Depends(auth.requiere_login)) -> str:
    """Igual que auth.requiere_it, pero condicionado al ajuste 'nexus.acceso'
    (Configuracion -> Nexus) en vez de ser siempre obligatorio -- de
    momento por defecto 'it' (lo mas restrictivo) hasta que se decida abrir
    la busqueda a todo el mundo con sesion."""
    if db.get_ajuste("nexus.acceso", "it") == "it" and not request.session.get("es_it"):
        raise auth.NoEsIT()
    return usuario


@router.get("/")
def nexus_home(request: Request, usuario: str = Depends(_requiere_acceso_nexus)):
    return templates.TemplateResponse(request, "nexus.html", {"usuario": usuario, "activo": "nexus"})


@router.get("/stats")
def nexus_stats(usuario: str = Depends(_requiere_acceso_nexus)):
    return JSONResponse(search.get_stats())


@router.get("/search")
def nexus_search(q: str = "", usuario: str = Depends(_requiere_acceso_nexus)):
    """Catalogo documental (fichas + archivos indexados, search.search_catalogo) +
    nuestras propias tareas/proyectos (app_tareas, db.search_tasks) +
    nuestra propia Wiki (db.search_wiki_pages) en la MISMA busqueda --
    "aparte de la documentacion, que busque en nuestra BD", pedido
    explicito del usuario: Nexus solo miraba el catalogo externo, nunca lo
    que ya gestionamos en esta app. Nexus es "el nexo" entre todo lo que
    hay (catalogo externo + tareas + Wiki); la Wiki es quien crea/organiza
    ese contenido -- db.search_tasks/search_wiki_pages ya respetan el
    entorno real/test activo (ver db.py), igual que el buscador de la
    cabecera (main.py::buscar)."""
    resultado = search.search_catalogo(q)
    resultado["tareas"] = db.search_tasks(q.strip()) if q.strip() else []
    # las fichas ya salen como tarjeta propia: no repetirlas en "Nuestra Wiki"
    fichas = {p["id"] for p in resultado["proyectos"]}
    resultado["wiki_propia"] = [w for w in db.search_wiki_pages(q.strip()) if w["page_id"] not in fichas] \
        if q.strip() else []
    return JSONResponse(resultado)


@router.get("/tema")
def nexus_tema(clave: str = "", usuario: str = Depends(_requiere_acceso_nexus)):
    return JSONResponse(search.filtrar_por_tema(clave))


@router.get("/tecnologias")
def nexus_tecnologias(usuario: str = Depends(_requiere_acceso_nexus)):
    return JSONResponse(search.listar_tecnologias())


@router.get("/preview/{archivo_id}")
def nexus_preview(archivo_id: int, usuario: str = Depends(_requiere_acceso_nexus)):
    data = preview.get_preview(archivo_id)
    if data is None:
        return Response(status_code=404)
    return Response(content=data, media_type="image/jpeg")


# ── modo dev y credenciales: siempre IT, ignora el ajuste de arriba ─────────

@router.get("/stats-dev")
def nexus_stats_dev(usuario: str = Depends(auth.requiere_it)):
    return JSONResponse(search.get_stats_dev())


@router.get("/buscar-dev")
def nexus_buscar_dev(q: str = "", usuario: str = Depends(auth.requiere_it)):
    return JSONResponse(search.search_dev(q))


@router.get("/proyecto/{proyecto_id}/credenciales")
def nexus_listar_credenciales(proyecto_id: str, usuario: str = Depends(auth.requiere_it)):
    return JSONResponse(search.listar_credenciales(proyecto_id))


@router.post("/proyecto/{proyecto_id}/credenciales")
def nexus_crear_credencial(proyecto_id: str, body: CrearCredencialRequest, usuario: str = Depends(auth.requiere_it)):
    cred_id = search.crear_credencial(
        proyecto_id, body.etiqueta, body.usuario, body.notas, body.password, body.secreto
    )
    return JSONResponse({"ok": True, "id": cred_id})


@router.post("/credencial/{credencial_id}/ver")
def nexus_ver_credencial(credencial_id: str, body: VerCredencialRequest, usuario: str = Depends(auth.requiere_it)):
    espera = _bloqueado(credencial_id)
    if espera is not None:
        return JSONResponse(
            {"ok": False, "error": f"Demasiados intentos, espera {int(espera) + 1}s"}, status_code=429
        )
    resultado = search.ver_credencial(credencial_id, body.password)
    if not resultado["ok"]:
        _registrar_fallo(credencial_id)
        return JSONResponse({"ok": False, "error": "Contraseña incorrecta"}, status_code=403)
    _limpiar_intentos(credencial_id)
    return JSONResponse(resultado)


@router.post("/credencial/{credencial_id}/borrar")
def nexus_borrar_credencial(credencial_id: str, body: VerCredencialRequest, usuario: str = Depends(auth.requiere_it)):
    espera = _bloqueado(credencial_id)
    if espera is not None:
        return JSONResponse(
            {"ok": False, "error": f"Demasiados intentos, espera {int(espera) + 1}s"}, status_code=429
        )
    if not search.eliminar_credencial(credencial_id, body.password):
        _registrar_fallo(credencial_id)
        return JSONResponse({"ok": False, "error": "Contraseña incorrecta"}, status_code=403)
    _limpiar_intentos(credencial_id)
    return JSONResponse({"ok": True})
