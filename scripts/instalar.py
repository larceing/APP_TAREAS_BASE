# -*- coding: utf-8 -*-
"""Instala la base de datos desde cero: crea la BD (DB_NAME y, si esta
definida, DB_NAME_TEST), el esquema completo, el usuario administrador, el
espacio "Equipo" con el proyecto general y, salvo --sin-demo, los datos de
ejemplo (ver datos_demo.py).

  python scripts/instalar.py                          # pide la contraseña del admin
  python scripts/instalar.py --admin admin --password "..." --sin-demo
  python scripts/instalar.py --recrear [--si]         # BORRA y vuelve a crear

Idempotente: si la BD ya tiene tablas, no la toca (asi Docker puede lanzarlo
en cada arranque) -- salvo --recrear.

Parametros por variable de entorno (para Docker / instalaciones desatendidas):
  INSTALAR_ADMIN, INSTALAR_ADMIN_PASSWORD, INSTALAR_DEMO=0|1,
  DB_ROOT_USER / DB_ROOT_PASSWORD -- solo si el usuario de la app (DB_USER)
  no tiene permiso para crear bases de datos (o aun no existe): se usan para
  crear las BD y el usuario DB_USER, con permisos solo sobre ellas.
"""
import argparse
import getpass
import os
import secrets
import sys
import time
import uuid

from _comun import BASE_DIR, conectar, sentencias_schema
from usuarios import crear_usuario


def _esperar_servidor(segundos: int) -> None:
    """Docker: el contenedor de la app puede arrancar antes de que MariaDB
    acepte conexiones -- se reintenta hasta 'segundos'."""
    root_user = os.getenv("DB_ROOT_USER", "root" if os.getenv("DB_ROOT_PASSWORD") else "")
    limite = time.time() + segundos
    while True:
        try:
            conectar(user=root_user or None, password=os.getenv("DB_ROOT_PASSWORD") if root_user else None).close()
            return
        except Exception as e:
            if time.time() > limite:
                sys.exit(f"No se puede conectar a la base de datos en {os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}: {e}")
            print("· esperando a la base de datos...")
            time.sleep(3)


def _nombre_seguro(nombre: str) -> str:
    if not nombre or not nombre.replace("_", "").isalnum():
        sys.exit(f"Nombre de base de datos no válido: '{nombre}' (solo letras, números y _).")
    return nombre


def _bd_con_tablas(cur, nombre: str) -> bool:
    cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=%s", (nombre,))
    return cur.fetchone()[0] > 0


def _crear_bd(nombre: str, recrear: bool) -> bool:
    """True si hay que instalar (BD nueva o recreada), False si ya estaba."""
    root_user = os.getenv("DB_ROOT_USER", "root" if os.getenv("DB_ROOT_PASSWORD") else "")
    conn = conectar(user=root_user or None, password=os.getenv("DB_ROOT_PASSWORD") if root_user else None)
    try:
        with conn.cursor() as cur:
            if _bd_con_tablas(cur, nombre):
                if not recrear:
                    print(f"· '{nombre}' ya está instalada, no se toca (usa --recrear para empezar de cero).")
                    return False
                cur.execute(f"DROP DATABASE `{nombre}`")
                print(f"· '{nombre}' borrada (--recrear).")
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{nombre}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            if root_user:
                cur.execute("CREATE USER IF NOT EXISTS %s@'%%' IDENTIFIED BY %s",
                            (os.getenv("DB_USER"), os.getenv("DB_PASSWORD", "")))
                cur.execute(f"GRANT ALL PRIVILEGES ON `{nombre}`.* TO %s@'%%'", (os.getenv("DB_USER"),))
        conn.commit()
        return True
    finally:
        conn.close()


