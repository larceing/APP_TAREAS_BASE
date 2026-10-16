# -*- coding: utf-8 -*-
"""Datos de ejemplo para que la app se pueda enseñar nada mas instalarla:
una empresa ficticia, tres usuarios, un espacio compartido con dos proyectos
(Kanban y Scrum con sprint), tareas en todas las columnas y con fechas
alrededor de hoy, notas, una pagina de wiki, mensajes en el muro, notas del
Buzon y dias especiales en el calendario.

Lo llama instalar.py (salvo con --sin-demo). Va por las MISMAS funciones de
la app (db.py / acciones.py / wiki_store.py) que usa la web, no por SQL a
mano, para que lo cargado sea exactamente lo que la app habria creado.

Usuarios de demo (contraseña = la del admin que se pase al instalador):
  ana.lopez  (IT)   -- tecnica de sistemas
  carlos.ruiz       -- usuario de negocio, Editor del espacio
"""
import uuid
from datetime import date, timedelta

from usuarios import crear_usuario

from app_fastapi import acciones, db, wiki_store


def _id() -> str:
    return str(uuid.uuid4())[:8]


def _dia(delta: int) -> str:
    return (date.today() + timedelta(days=delta)).isoformat()


def _parrafos(*textos) -> dict:
    bloques = []
    for t in textos:
        if t.startswith("## "):
            bloques.append({"type": "header", "data": {"text": t[3:], "level": 2}})
        elif t.startswith("- "):
            bloques.append({"type": "list", "data": {"style": "unordered", "items": [x[2:] for x in t.split("\n")]}})
        else:
            bloques.append({"type": "paragraph", "data": {"text": t}})
    return {"time": 0, "blocks": bloques, "version": "2.29.0"}


