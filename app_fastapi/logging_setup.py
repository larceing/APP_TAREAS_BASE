# -*- coding: utf-8 -*-
"""4 logs de uso, cada uno en su propio archivo rotado (5 MB x 5 copias) en
app_fastapi/logs/ (gitignored, igual que data/entorno_db.txt) -- pedido por
el usuario al ver que la app no dejaba rastro de nada:

- accesos.log  -- cada peticion (usuario, ruta, metodo, status, duracion).
- cambios.log  -- solo las peticiones POST (crear/editar/borrar/toggle/
  importar...) -- en esta app casi toda mutacion de datos es un POST a una
  ruta con nombre propio (ej. "/notas/nueva/", "/configuracion/empresa/
  <id>/toggle/"), asi que la propia ruta ya dice que accion fue -- mas
  simple que instrumentar a mano cada endpoint uno a uno.
- errores.log  -- excepciones no controladas + los "except" que ya existian
  en cada router (fallos de Mantis, de mysqldump, etc.), redirigidos aqui
  en vez de perderse en el JSON de error que ve el usuario.
- queries.log  -- cada sentencia SQL que pasa por db.py (via un cursor de
  PyMySQL que loguea antes de ejecutar, ver connect() en db.py) -- utilismo
  para depurar, pero es el que mas crece (registra tambien los SELECT).

No tiene nada que ver con el logging de Django (settings.LOGGING) -- es
propio de esta v2, archivos de texto plano, sin tocar la base de datos."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)


# archivo:funcion:linea de quien llamo al logger (no del propio logging_setup.py)
# -- para saber de un vistazo si el origen fue mantis/configuracion/calendario/
# etc. sin tener que escribirlo a mano en cada mensaje. Los sitios que llaman
# con stacklevel=2 (ver _CursorConLog.execute en db.py) apuntan un nivel mas
# arriba, a quien pidio la query, no a la propia funcion execute().
_FORMATO = "%(asctime)s | %(module)s:%(funcName)s:%(lineno)d | %(message)s"


def _crear_logger(nombre: str, archivo: str) -> logging.Logger:
    logger = logging.getLogger(f"app_fastapi.{nombre}")
    logger.setLevel(logging.INFO)
    if not logger.handlers:  # evita duplicar handlers si el modulo se importa mas de una vez
        handler = RotatingFileHandler(LOGS_DIR / archivo, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
        handler.setFormatter(logging.Formatter(_FORMATO, datefmt="%Y-%m-%d %H:%M:%S"))
        logger.addHandler(handler)
        logger.propagate = False
    return logger


accesos = _crear_logger("accesos", "accesos.log")
cambios = _crear_logger("cambios", "cambios.log")
errores = _crear_logger("errores", "errores.log")
queries = _crear_logger("queries", "queries.log")
escritorio = _crear_logger("escritorio", "escritorio.log")  # Recordatorio + Vigilante de Mantis