def _instalar(nombre: str, admin: str, password: str, demo: bool) -> None:
    conn = conectar(nombre)
    try:
        with conn.cursor() as cur:
            for sentencia in sentencias_schema():
                cur.execute(sentencia)
            admin_id = crear_usuario(cur, admin, password, nombre="Administrador", es_it=True)
            # espacio compartido con el proyecto 'general' -- el que usa la
            # app como destino por defecto (y al que van las tareas de un
            # proyecto que se elimina, ver db.eliminar_proyecto)
            espacio_id = str(uuid.uuid4())[:8]
            cur.execute("INSERT INTO espacios (id, nombre, color, orden, es_personal) VALUES (%s, 'Equipo', '#2563eb', 1, FALSE)",
                        (espacio_id,))
            cur.execute("INSERT INTO espacio_usuarios (espacio_id, user_id, rol) VALUES (%s, %s, 'admin')", (espacio_id, admin_id))
            cur.execute("INSERT INTO proyectos (id, nombre, descripcion, color, estado, tipo, orden, activo, espacio_id) "
                        "VALUES ('general', 'Soporte', 'Peticiones e incidencias del día a día', '#0891b2', 'Activo', "
                        "'kanban', 1, TRUE, %s)", (espacio_id,))
        conn.commit()
    finally:
        conn.close()
    print(f"· '{nombre}': esquema creado, admin '{admin}', espacio 'Equipo' con el proyecto 'Soporte'.")

    # db.py elige la BD por el toggle real/test + DB_NAME: se le apunta a esta
    # BD para que tanto la parte normal como la "siempre real" (recordatorio)
    # escriban aqui, sea la principal o la de pruebas.
    from app_fastapi import db
    os.environ["DB_NAME"] = nombre
    db._entorno_actual = lambda: "real"
    db.get_or_create_espacio_personal(db.get_user_id(admin))
    db.load_board_columns("general")
    if demo:
        import datos_demo
        datos_demo.cargar(lambda: conectar(nombre), admin, password)
        print(f"· '{nombre}': datos de demo cargados (usuarios ana.lopez y carlos.ruiz, misma contraseña que el admin).")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--admin", default=os.getenv("INSTALAR_ADMIN", "admin"))
    ap.add_argument("--password", default=os.getenv("INSTALAR_ADMIN_PASSWORD"))
    ap.add_argument("--sin-demo", action="store_true", default=os.getenv("INSTALAR_DEMO", "1") == "0")
    ap.add_argument("--sin-test", action="store_true", help="no crear DB_NAME_TEST aunque esté definida")
    ap.add_argument("--recrear", action="store_true", help="BORRA las bases de datos existentes y las vuelve a crear")
    ap.add_argument("--si", action="store_true", help="no pedir confirmación con --recrear")
    ap.add_argument("--esperar", type=int, default=0, metavar="SEG", help="reintentar la conexión hasta SEG segundos")
    args = ap.parse_args()

    bases = [_nombre_seguro(os.getenv("DB_NAME", ""))]
    if os.getenv("DB_NAME_TEST") and not args.sin_test:
        bases.append(_nombre_seguro(os.getenv("DB_NAME_TEST")))
    if args.recrear and not args.si:
        if input(f"Se BORRARÁN {', '.join(bases)} si existen. Escribe SI para seguir: ").strip() != "SI":
            sys.exit("Cancelado.")

    if args.esperar:
        _esperar_servidor(args.esperar)
    pendientes = [b for b in bases if _crear_bd(b, args.recrear)]
    if not pendientes:
        return
    password = args.password
    generada = False
    if not password:
        if sys.stdin.isatty():
            password = getpass.getpass(f"Contraseña para el administrador '{args.admin}': ")
        if not password:
            password, generada = secrets.token_urlsafe(12), True
    for nombre in pendientes:
        _instalar(nombre, args.admin, password, demo=not args.sin_demo)

    entorno = BASE_DIR / "data" / "entorno_db.txt"
    entorno.parent.mkdir(parents=True, exist_ok=True)
    if not entorno.exists():
        entorno.write_text("real")
    print(f"\nListo. Entra con el usuario '{args.admin}'" +
          (f" y la contraseña generada: {password}  (cámbiala con scripts/usuarios.py password {args.admin})"
           if generada else "."))


if __name__ == "__main__":
    main()
