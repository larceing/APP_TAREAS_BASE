# -*- coding: utf-8 -*-
"""API REST generica: cualquier endpoint que devuelva una lista JSON. Se
configura sin programar diciendo DONDE esta la lista y QUE campo es cada
cosa (rutas con puntos, p. ej. 'fields.summary')."""
import requests

from .base import Campo, Conector, ConectorError, Elemento, valor_en_ruta

TIMEOUT = 20


class RestGenerico(Conector):
    tipo = "rest"
    nombre = "API REST genérica"
    descripcion = "Cualquier API que devuelva una lista en JSON (GLPI, Jira, un ERP, un script propio...)."
    campos = [
        Campo("url", "URL", "url", True, "Dirección completa que devuelve la lista, con sus filtros en la query."),
        Campo("cabecera", "Cabecera de autenticación", ayuda="Nombre de la cabecera, p. ej. Authorization o X-API-Key. Vacío = sin autenticación.",
              defecto="Authorization"),
        Campo("token", "Valor de la cabecera", "secreto", ayuda="P. ej. 'Bearer abc123'. Se guarda cifrado."),
        Campo("ruta_lista", "Dónde está la lista", ayuda="Ruta dentro del JSON (p. ej. 'data.items'). Vacío = el JSON ya es la lista."),
        Campo("campo_id", "Campo id", obligatorio=True, defecto="id"),
        Campo("campo_titulo", "Campo título", obligatorio=True, defecto="title"),
        Campo("campo_descripcion", "Campo descripción", defecto="description"),
        Campo("campo_url", "Campo enlace", ayuda="Campo con la URL del elemento en el origen."),
        Campo("plantilla_url", "Plantilla de enlace", ayuda="Si el origen no da URL: p. ej. https://soporte.miempresa.com/ticket/{id}"),
        Campo("campo_prioridad", "Campo prioridad"),
        Campo("campo_fecha", "Campo fecha límite", ayuda="Fecha ISO (YYYY-MM-DD...)."),
        Campo("campo_asignado", "Campo asignado", ayuda="Username o email del responsable en el origen."),
    ]

    def traer(self, config: dict) -> list[Elemento]:
        self.validar(config)
        cabeceras = {"Accept": "application/json"}
        if config.get("cabecera") and config.get("token"):
            cabeceras[config["cabecera"]] = config["token"]
        try:
            resp = requests.get(config["url"], headers=cabeceras, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise ConectorError(f"no se pudo conectar: {e}") from e
        if resp.status_code in (401, 403):
            raise ConectorError(f"el origen rechaza la autenticación (HTTP {resp.status_code})")
        if not resp.ok:
            raise ConectorError(f"el origen respondió HTTP {resp.status_code}")
        try:
            datos = resp.json()
        except ValueError as e:
            raise ConectorError("la respuesta no es JSON") from e
        lista = valor_en_ruta(datos, config.get("ruta_lista", ""))
        if not isinstance(lista, list):
            raise ConectorError(f"en '{config.get('ruta_lista') or '(raíz)'}' no hay una lista")

        def campo(item, clave):
            ruta = config.get(clave, "")
            valor = valor_en_ruta(item, ruta) if ruta else None
            return "" if valor is None else str(valor)

        elementos = []
        for item in lista:
            id_externo, titulo = campo(item, "campo_id"), campo(item, "campo_titulo")
            if not id_externo or not titulo:
                continue
            url = campo(item, "campo_url") or (config.get("plantilla_url") or "").replace("{id}", id_externo)
            elementos.append(Elemento(id_externo, titulo, campo(item, "campo_descripcion"), url,
                                      campo(item, "campo_prioridad"), campo(item, "campo_fecha")[:10],
                                      campo(item, "campo_asignado")))
        return elementos
