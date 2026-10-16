# -*- coding: utf-8 -*-
"""Gestion de usuarios en modo AUTH_MODO=local (en modo keycloak los da de
alta Keycloak solos al primer login).

  python scripts/usuarios.py listar
  python scripts/usuarios.py crear ana --nombre "Ana" --apellidos "Ruiz" --email ana@empresa.com [--it] [--password X]
  python scripts/usuarios.py password ana [--password X]
  python scripts/usuarios.py it ana --si | --no
  python scripts/usuarios.py activar ana --si | --no

Sin --password se pide por teclado (sin eco). Actua sobre DB_NAME, o sobre
DB_NAME_TEST con --test.
"""
import argparse
import getpass
import os
import sys

from _comun import conectar

from app_fastapi.auth import hash_contrasena


def _pedir_password(valor: str | None) -> str:
    if valor:
        return valor
    p1 = getpass.getpass("Contraseña: ")
    if len(p1) < 8:
        sys.exit("La contraseña debe tener al menos 8 caracteres.")
    if p1 != getpass.getpass("Repite la contraseña: "):
        sys.exit("No coinciden.")
    return p1


def crear_usuario(cur, username: str, password: str, *, nombre: str = "", apellidos: str = "", email: str = "",
                  es_it: bool = False) -> int:
    """Tambien lo usan instalar.py y datos_demo.py."""
    cur.execute(
        "INSERT INTO auth_user (password, last_login, is_superuser, username, first_name, last_name, email, "
        "is_staff, is_active, date_joined) VALUES (%s, NULL, %s, %s, %s, %s, %s, %s, 1, NOW())",
        (hash_contrasena(password), int(es_it), username, nombre, apellidos, email, int(es_it)),
    )
    return cur.lastrowid


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--test", action="store_true", help="usar DB_NAME_TEST en vez de DB_NAME")
    sub = ap.add_subparsers(dest="orden", required=True)
    sub.add_parser("listar")
    c = sub.add_parser("crear")
    c.add_argument("username"); c.add_argument("--nombre", default=""); c.add_argument("--apellidos", default="")
    c.add_argument("--email", default=""); c.add_argument("--it", action="store_true"); c.add_argument("--password")
    p = sub.add_parser("password"); p.add_argument("username"); p.add_argument("--password")
    for nombre in ("it", "activar"):
        s = sub.add_parser(nombre); s.add_argument("username")
        g = s.add_mutually_exclusive_group(required=True)
        g.add_argument("--si", action="store_true"); g.add_argument("--no", action="store_true")
    args = ap.parse_args()

    conn = conectar(os.getenv("DB_NAME_TEST" if args.test else "DB_NAME"))
    try:
        with conn.cursor() as cur:
            if args.orden == "listar":
                cur.execute("SELECT username, CONCAT(first_name, ' ', last_name), email, is_staff, is_active, "
                            "password LIKE '!%%' FROM auth_user ORDER BY username")
                for u, nombre, email, it, activo, sin_pw in cur.fetchall():
                    marcas = [m for m, v in (("IT", it), ("inactivo", not activo), ("sin contraseña local", sin_pw)) if v]
                    print(f"{u:20} {nombre.strip():25} {email:30} {', '.join(marcas)}")
                return
            if args.orden == "crear":
                crear_usuario(cur, args.username, _pedir_password(args.password), nombre=args.nombre,
                              apellidos=args.apellidos, email=args.email, es_it=args.it)
            elif args.orden == "password":
                n = cur.execute("UPDATE auth_user SET password=%s WHERE username=%s",
                                (hash_contrasena(_pedir_password(args.password)), args.username))
                if not n:
                    sys.exit(f"No existe el usuario '{args.username}'.")
            else:
                columna = "is_staff" if args.orden == "it" else "is_active"
                if not cur.execute(f"UPDATE auth_user SET {columna}=%s WHERE username=%s", (int(args.si), args.username)):
                    sys.exit(f"No existe el usuario '{args.username}' (o ya estaba así).")
        conn.commit()
        print("Hecho.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
