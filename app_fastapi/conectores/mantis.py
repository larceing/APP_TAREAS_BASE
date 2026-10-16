# -*- coding: utf-8 -*-
"""MantisBT como conector: incidencias abiertas de un proyecto -> tareas.

Independiente del modulo Mantis (MODULO_MANTIS, mantis_client.py), que es
mas completo (pool, SLA, vigilante) pero va con una unica cuenta en el .env.
Este solo trae, y puede haber varios (uno por instancia o proyecto de
Mantis), cada uno con su URL y su token."""
import requests

from .base import Campo, Conector, ConectorError, Elemento

TIMEOUT = 20
CERRADAS = {"resolved", "closed"}


class Mantis(Conector):
    tipo = "mantis"
    nombre = "MantisBT"
    descripcion = "Incidencias abiertas de un proyecto de MantisBT (API REST, versión 2.x)."
    campos = [
        Campo("url", "URL de Mantis", "url", True, "La raíz, p. ej. https://mantis.miempresa.com"),
        Campo("token", "Token de API", "secreto", True, "Mantis -> Mi cuenta -> API Tokens. Se guarda cifrado."),
        Campo("proyecto", "Id de proyecto en Mantis", "numero", True),
        Campo("solo_sin_asignar", "Solo las que no tienen a nadie asignado", "si_no", defecto="0"),
    ]

    def traer(self, config: dict) -> list[Elemento]:
        self.validar(config)
        base = config["url"].rstrip("/")
        elementos, pagina = [], 1
        while pagina <= 20:  # tope de seguridad: 2000 incidencias
            try:
                resp = requests.get(
                    f"{base}/api/rest/issues",
                    params={"project_id": config["proyecto"], "page_size": 100, "page": pagina,
                            "select": "id,summary,description,priority,status,handler,due_date"},
                    headers={"Authorization": config["token"]}, timeout=TIMEOUT,
                )
            except requests.RequestException as e:
                raise ConectorError(f"no se pudo conectar con Mantis: {e}") from e
            if resp.status_code in (401, 403):
                raise ConectorError("Mantis rechaza el token")
            if not resp.ok:
                raise ConectorError(f"Mantis respondió HTTP {resp.status_code}")
            incidencias = resp.json().get("issues", [])
            for i in incidencias:
                if (i.get("status") or {}).get("name") in CERRADAS:
                    continue
                asignado = (i.get("handler") or {}).get("name", "")
                if config.get("solo_sin_asignar") == "1" and asignado:
                    continue
                elementos.append(Elemento(
                    str(i["id"]), f"#{i['id']} {i.get('summary', '')}".strip(), i.get("description", ""),
                    f"{base}/view.php?id={i['id']}", (i.get("priority") or {}).get("name", ""),
                    (i.get("due_date") or "")[:10], asignado,
                ))
            if len(incidencias) < 100:
                break
            pagina += 1
        return elementos
