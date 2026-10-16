# -*- coding: utf-8 -*-
"""Curar el catalogo de Nexus mientras no haya pantalla para ello (ver
docs/NEXUS_PLAN_DE_ACCION.md): convertir paginas de wiki en fichas, enlazar
archivos/carpetas indexados a una ficha y relacionar entidades en el grafo.

  python scripts/nexus_fichas.py paginas                      # paginas de wiki con su id
  python scripts/nexus_fichas.py ficha <pagina_id> --alias "ERP, Gestion" --codigo SIS-01 \\
         --tecnologias "SQL Server, IIS" --estado activo --rol negocio
  python scripts/nexus_fichas.py enlazar <pagina_id> --carpeta "documentacion/ERP"
  python scripts/nexus_fichas.py enlazar <pagina_id> --archivo "documentacion/ERP/manual.pdf"
  python scripts/nexus_fichas.py relacionar wiki_pagina:<id> sistema:sis-erp
  python scripts/nexus_fichas.py relacionados wiki_pagina:<id>

Las rutas de --carpeta/--archivo son las relativas que guarda el indexador
(nombre de la carpeta indexada + subruta, con '/'). Tipos para relacionar:
proyecto, sistema, empresa, wiki_pagina, nota, whiteboard, credencial.
--test trabaja sobre DB_NAME_TEST.
"""
import argparse
import sys

import _comun  # noqa: F401  (carga el .env y el path de la app)

from app_fastapi import db


def _entidad(texto: str) -> tuple:
    tipo, _, entidad_id = texto.partition(":")
    if tipo not in db.NEXUS_TIPOS or not entidad_id:
        sys.exit(f"'{texto}' no es tipo:id (tipos: {', '.join(db.NEXUS_TIPOS)})")
    return tipo, entidad_id


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--test", action="store_true")
    sub = ap.add_subparsers(dest="orden", required=True)
    sub.add_parser("paginas")
    f = sub.add_parser("ficha")
    f.add_argument("pagina_id")
    for campo in ("alias", "codigo", "tecnologias", "estado", "rol"):
        f.add_argument(f"--{campo}", default="")
    e = sub.add_parser("enlazar")
    e.add_argument("pagina_id")
    g = e.add_mutually_exclusive_group(required=True)
    g.add_argument("--carpeta")
    g.add_argument("--archivo")
    r = sub.add_parser("relacionar")
    r.add_argument("a")
    r.add_argument("b")
    v = sub.add_parser("relacionados")
    v.add_argument("entidad")
    args = ap.parse_args()

    db._entorno_actual = lambda: "test" if args.test else "real"
    conn = db.connect()
    try:
        with conn.cursor() as cur:
            if args.orden == "paginas":
                cur.execute("SELECT w.id, w.proyecto_id, w.titulo, m.pagina_id IS NOT NULL FROM wiki_paginas w "
                            "LEFT JOIN wiki_pagina_metadata m ON m.pagina_id = w.id ORDER BY w.proyecto_id, w.titulo")
                for pid, proyecto, titulo, es_ficha in cur.fetchall():
                    print(f"{pid:10} {proyecto:20} {'[ficha] ' if es_ficha else ''}{titulo}")
                return
            if args.orden in ("ficha", "enlazar"):
                cur.execute("SELECT titulo FROM wiki_paginas WHERE id=%s", (args.pagina_id,))
                if not cur.fetchone():
                    sys.exit(f"No existe la página de wiki '{args.pagina_id}' (mira 'paginas').")
            if args.orden == "ficha":
                cur.execute(
                    "INSERT INTO wiki_pagina_metadata (pagina_id, alias, codigo, tecnologias, estado, rol) "
                    "VALUES (%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE alias=VALUES(alias), codigo=VALUES(codigo), "
                    "tecnologias=VALUES(tecnologias), estado=VALUES(estado), rol=VALUES(rol)",
                    (args.pagina_id, args.alias, args.codigo, args.tecnologias, args.estado, args.rol),
                )
            elif args.orden == "enlazar":
                tabla, ruta = ("nexus_carpetas", args.carpeta) if args.carpeta else ("nexus_archivos", args.archivo)
                cur.execute(f"SELECT id FROM {tabla} WHERE ruta_relativa=%s", (ruta.strip("/"),))
                fila = cur.fetchone()
                if not fila:
                    sys.exit(f"'{ruta}' no está indexada (¿has lanzado scripts/nexus_indexar.py?).")
                columna = "carpeta_id" if args.carpeta else "archivo_id"
                cur.execute(f"SELECT 1 FROM nexus_referencias WHERE wiki_pagina_id=%s AND {columna}=%s",
                            (args.pagina_id, fila[0]))
                if not cur.fetchone():
                    cur.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM nexus_referencias")
                    cur.execute(f"INSERT INTO nexus_referencias (id, wiki_pagina_id, {columna}) VALUES (%s,%s,%s)",
                                (cur.fetchone()[0], args.pagina_id, fila[0]))
        conn.commit()
    finally:
        conn.close()

    if args.orden == "relacionar":
        nueva = db.nexus_relacionar(_entidad(args.a), _entidad(args.b))
        print("Relacionados." if nueva else "Ya estaban relacionados.")
        return
    if args.orden == "relacionados":
        for r in db.nexus_relacionados(*_entidad(args.entidad)):
            print(f"{r['tipo']:12} {r['entidad_id']:12} {'directo' if r['directo'] else 'indirecto'}"
                  f"{'  (representante)' if r['es_representante'] else ''}")
        return
    print("Hecho.")


if __name__ == "__main__":
    main()