def cargar(conn_cursor_factory, admin_username: str, password: str) -> None:
    """conn_cursor_factory: funcion que devuelve una conexion a la BD destino
    (para crear los usuarios con su hash; el resto va por db.py, que ya
    apunta a esa misma BD -- ver instalar.py)."""
    conn = conn_cursor_factory()
    try:
        with conn.cursor() as cur:
            ana = crear_usuario(cur, "ana.lopez", password, nombre="Ana", apellidos="López",
                                email="ana.lopez@empresa-demo.local", es_it=True)
            carlos = crear_usuario(cur, "carlos.ruiz", password, nombre="Carlos", apellidos="Ruiz",
                                   email="carlos.ruiz@empresa-demo.local")
        conn.commit()
    finally:
        conn.close()
    admin = db.get_user_id(admin_username)
    for uid in (admin, ana, carlos):
        db.get_or_create_espacio_personal(uid)

    # ── catalogos ──
    db.crear_empresa("emp-demo", "Empresa Demo", "Empresa Demo S.L.", "#2563eb", "", "empresa-demo.local")
    db.crear_sistema("sis-erp", "ERP", "emp-demo", "#2563eb")
    db.crear_sistema("sis-correo", "Correo", "", "#0891b2")
    db.crear_sistema("sis-infra", "Infraestructura", "", "#6b7280")
    db.crear_sistema("sis-ofimatica", "Ofimática", "", "#16a34a")
    db.crear_iniciativa("ini-ciber", "Ciberseguridad", "Ana López", "#dc2626")
    db.crear_iniciativa("ini-onboarding", "Altas de personal", "", "#7c3aed")

    # ── espacio compartido "Equipo IT" con el proyecto general + uno Scrum ──
    espacio = db.get_proyecto("general")["espacio_id"]
    db.agregar_miembro_espacio(espacio, ana, "admin")
    db.agregar_miembro_espacio(espacio, carlos, "editor")
    db.crear_proyecto("migracion-correo", "Migración de correo", "Paso del correo local a la nube, por fases.",
                      "Ana López", "#7c3aed", "Activo", "scrum", _dia(-14), _dia(40), espacio_id=espacio)
    db.load_board_columns("migracion-correo")  # crea las 4 columnas por defecto
    sprint = db.crear_sprint("migracion-correo", "Sprint 1", _dia(-7), _dia(7), "activo",
                             "Buzones piloto migrados y validados")

    actor_ana = acciones.Actor(ana, "Ana López", "ana.lopez", es_it=True)
    actor_admin = acciones.Actor(admin, admin_username, admin_username, es_it=True)
    actor_carlos = acciones.Actor(carlos, "Carlos Ruiz", "carlos.ruiz")

    soporte = [
        # (titulo, estado, prioridad, categoria, sistema, asignado, inicio, fin, descripcion)
        ("No arranca el portátil de recepción", "Pendiente", "Alta", "cat-incidencia", "sis-infra", ana, 0, 0,
         "Pantalla negra tras el logo. Probar arranque en modo seguro."),
        ("Alta de usuario: nueva incorporación en Compras", "Pendiente", "Normal", "cat-peticion", "sis-ofimatica",
         carlos, 0, 2, "Cuenta, correo, licencia ofimática y acceso al ERP."),
        ("Error al imprimir albaranes desde el ERP", "En curso", "Alta", "cat-incidencia", "sis-erp", ana, -2, 1,
         "Solo pasa con la impresora de almacén."),
        ("Renovar certificado SSL de la intranet", "En curso", "Normal", "cat-infra", "sis-infra", admin, -5, 3, ""),
        ("Esperando presupuesto del proveedor de cableado", "En espera", "Baja", "cat-peticion", "sis-infra", admin,
         -10, 10, "Pedido por correo el lunes."),
        ("Documentar procedimiento de copias de seguridad", "Pendiente", "Normal", "cat-doc", "sis-infra", ana, 1, 7, ""),
        ("Cambiar tóner de la impresora de planta 2", "Hecha", "Normal", "cat-incidencia", "sis-ofimatica", carlos,
         -3, -3, ""),
        ("Revisar accesos de usuarios dados de baja", "Pendiente", "Alta", "cat-peticion", "sis-erp", ana, -1, -1,
         "Vencida a propósito: así se ve una tarea atrasada."),
    ]
    for titulo, estado, prio, cat, sis, asig, ini, fin, desc in soporte:
        acciones.crear_tarea(actor_admin, "general", titulo, estado=estado, prioridad=prio, categoria=cat,
                             sistema_id=sis, empresa_id="emp-demo", asignado_a=asig, fecha_inicio=_dia(ini),
                             fecha_fin=_dia(fin), descripcion=desc, iniciativa_id="ini-ciber" if "accesos" in titulo else "")

    migracion = [
        ("Inventario de buzones y tamaños", "Hecha", True, ana, -7, -5),
        ("Configurar dominio en el proveedor nube", "Hecha", True, ana, -6, -4),
        ("Migrar 5 buzones piloto", "En curso", True, ana, -3, 2),
        ("Guía de usuario: nuevo correo en el móvil", "Pendiente", True, carlos, 0, 5),
        ("Migración del resto de buzones", "Pendiente", False, ana, 8, 20),
        ("Apagar el servidor de correo antiguo", "Pendiente", False, admin, 25, 30),
    ]
    for titulo, estado, en_sprint, asig, ini, fin in migracion:
        acciones.crear_tarea(actor_ana, "migracion-correo", titulo, estado=estado, sistema_id="sis-correo",
                             asignado_a=asig, fecha_inicio=_dia(ini), fecha_fin=_dia(fin),
                             sprint_id=sprint if en_sprint else "",
                             subtareas=acciones.subtareas_json([{"texto": "Preparar", "hecho": True}, "Ejecutar"])
                             if estado == "En curso" else "")

    # ── muro, buzon ──
    acciones.escribir_en_muro(actor_ana, "Esta semana migramos los 5 buzones piloto. Si notáis algo raro en el "
                              "correo, decídmelo por aquí.", proyecto_id="migracion-correo")
    acciones.escribir_en_muro(actor_carlos, "Gracias, ya tengo el correo nuevo en el móvil y va perfecto.",
                              proyecto_id="migracion-correo")
    acciones.escribir_en_muro(actor_admin, "Recordad: las peticiones nuevas, como tarea en Soporte o por el Buzón.",
                              espacio_id=espacio)
    acciones.enviar_nota(actor_carlos, admin, "¿Puedes revisar el acceso de la nueva incorporación al ERP antes del "
                         "viernes?", vence_en=_dia(3), aviso_cantidad=1, aviso_unidad="dias")
    acciones.enviar_nota(actor_ana, admin, "Te dejo apuntado: el certificado SSL caduca a final de mes.")

    # ── notas, wiki, calendario, recordatorio ──
    db.crear_nota(_id(), "Teléfonos útiles", "Proveedor de internet: 900 000 000\nMantenimiento edificio: ext. 210",
                  "#fef3c7")
    db.crear_nota(_id(), "Ideas", "- Encuesta de satisfacción del soporte\n- Catálogo de servicios", "#dbeafe")
    db.crear_nota(_id(), "Reunión de seguimiento", "Revisar avance de la migración y el SLA del mes.", "#dcfce7",
                  agenda_fecha=_dia(0))
    portada = wiki_store.create_page("general", "Cómo pedir soporte", icon="🛟", content=_parrafos(
        "## Canales",
        "- Crear una tarea en el proyecto Soporte\n- Mandar una nota por el Buzón al equipo de IT",
        "## Qué incluir",
        "Qué ha pasado, desde cuándo, a quién afecta y, si se puede, una captura de pantalla."))
    backups = wiki_store.create_page("general", "Copias de seguridad", parent_id=portada["page_id"], icon="💾", content=_parrafos(
        "Las copias de la base de datos se hacen desde Configuración → Copias de seguridad.",
        "## Info para desarrolladores",
        "Volcado con mariadb-dump; se guardan en data/backups_bd/."))
    # ficha de Nexus (se ve al activar MODULO_NEXUS): la pagina + metadatos + relaciones en el grafo
    conn = conn_cursor_factory()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO wiki_pagina_metadata (pagina_id, alias, codigo, tecnologias, estado, rol) "
                        "VALUES (%s, 'Backups, copias', 'SRV-BKP', 'MariaDB, mariadb-dump', 'activo', 'tecnico')",
                        (backups["page_id"],))
        conn.commit()
    finally:
        conn.close()
    db.nexus_relacionar(("wiki_pagina", backups["page_id"]), ("sistema", "sis-infra"))
    db.nexus_relacionar(("sistema", "sis-infra"), ("proyecto", "general"))
    db.crear_dia_especial(_id(), "tipo:tde-festivo", _dia(12), _dia(12), "Festivo local", "")
    db.crear_dia_especial(_id(), "tipo:tde-vacaciones", _dia(20), _dia(24), "Vacaciones Ana", "")
    db.crear_dia_especial(_id(), "tipo:tde-aviso", _dia(2), _dia(2), "Corte de luz programado 8:00-9:00", "")
    db.crear_dia_especial(_id(), "empresa:emp-demo", _dia(0), _dia(0), "", "")
    for texto, categoria in (("Levántate y camina un par de minutos.", "Movimiento"),
                             ("Aparta la vista de la pantalla: mira algo a 6 metros durante 20 segundos.", "Vista"),
                             ("Revisa tu postura: espalda apoyada y hombros relajados.", "Postura")):
        db.crear_recordatorio_mensaje(texto, categoria, real=True)
    db.nexus_sincronizar()
