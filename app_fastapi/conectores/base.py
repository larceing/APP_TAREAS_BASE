# -*- coding: utf-8 -*-
"""Contrato de un conector de entrada: lo unico que tiene que saber hacer es
TRAER elementos de un sistema externo y devolverlos ya normalizados
(Elemento). Todo lo demas -- no duplicar, crear la tarea, asignarla, avisar,
publicar en el muro, cuando ejecutarse -- lo hace motor.py igual para todos.

Para añadir un tipo nuevo: un fichero en esta carpeta con una subclase de
Conector (tipo, nombre, descripcion, campos, traer) y una linea en
TIPOS de __init__.py. Ver docs/CONECTORES.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class ConectorError(Exception):
    """Fallo esperable (credenciales, URL, formato): el mensaje se enseña tal
    cual en Configuracion -> Conectores, sin traza."""


@dataclass
class Campo:
    clave: str
    etiqueta: str
    tipo: str = "texto"  # texto | url | secreto | numero | si_no | lista
    obligatorio: bool = False
    ayuda: str = ""
    defecto: str = ""
    opciones: list[tuple[str, str]] = field(default_factory=list)  # solo tipo 'lista'


@dataclass
class Elemento:
    """Un elemento externo listo para convertirse en tarea. id_externo es lo
    que evita duplicados: el mismo id del mismo conector nunca crea dos
    tareas."""
    id_externo: str
    titulo: str
    descripcion: str = ""
    url: str = ""
    prioridad: str = ""  # texto libre del origen; motor.py lo traduce a Alta/Normal/Baja
    fecha_fin: str = ""  # YYYY-MM-DD
    asignado: str = ""  # username o email en el origen; si coincide con un usuario de la app, se le asigna


class Conector:
    tipo = ""
    nombre = ""
    descripcion = ""
    campos: list[Campo] = []

    def traer(self, config: dict) -> list[Elemento]:
        raise NotImplementedError

    def probar(self, config: dict) -> str:
        """Por defecto: traer y contar. Un conector puede hacer algo mas
        barato si su API lo permite."""
        elementos = self.traer(config)
        return f"conexión correcta: {len(elementos)} elemento(s) disponibles"

    def validar(self, config: dict) -> None:
        faltan = [c.etiqueta for c in self.campos if c.obligatorio and not str(config.get(c.clave, "")).strip()]
        if faltan:
            raise ConectorError("faltan campos obligatorios: " + ", ".join(faltan))


def valor_en_ruta(dato, ruta: str):
    """'data.items.0.title' -> dato['data']['items'][0]['title']. Ruta vacia =
    el propio dato. None si algun tramo no existe."""
    actual = dato
    for tramo in [t for t in (ruta or "").split(".") if t]:
        if isinstance(actual, list) and tramo.isdigit() and int(tramo) < len(actual):
            actual = actual[int(tramo)]
        elif isinstance(actual, dict) and tramo in actual:
            actual = actual[tramo]
        else:
            return None
    return actual
