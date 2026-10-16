# -*- coding: utf-8 -*-
"""Conectores de entrada (modulo opcional, MODULO_CONECTORES=1): traen
elementos de sistemas externos y los convierten en tareas. Ver
docs/CONECTORES.md.

Registro de tipos disponibles -- para añadir uno, su clase aqui."""
from .base import Campo, Conector, ConectorError, Elemento
from .mantis import Mantis
from .rest_generico import RestGenerico

TIPOS: dict[str, Conector] = {c.tipo: c() for c in (RestGenerico, Mantis)}

__all__ = ["TIPOS", "Campo", "Conector", "ConectorError", "Elemento"]
