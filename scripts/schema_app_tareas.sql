-- Esquema completo de la app. Lo ejecuta scripts/instalar.py sobre una base
-- de datos ya creada (el instalador hace el CREATE DATABASE con el nombre de
-- DB_NAME / DB_NAME_TEST) -- no lleva USE ni nombre de base fijo.

-- ────────────────────────────────────────────────────────────
-- auth_user: usuarios de la app. Mismo formato que la tabla de Django
-- (la app empezo en Django: asi una instalacion que venga de alli conserva
-- usuarios y contraseñas). password = hash pbkdf2_sha256 (ver auth.py) o
-- '!...' = sin contraseña local (usuarios que entran por Keycloak).
-- is_staff = es de IT (acceso a Configuracion, Aviso en los muros...).
-- Sin DEFAULTs a proposito, igual que la de Django: todo INSERT debe dar
-- todas las columnas.
CREATE TABLE auth_user (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    password     VARCHAR(128) NOT NULL,
    last_login   DATETIME(6) NULL,
    is_superuser TINYINT(1) NOT NULL,
    username     VARCHAR(150) NOT NULL UNIQUE,
    first_name   VARCHAR(150) NOT NULL,
    last_name    VARCHAR(150) NOT NULL,
    email        VARCHAR(254) NOT NULL,
    is_staff     TINYINT(1) NOT NULL,
    is_active    TINYINT(1) NOT NULL,
    date_joined  DATETIME(6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
-- espacios: workspace de un proyecto -- personal (uno por usuario, siempre
-- existe, no se puede desactivar/borrar, es_personal=TRUE + owner_id) o
-- compartido (es_personal=FALSE, sin owner_id, con miembros en
-- espacio_usuarios). "Como mucho un espacio personal por usuario" se valida
-- en db.py::get_or_create_espacio_personal, no aqui -- un indice unico
-- parcial (WHERE es_personal=1) no existe en MariaDB de forma portable.
CREATE TABLE espacios (
    id          VARCHAR(32)  PRIMARY KEY,
    nombre      VARCHAR(150) NOT NULL,
    color       VARCHAR(7)   NOT NULL DEFAULT '#6b7280',
    orden       INT NOT NULL DEFAULT 0,
    activo      BOOLEAN NOT NULL DEFAULT TRUE,
    es_personal BOOLEAN NOT NULL DEFAULT FALSE,
    owner_id    INT NULL,
    -- Permisos granulares de un Editor dentro de este espacio (Admin siempre
    -- los salta, Lector nunca puede nada de esto de por si) -- todos por
    -- defecto TRUE (comportamiento de siempre) hasta que un Admin restrinja
    -- alguno a proposito. Los dos "_ajenas" no aplican si la tarea esta
    -- asignada al propio Editor (ver db.py::puede_actuar_en_proyecto).
    editores_mueven_tareas_ajenas      BOOLEAN NOT NULL DEFAULT TRUE,
    editores_eliminan_tareas_ajenas    BOOLEAN NOT NULL DEFAULT TRUE,
    editores_gestionan_columnas        BOOLEAN NOT NULL DEFAULT TRUE,
    editores_editan_apariencia         BOOLEAN NOT NULL DEFAULT TRUE,
    editores_gestionan_documentos_wiki BOOLEAN NOT NULL DEFAULT TRUE,
    FOREIGN KEY (owner_id) REFERENCES auth_user(id) ON DELETE CASCADE,
    INDEX idx_espacio_owner (owner_id)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE espacio_usuarios (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    espacio_id VARCHAR(32) NOT NULL,
    user_id    INT NOT NULL,
    -- admin: gestiona miembros/roles y edita/desactiva el espacio.
    -- editor: crea/edita/borra proyectos dentro del espacio (rol por
    -- defecto para altas nuevas). lector: solo ve, ninguna mutacion pasa.
    -- Quien crea un espacio compartido entra como admin (ver
    -- db.py::crear_espacio) -- antes de esta columna no habia ningun
    -- "dueno" de un espacio compartido, cualquier logueado podia
    -- editarlo/desactivarlo.
    rol        ENUM('admin','editor','lector') NOT NULL DEFAULT 'editor',
    creado_en  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_espacio_usuario (espacio_id, user_id),
    FOREIGN KEY (espacio_id) REFERENCES espacios(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES auth_user(id) ON DELETE CASCADE,
    INDEX idx_espacio_usuarios_espacio (espacio_id),
    INDEX idx_espacio_usuarios_user (user_id)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
CREATE TABLE proyectos (
    id            VARCHAR(32)  PRIMARY KEY,
    nombre        VARCHAR(200) NOT NULL,
    descripcion   TEXT         NOT NULL DEFAULT '',
    responsable   VARCHAR(200) NOT NULL DEFAULT '',
    color         VARCHAR(7)   NOT NULL DEFAULT '#2563eb',
    estado        ENUM('Activo','En pausa','Cerrado') NOT NULL DEFAULT 'Activo',
    tipo          ENUM('kanban','scrum') NOT NULL DEFAULT 'kanban',
    -- espacio (workspace) al que pertenece -- NULL hasta asignarlo a mano --
    -- borrar el espacio nunca borra el proyecto (ON DELETE SET NULL).
    espacio_id    VARCHAR(32)  NULL,
    fecha_inicio  DATE NULL,
    fecha_fin     DATE NULL,
    orden         INT NOT NULL DEFAULT 0,
    activo        BOOLEAN NOT NULL DEFAULT TRUE,
    -- si TRUE, una tarea de este proyecto no puede moverse a una columna
    -- es_done (columnas_tablero) mientras le queden subtareas sin marcar
    -- como hechas -- ver core/views.py::_bloquea_cierre_por_subtareas.
    requiere_subtareas_completas BOOLEAN NOT NULL DEFAULT FALSE,
    FOREIGN KEY (espacio_id) REFERENCES espacios(id) ON DELETE SET NULL,
    INDEX idx_proyecto_orden (orden),
    INDEX idx_proyecto_espacio (espacio_id)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
-- proyecto_id ahora NULLABLE: una categoria con proyecto_id=NULL es GLOBAL
-- (se gestiona desde /configuracion/, no por proyecto). Las filas viejas
-- con proyecto_id real son anteriores a la reorganizacion Empresa/Sistema
-- (2026-07-31) y se retiran tras el re-etiquetado de tareas existentes.
CREATE TABLE categorias (
    id            VARCHAR(32)  PRIMARY KEY,
    proyecto_id   VARCHAR(32)  NULL,
    nombre        VARCHAR(150) NOT NULL,
    color         VARCHAR(7)   NOT NULL DEFAULT '#6b7280',
    orden         INT NOT NULL DEFAULT 0,
    activo        BOOLEAN NOT NULL DEFAULT TRUE,
    FOREIGN KEY (proyecto_id) REFERENCES proyectos(id) ON DELETE CASCADE,
    INDEX idx_cat_proyecto (proyecto_id)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
-- empresas/sistemas/iniciativas: siempre globales, gestionadas desde
-- /configuracion/. Ver memoria del proyecto (project_reorg_sistema_categoria)
-- para el porque de estas 3 dimensiones nuevas.
CREATE TABLE empresas (
    id            VARCHAR(32)  PRIMARY KEY,
    nombre        VARCHAR(150) NOT NULL,
    nombre_fiscal VARCHAR(200) NOT NULL DEFAULT '',
    color         VARCHAR(7)   NOT NULL DEFAULT '#6b7280',
    orden         INT NOT NULL DEFAULT 0,
    activo        BOOLEAN NOT NULL DEFAULT TRUE,
    -- id del proyecto de Mantis que corresponde a esta empresa (opcional) --
    -- ver core/mantis_client.py. Antes vivia hardcodeado como constante de
    -- codigo (POOL_PROJECT_ID/EMPRESA_PROJECT_NAMES), lo que obligaba a tocar
    -- codigo si Mantis reorganizaba ids o se sumaba una empresa nueva.
    mantis_project_id INT NULL,
    -- dominio de correo de esta empresa (opcional, ej. "miempresa.com") -- solo
    -- para SUGERIR la empresa de una incidencia de Mantis sin triar comparando
    -- el dominio del reportero, nunca se aplica en silencio (ver views.py)
    dominio_email VARCHAR(120) NOT NULL DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE sistemas (
    id            VARCHAR(32)  PRIMARY KEY,
    nombre        VARCHAR(100) NOT NULL,
    empresa_id    VARCHAR(32)  NULL,
    color         VARCHAR(7)   NOT NULL DEFAULT '#6b7280',
    orden         INT NOT NULL DEFAULT 0,
    activo        BOOLEAN NOT NULL DEFAULT TRUE,
    FOREIGN KEY (empresa_id) REFERENCES empresas(id) ON DELETE SET NULL,
    INDEX idx_sistema_empresa (empresa_id)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE iniciativas (
    id            VARCHAR(32)  PRIMARY KEY,
    nombre        VARCHAR(150) NOT NULL,
    responsable   VARCHAR(200) NOT NULL DEFAULT '',
    color         VARCHAR(7)   NOT NULL DEFAULT '#6b7280',
    activo        BOOLEAN NOT NULL DEFAULT TRUE
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
-- tipos_dia_especial: catalogo editable (Configuracion -> Calendario) de los
-- tipos de anotacion/banner/sede-manual del Calendario. 'categoria' es fija
-- en codigo (CATEGORIAS_TIPO_DIA_ESPECIAL en core/models.py: sede/anotacion/
-- banner) y controla COMO se pinta, no QUE tipos existen -- eso ya es
-- editable aqui. Las "Sede <empresa>" NO son filas de esta tabla: se
-- generan solas a partir de las Empresas activas (ver dia_especial_new en
-- views.py) -- solo "Teletrabajo" (sede sin empresa) vive aqui como fila
-- categoria='sede'. Ver memoria feature_calendario_dias_especiales.
CREATE TABLE tipos_dia_especial (
    id            VARCHAR(32)  PRIMARY KEY,
    nombre        VARCHAR(100) NOT NULL,
    categoria     ENUM('sede','anotacion','banner') NOT NULL,
    color         VARCHAR(7)   NOT NULL DEFAULT '#6b7280',
    orden         INT NOT NULL DEFAULT 0,
    activo        BOOLEAN NOT NULL DEFAULT TRUE,
    -- solo aplica si categoria='banner': banner rojo/solido (urgente) vs
    -- pastel/tranquilo -- asi anadir un tipo de banner nuevo no requiere
    -- tocar codigo para decidir su peso visual.
    urgente       BOOLEAN NOT NULL DEFAULT FALSE,
    -- si los dias marcados con este tipo cuentan como no laborables para el
    -- SLA general (core/views.py::festivos_dates) -- antes el SLA buscaba el
    -- tipo "Festivo" por su id fijo en codigo, asi que renombrarlo/borrarlo
    -- rompia el calculo sin avisar.
    cuenta_para_sla BOOLEAN NOT NULL DEFAULT FALSE
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- dias_especiales: anotaciones del Calendario. Exactamente uno de tipo_id/
-- empresa_id esta relleno por fila (tipo_id para Anotacion/Banner/Teletrabajo,
-- empresa_id para una Sede ligada a una Empresa real -- asi el nombre/color
-- de la sede sigue a la Empresa aunque se renombre, no se duplica texto).
CREATE TABLE dias_especiales (
    id            VARCHAR(32)  PRIMARY KEY,
    tipo_id       VARCHAR(32)  NULL,
    empresa_id    VARCHAR(32)  NULL,
    fecha_inicio  DATE NOT NULL,
    fecha_fin     DATE NOT NULL,
    nota          VARCHAR(300) NOT NULL DEFAULT '',
    color         VARCHAR(7)   NOT NULL DEFAULT '#6b7280',
    FOREIGN KEY (tipo_id)    REFERENCES tipos_dia_especial(id) ON DELETE CASCADE,
    FOREIGN KEY (empresa_id) REFERENCES empresas(id)           ON DELETE CASCADE,
    INDEX idx_dia_especial_fechas (fecha_inicio, fecha_fin)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
CREATE TABLE columnas_tablero (
    id            VARCHAR(32)  PRIMARY KEY,
    proyecto_id   VARCHAR(32)  NOT NULL,
    nombre        VARCHAR(100) NOT NULL,
    orden         INT NOT NULL DEFAULT 0,
    es_done       BOOLEAN NOT NULL DEFAULT FALSE,
    color         VARCHAR(7)   NOT NULL DEFAULT '#6b7280',
    max_tareas    INT NOT NULL DEFAULT 0,
    FOREIGN KEY (proyecto_id) REFERENCES proyectos(id) ON DELETE CASCADE,
    INDEX idx_col_proyecto (proyecto_id)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
CREATE TABLE hitos (
    id            VARCHAR(32)  PRIMARY KEY,
    proyecto_id   VARCHAR(32)  NOT NULL,
    nombre        VARCHAR(200) NOT NULL,
    fecha         DATE NULL,
    completado    BOOLEAN NOT NULL DEFAULT FALSE,
    FOREIGN KEY (proyecto_id) REFERENCES proyectos(id) ON DELETE CASCADE,
    INDEX idx_hito_proyecto (proyecto_id)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
CREATE TABLE sprints (
    id            VARCHAR(32)  PRIMARY KEY,
    proyecto_id   VARCHAR(32)  NOT NULL,
    nombre        VARCHAR(150) NOT NULL,
    numero        INT NOT NULL DEFAULT 1,
    fecha_inicio  DATE NULL,
    fecha_fin     DATE NULL,
    estado        ENUM('planificado','activo','cerrado') NOT NULL DEFAULT 'planificado',
    objetivo      TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (proyecto_id) REFERENCES proyectos(id) ON DELETE CASCADE,
    INDEX idx_sprint_proyecto (proyecto_id),
    INDEX idx_sprint_estado (estado)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
CREATE TABLE tareas (
    id               VARCHAR(32)  PRIMARY KEY,
    proyecto_id      VARCHAR(32)  NOT NULL,
    categoria_id     VARCHAR(32)  NULL,
    empresa_id       VARCHAR(32)  NULL,
    sistema_id       VARCHAR(32)  NULL,
    iniciativa_id    VARCHAR(32)  NULL,
    titulo           VARCHAR(500) NOT NULL,
    -- NO es un ENUM fijo: el estado sigue el nombre de la columna del tablero
    -- (columnas_tablero.nombre), que el usuario puede renombrar libremente
    -- ademas usa el valor especial 'OUTCAST' cuando se borra la columna
    -- de una tarea sin reasignarla (ver core/views.py column_delete/column_rename).
    estado           VARCHAR(100) NOT NULL DEFAULT 'Pendiente',
    descripcion      TEXT NOT NULL DEFAULT '',
    proximo_paso     TEXT NOT NULL DEFAULT '',
    prioridad        ENUM('Normal','Alta','Baja') NOT NULL DEFAULT 'Normal',
    orden            INT NOT NULL DEFAULT 0,
    borrada          BOOLEAN NOT NULL DEFAULT FALSE,
    sprint_id        VARCHAR(32) NULL,
    fecha_inicio     DATE NULL,
    fecha_fin        DATE NULL,
    iniciada_en      DATETIME NULL,
    cerrada_en       DATETIME NULL,
    subtareas        JSON NULL,
    tiempo_estimado  DECIMAL(6,2) NULL,
    tiempo_real      DECIMAL(6,2) NULL,
    anclada          BOOLEAN NOT NULL DEFAULT FALSE,
    -- FK a reuniones_calendario añadida mas abajo con ALTER TABLE (esa tabla
    -- se crea despues en este mismo fichero, no se puede referenciar aqui).
    reunion_id       VARCHAR(64) NULL,
    -- id de la incidencia de Mantis de origen (sin FK: Mantis no es una tabla
    -- local) -- control de duplicados real en vez de solo la marca "Mantis
    -- #<id>" en la descripcion, ver core/views.py:_mantis_ids_ya_importadas.
    mantis_id        INT NULL,
    -- si la incidencia de Mantis de origen la creo la IA de la empresa
    -- (MANTIS_REPORTERO_IA) -- solo informativo/filtrado, ver
    -- core/mantis_client.py:fue_creada_por_ia. Se calcula una unica vez al
    -- importar, no se recalcula despues.
    generada_por_ia  BOOLEAN NOT NULL DEFAULT FALSE,
    -- persona asignada (opcional) -- para los permisos granulares por
    -- espacio (editores_mueven_tareas_ajenas/editores_eliminan_tareas_ajenas,
    -- ver espacios mas abajo): un Editor sin esos interruptores solo puede
    -- tocar sus propias tareas asignadas. Borrar el usuario no borra la
    -- tarea, solo la deja sin asignar, igual que empresa_id/sistema_id.
    asignado_a       INT NULL,
    creada_en        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actualizada_en   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (proyecto_id)   REFERENCES proyectos(id)   ON DELETE CASCADE,
    FOREIGN KEY (categoria_id)  REFERENCES categorias(id)  ON DELETE SET NULL,
    FOREIGN KEY (sprint_id)     REFERENCES sprints(id)     ON DELETE SET NULL,
    FOREIGN KEY (empresa_id)    REFERENCES empresas(id)    ON DELETE SET NULL,
    FOREIGN KEY (sistema_id)    REFERENCES sistemas(id)    ON DELETE SET NULL,
    FOREIGN KEY (iniciativa_id) REFERENCES iniciativas(id) ON DELETE SET NULL,
    FOREIGN KEY (asignado_a)    REFERENCES auth_user(id)   ON DELETE SET NULL,
    INDEX idx_tarea_proyecto (proyecto_id),
    INDEX idx_tarea_categoria (categoria_id),
    INDEX idx_tarea_estado (estado),
    INDEX idx_tarea_sprint (sprint_id),
    INDEX idx_tarea_borrada (borrada),
    INDEX idx_tarea_empresa (empresa_id),
    INDEX idx_tarea_sistema (sistema_id),
    INDEX idx_tarea_iniciativa (iniciativa_id),
    INDEX idx_tarea_reunion (reunion_id),
    INDEX idx_tarea_mantis (mantis_id),
    INDEX idx_tarea_asignado (asignado_a)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
CREATE TABLE documentos (
    id            VARCHAR(32)  PRIMARY KEY,
    proyecto_id   VARCHAR(32)  NOT NULL,
    tarea_id      VARCHAR(32)  NULL,
    nombre        VARCHAR(300) NOT NULL,
    filename      VARCHAR(300) NOT NULL,
    size          INT NOT NULL DEFAULT 0,
    subido_en     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    subido_por    VARCHAR(200) NOT NULL DEFAULT '',
    FOREIGN KEY (proyecto_id) REFERENCES proyectos(id) ON DELETE CASCADE,
    FOREIGN KEY (tarea_id)    REFERENCES tareas(id)     ON DELETE CASCADE,
    INDEX idx_doc_proyecto (proyecto_id),
    INDEX idx_doc_tarea (tarea_id)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
CREATE TABLE wiki_paginas (
    id             VARCHAR(32)  PRIMARY KEY,
    proyecto_id    VARCHAR(32)  NOT NULL,
    parent_id      VARCHAR(32)  NULL,
    titulo         VARCHAR(300) NOT NULL,
    -- OJO: un DEFAULT literal con emoji (4 bytes utf8mb4) se guarda mal como '?'
    -- en MariaDB si la sesion que ejecuta el DDL no es estrictamente utf8mb4
    -- de punta a punta. CONVERT(UNHEX(...) USING utf8mb4) evita el problema
    -- porque se evalua como expresion en cada INSERT, no como literal fijo.
    icono          VARCHAR(8)   NOT NULL DEFAULT (CONVERT(UNHEX('F09F9384') USING utf8mb4)),
    orden          INT NOT NULL DEFAULT 0,
    contenido      JSON NOT NULL,
    creada_en      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actualizada_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (proyecto_id) REFERENCES proyectos(id)   ON DELETE CASCADE,
    FOREIGN KEY (parent_id)   REFERENCES wiki_paginas(id) ON DELETE SET NULL,
    INDEX idx_wiki_proyecto (proyecto_id),
    INDEX idx_wiki_parent (parent_id)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
-- notas: post-its personales, independientes entre si (sin proyecto ni FK
-- entrante), solo titulo+contenido+color de fondo.
CREATE TABLE notas (
    id             VARCHAR(32)  PRIMARY KEY,
    titulo         VARCHAR(200) NOT NULL,
    contenido      TEXT NOT NULL DEFAULT '',
    color          VARCHAR(7)   NOT NULL DEFAULT '#fef9c3',
    orden          INT NOT NULL DEFAULT 0,
    -- FK a reuniones_calendario añadida mas abajo con ALTER TABLE (esa tabla
    -- se crea despues en este mismo fichero, no se puede referenciar aqui).
    reunion_id     VARCHAR(64)  NULL,
    -- Agenda por dia (routers/agenda.py) -- una nota suelta puede anclarse a
    -- una fecha concreta, igual patron que reunion_id pero con una fecha en
    -- vez de un id (la fecha ya es una clave estable, no hace falta tabla
    -- intermedia). Nunca a la vez que reunion_id en la practica, pero nada
    -- lo impide a nivel de esquema.
    agenda_fecha   DATE NULL,
    creada_en      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actualizada_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_nota_agenda_fecha (agenda_fecha)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
-- whiteboards: pizarras tipo Paint, reeditables -- el contenido se guarda como
-- JSON de objetos (trazos/formas/texto), con claves cortas y minificado desde
-- el propio cliente para ocupar poco. thumbnail es un PNG derivado en disco
-- (media_dir()/whiteboards/), solo para la miniatura de la galeria y el boton
-- "Descargar PNG" -- NO es el formato de almacenamiento principal.
-- version_hash se recalcula en cada guardado real, como marca de version simple.
CREATE TABLE whiteboards (
    id             VARCHAR(32)  PRIMARY KEY,
    titulo         VARCHAR(200) NOT NULL,
    contenido      JSON NOT NULL,
    thumbnail      VARCHAR(255) NOT NULL DEFAULT '',
    version_hash   VARCHAR(16)  NOT NULL DEFAULT '',
    -- FK a reuniones_calendario añadida mas abajo con ALTER TABLE (esa tabla
    -- se crea despues en este mismo fichero, no se puede referenciar aqui).
    reunion_id     VARCHAR(64)  NULL,
    -- Agenda por dia (routers/agenda.py) -- mismo patron/comentario que
    -- notas.agenda_fecha arriba.
    agenda_fecha   DATE NULL,
    creada_en      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actualizada_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_whiteboard_agenda_fecha (agenda_fecha)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
-- calendario_sync_config: config de sincronizacion del calendario externo
-- (feed ICS de Outlook/Office 365) para importar reuniones -- una fila por
-- usuario (username de auth.User, sin FK cruzado a las tablas de Django,
-- mismo criterio que documentos.subido_por) porque cada persona publica su
-- propio calendario. De momento solo guarda la URL -- la sincronizacion en si
-- (leer el ICS y crear/actualizar eventos) es un modulo futuro sin decidir.
CREATE TABLE calendario_sync_config (
    usuario        VARCHAR(150) PRIMARY KEY,
    ics_url        TEXT NOT NULL DEFAULT '',
    creado_en      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actualizado_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
-- reuniones_calendario: reuniones traidas del feed ICS configurado por
-- usuario (calendario_sync_config), para mostrarlas en el Calendario. 'id'
-- es un hash (sha256 de usuario+UID del ICS) en vez del UID tal cual, porque
-- los UID que genera Exchange pueden ser muy largos y superar el limite de
-- longitud de indice de InnoDB -- 'uid_ics' guarda el original para
-- referencia/depuracion. Se rellena SOLO con el boton "Sincronizar ahora"
-- (Configuracion -> Calendario externo), nada automatico, mismo criterio que
-- el historico de Mantis.
CREATE TABLE reuniones_calendario (
    id              VARCHAR(64)  PRIMARY KEY,
    usuario         VARCHAR(150) NOT NULL,
    uid_ics         TEXT NOT NULL,
    titulo          VARCHAR(300) NOT NULL,
    fecha_inicio    DATETIME NOT NULL,
    fecha_fin       DATETIME NULL,
    ubicacion       VARCHAR(500) NOT NULL DEFAULT '',
    enlace_teams    VARCHAR(500) NOT NULL DEFAULT '',
    sincronizada_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_reunion_usuario_fecha (usuario, fecha_inicio)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- FKs de tareas.reunion_id/whiteboards.reunion_id hacia esta tabla -- van aqui
-- (no en los CREATE TABLE de arriba) porque reuniones_calendario se crea
-- despues que esas dos en este fichero. ON DELETE SET NULL: si la reunion
-- desaparece, la tarea/pizarra no se borra, solo se desvincula.
ALTER TABLE tareas ADD CONSTRAINT fk_tarea_reunion
    FOREIGN KEY (reunion_id) REFERENCES reuniones_calendario(id) ON DELETE SET NULL;
ALTER TABLE whiteboards ADD CONSTRAINT fk_whiteboard_reunion
    FOREIGN KEY (reunion_id) REFERENCES reuniones_calendario(id) ON DELETE SET NULL;
ALTER TABLE notas ADD CONSTRAINT fk_nota_reunion
    FOREIGN KEY (reunion_id) REFERENCES reuniones_calendario(id) ON DELETE SET NULL;

-- ────────────────────────────────────────────────────────────
-- ajustes_app: settings operativos de la app (NO texto de interfaz -- eso es
-- plantilla_config), clave/valor generico. Primer uso: que proyecto recibe
-- las tareas importadas desde Mantis (clave 'mantis.proyecto_destino').
CREATE TABLE ajustes_app (
    clave VARCHAR(100) PRIMARY KEY,
    valor TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
-- api_tokens: claves de la API externa (ver docs/api/Manual_API_App_Tareas.md),
-- gestionables desde Configuracion -> API en vez de solo la clave "maestra"
-- fija en .env (API_IMPORT_TOKEN, que sigue funcionando, con acceso a todo).
-- Se guarda el HASH (sha256), nunca el token en claro -- igual que una
-- contraseña, el valor real solo se ve una vez, al crearlo.
-- proyecto_id NULL = acceso a todos los proyectos -- con valor = solo ese
-- proyecto (import_tareas/lista/detalle de otro proyecto con este token
-- devuelve 403/404, ver core/views.py::_resolver_api_token).
CREATE TABLE api_tokens (
    id            VARCHAR(32)  PRIMARY KEY,
    nombre        VARCHAR(150) NOT NULL,
    token_hash    CHAR(64)     NOT NULL UNIQUE,
    proyecto_id   VARCHAR(32)  NULL,
    creado_en     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ultimo_uso_en DATETIME NULL,
    -- dueño: quien lo creo. La API actua como esta persona (acciones.py);
    -- NULL = token antiguo, firma como 'API · <nombre>'
    user_id       INT NULL,
    FOREIGN KEY (proyecto_id) REFERENCES proyectos(id) ON DELETE CASCADE,
    CONSTRAINT fk_api_tokens_user FOREIGN KEY (user_id) REFERENCES auth_user(id) ON DELETE SET NULL,
    INDEX idx_api_token_proyecto (proyecto_id)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
-- mantis_origen_cache: clasificacion (IA/correo/manual, ver
-- mantis_client.clasificar_origen) de cada incidencia de Mantis YA vista,
-- por mantis_id -- el origen de una incidencia no cambia nunca una vez
-- creada, asi que una vez clasificada no hace falta volver a pedirselo a
-- Mantis (esa llamada es la cara: una por incidencia). Se rellena desde dos
-- sitios: scripts/mantis_watcher.py (cada vez que ve una incidencia nueva
-- en su ronda de 5 min, de fondo) y views.py::mantis_origen_desglose (al
-- vuelo, solo para las que el vigilante no haya visto todavia) -- ver
-- comentario en ambos.
CREATE TABLE mantis_origen_cache (
    mantis_id      INT PRIMARY KEY,
    proyecto_id    INT NOT NULL,
    creada         DATETIME NOT NULL,
    es_ia          BOOLEAN NOT NULL,
    es_correo      BOOLEAN NOT NULL,
    clasificado_en DATETIME NOT NULL,
    categoria      VARCHAR(190) NULL,
    tecnico        VARCHAR(190) NULL,
    proyecto_nombre VARCHAR(190) NULL,
    INDEX idx_origen_cache_creada (creada)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
-- mantis_espejo: estado ACTUAL (proyecto, tecnico, categoria, fecha) de
-- todas las incidencias de Mantis, para el desglose de origen del SLA. Se
-- pone al dia al principio de cada calculo trayendo solo lo que cambio
-- desde ajustes_app['mantis.espejo_actualizado_hasta'] (el listado de
-- Mantis sale ordenado por updated_at desc) -- ver
-- routers/mantis.py::_sincronizar_espejo_mantis. A diferencia de
-- mantis_origen_cache (clasificacion inmutable), esto SI cambia: una
-- incidencia se mueve de proyecto o se reasigna y aqui se refleja.
CREATE TABLE mantis_espejo (
    mantis_id       INT PRIMARY KEY,
    proyecto_id     INT NOT NULL,
    proyecto_nombre VARCHAR(190) NULL,
    creada          DATETIME NOT NULL,
    actualizada     DATETIME NOT NULL,
    tecnico         VARCHAR(190) NULL,
    categoria       VARCHAR(190) NULL,
    INDEX idx_espejo_creada (creada)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
-- mantis_incidencias_historico: acumulado local de incidencias de Mantis
-- (proyectos de empresa) que en algun momento se vio con mi email como
-- handler -- sirve para calcular tiempos de resolucion reales, algo que la
-- lista en vivo (fetch_pool_issues) no puede dar porque excluye a proposito
-- las resueltas/cerradas por rendimiento. Se rellena solo con el boton
-- "Sincronizar historico" (Configuracion/pestana SLA Mantis), nunca solo.
-- resuelta_en es una aproximacion: se fija la PRIMERA vez que se ve la
-- incidencia en estado resuelta/cerrada (= su actualizada de ese momento) y
-- ya no se toca despues, para no moverse si luego se anade una nota.
CREATE TABLE mantis_incidencias_historico (
    mantis_id    INT PRIMARY KEY,
    proyecto     VARCHAR(100) NOT NULL,
    categoria    VARCHAR(100) NOT NULL DEFAULT '',
    prioridad    VARCHAR(20)  NOT NULL DEFAULT '',
    resumen      VARCHAR(500) NOT NULL DEFAULT '',
    estado_name  VARCHAR(30)  NOT NULL DEFAULT '',
    estado_label VARCHAR(50)  NOT NULL DEFAULT '',
    creada       DATETIME NOT NULL,
    actualizada  DATETIME NOT NULL,
    resuelta_en  DATETIME NULL,
    ultima_sync  DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
-- plantilla_config: textos de interfaz (titulos, nombre de la app, etc.) que
-- NO deben quedar escritos a mano en las plantillas -- si esto se empaqueta
-- algun dia como .exe, ese texto quedaria embebido en el binario y cambiarlo
-- exigiria recompilar. Al leerse de aqui en cada request (context processor
-- core.context_processors.plantilla_config), cambiar valor + recargar basta.
-- clave usa notacion 'seccion.nombre' (ej. 'app.nombre', 'gantt.leyenda') que
-- el context processor anida en un dict -- categoria es para filtrar/agrupar
-- en una futura pantalla de edicion, no afecta a como se usa la clave.
CREATE TABLE plantilla_config (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    clave       VARCHAR(100) NOT NULL UNIQUE,
    valor       TEXT NOT NULL,
    categoria   VARCHAR(50)  NOT NULL,
    descripcion VARCHAR(255) NOT NULL DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
-- marcadores: accesos directos PERSONALES (no compartidos) a cualquier URL
-- de la app -- un tablero concreto, un sprint filtrado, el SLA de Mantis...
-- url es relativa (siempre empieza por "/", nunca un dominio externo,
-- validado en el router) y puede llevar sus propios query params, incluido
-- un "abrir=..." que algunas paginas (ver tablero.html) leen al cargar para
-- reabrir un modal concreto -- asi el marcador reproduce todo el
-- recorrido hasta ese punto, no solo la pagina en si.
CREATE TABLE marcadores (
    id         VARCHAR(32)  PRIMARY KEY,
    user_id    INT NOT NULL,
    titulo     VARCHAR(150) NOT NULL,
    url        VARCHAR(500) NOT NULL,
    orden      INT NOT NULL DEFAULT 0,
    creado_en  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES auth_user(id) ON DELETE CASCADE,
    INDEX idx_marcador_user (user_id)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
-- nexus_nodos / nexus_relaciones / nexus_historial: sistema de relaciones
-- "nexus_id" tipo Union-Find -- cualquier entidad (proyecto, sistema,
-- wiki_paginas, notas, whiteboards) puede relacionarse con cualquier otra
-- sin que una tenga que "pertenecer" rigidamente a la otra (ver plan de
-- sesion "Sistema de relaciones nexus_id"). Cada entidad nace con su
-- propio nodo (grupo de 1), al relacionar dos nodos, uno pasa a ser el
-- "representante" del grupo combinado (union por tamaño), y si el
-- representante se borra, se promueve automaticamente el nodo con mas
-- relaciones dentro del grupo (ver db.py::nexus_eliminar_nodo). Nada de
-- esto reemplaza las FK normales que ya existen (proyecto_id en tareas,
-- etc.) -- es una capa ADICIONAL para relaciones que no encajan en una FK
-- fija de 1 a muchos.
CREATE TABLE nexus_nodos (
    id             VARCHAR(32)  PRIMARY KEY,
    tipo           VARCHAR(30)  NOT NULL,
    entidad_id     VARCHAR(32)  NOT NULL,
    representante  VARCHAR(32)  NOT NULL,
    creado_en      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_nexus_entidad (tipo, entidad_id),
    INDEX idx_nexus_representante (representante)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE nexus_relaciones (
    id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    nodo_a      VARCHAR(32) NOT NULL,
    nodo_b      VARCHAR(32) NOT NULL,
    creado_en   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (nodo_a) REFERENCES nexus_nodos(id) ON DELETE CASCADE,
    FOREIGN KEY (nodo_b) REFERENCES nexus_nodos(id) ON DELETE CASCADE,
    UNIQUE KEY uq_relacion (nodo_a, nodo_b)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE nexus_historial (
    id                      INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    grupo_nodos             TEXT NOT NULL,
    representante_anterior  VARCHAR(32) NULL,
    representante_nuevo     VARCHAR(32) NOT NULL,
    motivo                  VARCHAR(255) NOT NULL,
    creado_en               DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
-- wiki_pagina_metadata: campos estructurados (alias/codigo/tecnologias/
-- estado/rol) de una pagina de Wiki que describe un sistema -- vienen del
-- catalogo de Nexus (confluence_local.proyectos), donde SI eran columnas
-- propias con LIKE/FULLTEXT: en wiki_paginas ese texto vive dentro del
-- JSON de bloques EditorJS, poco practico de parsear en cada busqueda.
-- Fila opcional (no toda pagina de wiki describe un sistema).
CREATE TABLE wiki_pagina_metadata (
    pagina_id    VARCHAR(32)  PRIMARY KEY,
    alias        VARCHAR(255) NOT NULL DEFAULT '',
    codigo       VARCHAR(100) NOT NULL DEFAULT '',
    tecnologias  TEXT NOT NULL,
    estado       VARCHAR(100) NOT NULL DEFAULT '',
    rol          VARCHAR(20)  NOT NULL DEFAULT '',
    FOREIGN KEY (pagina_id) REFERENCES wiki_paginas(id) ON DELETE CASCADE,
    FULLTEXT KEY ft_metadata (tecnologias)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
-- wiki_paginas_versiones_archivo: historial de versiones HEREDADO de la
-- wiki propia de confluence_local (paginas_wiki_versiones) -- wiki_paginas
-- no tiene versionado propio hoy, no se inventa uno nuevo aqui, esto es
-- solo almacenamiento frio/consulta manual, sin UI.
CREATE TABLE wiki_paginas_versiones_archivo (
    id         VARCHAR(32)  PRIMARY KEY,
    pagina_id  VARCHAR(32)  NOT NULL,
    version    INT UNSIGNED NOT NULL,
    contenido  LONGTEXT NOT NULL,
    autor      VARCHAR(255) NULL,
    creado_en  DATETIME NOT NULL,
    FOREIGN KEY (pagina_id) REFERENCES wiki_paginas(id) ON DELETE CASCADE,
    UNIQUE KEY uq_version_archivo (pagina_id, version)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
-- credenciales: portada de confluence_local -- vinculada a un nexus_nodos
-- (normalmente el de un 'sistema'), no a un proyecto fijo, via
-- nexus_relaciones -- ver plan de sesion. valor es un blob AES-256-GCM
-- (ver app_fastapi/nexus/cripto.py, mismo cifrado que el original, copiado
-- sin re-cifrar en la migracion). Sin pass_hash: la propia autenticacion
-- AES-GCM ya dice si la contraseña de desbloqueo era correcta.
CREATE TABLE credenciales (
    id         VARCHAR(32)  PRIMARY KEY,
    etiqueta   VARCHAR(255) NOT NULL,
    usuario    VARCHAR(255) NULL,
    valor      TEXT NOT NULL,
    notas      TEXT NULL,
    creado_en  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
-- nexus_carpetas / nexus_archivos: catalogo de archivos indexados EN
-- SITIO sobre una unidad de red compartida -- portado tal cual de
-- confluence_local (carpetas/archivos), ids INT originales preservados
-- (decenas de miles de filas, nada fuera de este cluster necesita
-- referenciarlas). Filosofia distinta a `documentos` (que SI posee una
-- copia del fichero, ver db.py::media_dir()) -- no se funden, ver plan.
CREATE TABLE nexus_carpetas (
    id                INT UNSIGNED PRIMARY KEY,
    ruta_completa     VARCHAR(1024) NOT NULL,
    ruta_relativa     VARCHAR(1024) NOT NULL,
    nombre            VARCHAR(255)  NOT NULL,
    carpeta_padre_id  INT UNSIGNED NULL,
    nivel             SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    cuerpo            VARCHAR(255)  NULL,
    categoria         VARCHAR(255)  NULL,
    creado_en         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_nexus_carpetas_ruta (ruta_relativa(255)),
    FOREIGN KEY (carpeta_padre_id) REFERENCES nexus_carpetas(id) ON DELETE SET NULL,
    INDEX idx_nexus_carpetas_padre (carpeta_padre_id)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE nexus_archivos (
    id                  INT UNSIGNED PRIMARY KEY,
    carpeta_id          INT UNSIGNED NOT NULL,
    ruta_completa       VARCHAR(1024) NOT NULL,
    ruta_relativa       VARCHAR(1024) NOT NULL,
    nombre              VARCHAR(255)  NOT NULL,
    extension           VARCHAR(20)   NULL,
    tamano_kb           DECIMAL(14,2) NOT NULL DEFAULT 0,
    fecha_modificacion  DATETIME NULL,
    fecha_creacion      DATETIME NULL,
    tipo_documento      VARCHAR(100)  NULL,
    contenido_plano     LONGTEXT NULL,
    descripcion         TEXT NULL,
    rol                 VARCHAR(20) NULL,
    creado_en           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actualizado_en      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_nexus_archivos_ruta (ruta_relativa(255)),
    FOREIGN KEY (carpeta_id) REFERENCES nexus_carpetas(id) ON DELETE CASCADE,
    INDEX idx_nexus_archivos_tipo (tipo_documento),
    -- busqueda de Nexus (nexus/search.py). Para una carga masiva de miles de
    -- archivos es mas rapido quitarlo, cargar y volver a crearlo.
    FULLTEXT ft_nexus_archivos_busqueda (nombre, descripcion, contenido_plano)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
-- etiquetas: tageado portado en frio de confluence_local -- hoy nada en
-- app_fastapi/nexus/search.py las lee, se portan igualmente para no
-- perderlas (ver condicion "nada se queda por ahi tirado" del plan).
CREATE TABLE etiquetas (
    id      INT UNSIGNED PRIMARY KEY,
    nombre  VARCHAR(100) NOT NULL UNIQUE
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE nexus_archivo_etiquetas (
    archivo_id  INT UNSIGNED NOT NULL,
    etiqueta_id INT UNSIGNED NOT NULL,
    PRIMARY KEY (archivo_id, etiqueta_id),
    FOREIGN KEY (archivo_id) REFERENCES nexus_archivos(id) ON DELETE CASCADE,
    FOREIGN KEY (etiqueta_id) REFERENCES etiquetas(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE nexus_carpeta_etiquetas (
    carpeta_id  INT UNSIGNED NOT NULL,
    etiqueta_id INT UNSIGNED NOT NULL,
    PRIMARY KEY (carpeta_id, etiqueta_id),
    FOREIGN KEY (carpeta_id) REFERENCES nexus_carpetas(id) ON DELETE CASCADE,
    FOREIGN KEY (etiqueta_id) REFERENCES etiquetas(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- nexus_referencias: portada de confluence_local.proyecto_referencias ("este
-- archivo/carpeta es del sistema X"), con la ficha del catalogo sustituida
-- por SU pagina de Wiki (wiki_pagina_id). Los archivos/carpetas NO entran
-- en el grafo nexus nodo a nodo; la pagina si, asi que lo relacionado con
-- un sistema llega hasta sus archivos a traves de esta tabla.
CREATE TABLE nexus_referencias (
    id              INT UNSIGNED PRIMARY KEY,
    wiki_pagina_id  VARCHAR(32)  NOT NULL,
    carpeta_id      INT UNSIGNED NULL,
    archivo_id      INT UNSIGNED NULL,
    FOREIGN KEY (wiki_pagina_id) REFERENCES wiki_paginas(id) ON DELETE CASCADE,
    FOREIGN KEY (carpeta_id) REFERENCES nexus_carpetas(id) ON DELETE CASCADE,
    FOREIGN KEY (archivo_id) REFERENCES nexus_archivos(id) ON DELETE CASCADE,
    INDEX idx_nexus_ref_pagina (wiki_pagina_id)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
-- nexus_busquedas_log: log de busquedas de Nexus, portado de
-- confluence_local.busquedas_log (search.py::_log_busqueda sigue
-- escribiendo aqui tras el corte de codigo).
CREATE TABLE nexus_busquedas_log (
    id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    termino     VARCHAR(500) NOT NULL,
    modo        VARCHAR(10)  NOT NULL DEFAULT 'normal',
    resultados  INT NOT NULL DEFAULT 0,
    creado_en   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Las ~400 claves de abajo cubren TODO el texto de interfaz de la app (headers,
-- botones, labels de formulario, mensajes de confirmacion, tooltips, estados
-- vacios...) -- generadas desde core/context_processors.py:DEFAULTS, que es la
-- fuente de verdad real -- si diverge de este INSERT, ese diccionario manda.
INSERT INTO plantilla_config (clave, valor, categoria, descripcion) VALUES
    ('app.nombre', 'Gestor de Tareas', 'app', ''),
    ('notas.titulo', 'Notas', 'notas', ''),
    ('whiteboard.titulo', 'Whiteboards', 'whiteboard', ''),
    ('calendario.titulo', 'Calendario', 'calendario', ''),
    ('sla.titulo', 'Dashboard SLA', 'sla', ''),
    ('kanban.titulo', 'Todos los proyectos Kanban', 'kanban', ''),
    ('scrum.titulo', 'Todos los proyectos Scrum', 'scrum', ''),
    ('project_duplicate.titulo', 'Duplicar proyecto', 'project_duplicate', ''),
    ('nav.proyectos', 'Proyectos', 'nav', ''),
    ('nav.calendario', 'Calendario', 'nav', ''),
    ('nav.kanban', 'Kanban', 'nav', ''),
    ('nav.scrum', 'Scrum', 'nav', ''),
    ('nav.sla', 'SLA', 'nav', ''),
    ('nav.configuracion', 'Configuración', 'nav', ''),
    ('base.sidebar_toggle_tooltip', 'Ocultar/mostrar sidebar', 'base', ''),
    ('base.buscar_placeholder', 'Buscar en todos los proyectos...', 'base', ''),
    ('base.entorno_confirm_msg', 'Pasarás a leer/escribir en otra base de datos.', 'base', ''),
    ('base.entorno_confirm_title', '¿Cambiar de entorno?', 'base', ''),
    ('base.entorno_confirm_ok', 'Cambiar de entorno', 'base', ''),
    ('base.modo_pruebas_label', 'Modo Pruebas', 'base', ''),
    ('base.cambiar_a_real', 'cambiar a Real', 'base', ''),
    ('base.modo_real_label', 'Modo Real', 'base', ''),
    ('base.cambiar_a_pruebas', 'cambiar a Pruebas', 'base', ''),
    ('base.modo_oscuro', 'Modo oscuro', 'base', ''),
    ('base.modo_claro', 'Modo claro', 'base', ''),
    ('base.entorno_banner_texto', 'MODO PRUEBAS — estás viendo la base de datos de pruebas, no los datos reales', 'base', ''),
    ('base.sidebar_general_label', 'GENERAL', 'base', ''),
    ('base.sidebar_kanban_label', 'KANBAN', 'base', ''),
    ('base.sidebar_scrum_label', 'SCRUM', 'base', ''),
    ('base.ver_todos_sprints', 'Ver todos los sprints', 'base', ''),
    ('base.import_excel_label', 'IMPORTAR TAREAS DESDE EXCEL (opcional)', 'base', ''),
    ('base.excel_hint_pre', 'Cada fila del Excel se crea como una tarea en "Pendiente".', 'base', ''),
    ('base.plantilla_link_text', 'Descargar plantilla', 'base', ''),
    ('base.excel_hint_post', 'con las columnas y los valores validos de Categoria/Sistema/Empresa/Iniciativa.', 'base', ''),
    ('base.tipo_kanban_desc', 'Flujo continuo, sin fechas', 'base', ''),
    ('base.tipo_scrum_desc', 'Sprints, fechas, gantt', 'base', ''),
    ('base.sprint_placeholder', 'Sprint 1', 'base', ''),
    ('base.dirty_close_msg', 'Hay cambios sin guardar en este formulario. ¿Cerrar de todos modos y descartarlos?', 'base', ''),
    ('base.dirty_close_title', '¿Descartar cambios?', 'base', ''),
    ('base.dirty_close_ok', 'Descartar y cerrar', 'base', ''),
    ('base.sin_resultados', 'Sin resultados', 'base', ''),
    ('base.error_busqueda', 'No se pudo buscar (¿sesión caducada? recarga la página)', 'base', ''),
    ('base.requiere_subtareas_completas_label', 'Exigir subtareas completas para cerrar', 'base', ''),
    ('base.requiere_subtareas_completas_hint', 'Una tarea de este proyecto no podrá moverse a una columna "Hecha" mientras le queden subtareas sin marcar.', 'base', ''),
    ('base.subtareas_pendientes_error', 'No se puede cerrar la tarea: quedan subtareas sin completar.', 'base', ''),
    ('comun.salir', 'Salir', 'comun', ''),
    ('comun.hoy', 'Hoy', 'comun', ''),
    ('comun.periodo_activo', 'periodo activo', 'comun', ''),
    ('comun.editar_tooltip', 'Editar', 'comun', ''),
    ('comun.ver_en_mantis_tooltip', 'Ver incidencia en Mantis', 'comun', ''),
    ('comun.generada_ia_label', 'Generada por IA', 'comun', ''),
    ('comun.generada_ia_si', 'Sí', 'comun', ''),
    ('comun.generada_ia_no', 'No', 'comun', ''),
    ('comun.generada_ia_badge', '🤖 IA', 'comun', ''),
    ('comun.generada_ia_tooltip', 'Incidencia de Mantis generada automáticamente por la IA de la empresa', 'comun', ''),
    ('comun.activo_badge', 'activo', 'comun', ''),
    ('comun.nuevo_proyecto', 'Nuevo proyecto', 'comun', ''),
    ('comun.editar_proyecto', 'Editar proyecto', 'comun', ''),
    ('comun.nombre', 'NOMBRE', 'comun', ''),
    ('comun.descripcion', 'DESCRIPCION', 'comun', ''),
    ('comun.responsable', 'RESPONSABLE', 'comun', ''),
    ('comun.tipo', 'TIPO', 'comun', ''),
    ('comun.estado', 'ESTADO', 'comun', ''),
    ('comun.color', 'COLOR', 'comun', ''),
    ('comun.fecha', 'FECHA', 'comun', ''),
    ('comun.fecha_inicio', 'FECHA INICIO', 'comun', ''),
    ('comun.fecha_fin', 'FECHA FIN', 'comun', ''),
    ('comun.activo', 'Activo', 'comun', ''),
    ('comun.en_pausa', 'En pausa', 'comun', ''),
    ('comun.cerrado', 'Cerrado', 'comun', ''),
    ('comun.planificado', 'Planificado', 'comun', ''),
    ('comun.cancelar', 'Cancelar', 'comun', ''),
    ('comun.guardar', 'Guardar', 'comun', ''),
    ('comun.confirmar', 'Confirmar', 'comun', ''),
    ('comun.completado', 'Completado', 'comun', ''),
    ('comun.objetivo', 'OBJETIVO', 'comun', ''),
    ('comun.nuevo_hito', 'Nuevo hito', 'comun', ''),
    ('comun.editar_hito', 'Editar hito', 'comun', ''),
    ('comun.nueva_categoria', 'Nueva categoria', 'comun', ''),
    ('comun.editar_categoria', 'Editar categoria', 'comun', ''),
    ('comun.nuevo_sprint', 'Nuevo sprint', 'comun', ''),
    ('comun.editar_sprint', 'Editar sprint', 'comun', ''),
    ('comun.nueva_tarea', 'Nueva tarea', 'comun', ''),
    ('comun.editar_tarea', 'Editar tarea', 'comun', ''),
    ('comun.sin_sprint', 'Sin sprint', 'comun', ''),
    ('board.responsable_prefix', 'Responsable', 'board', ''),
    ('board.inicio_prefix', 'Inicio', 'board', ''),
    ('board.fin_prefix', 'Fin', 'board', ''),
    ('board.boton_tarea', '+ Tarea', 'board', ''),
    ('board.buscar_tareas_placeholder', 'Buscar tareas...', 'board', ''),
    ('board.exportar_csv_tooltip', 'Exportar CSV', 'board', ''),
    ('board.atajos_teclado', 'Atajos de teclado', 'board', ''),
    ('board.creadas_entre', 'CREADAS ENTRE', 'board', ''),
    ('board.quitar_filtros_tooltip', 'Quitar todos los filtros', 'board', ''),
    ('board.limpiar_todo', 'Limpiar todo', 'board', ''),
    ('board.opciones_columna_tooltip', 'Opciones columna', 'board', ''),
    ('board.mover_izquierda', 'Mover izquierda', 'board', ''),
    ('board.mover_derecha', 'Mover derecha', 'board', ''),
    ('board.col_delete_confirm_msg', 'Las tareas de esta columna pasarán a OUTCAST.', 'board', ''),
    ('board.col_delete_confirm_title', '¿Eliminar columna?', 'board', ''),
    ('board.col_delete_confirm_ok', 'Eliminar columna', 'board', ''),
    ('board.quitar_sprint_tooltip', 'Quitar del sprint (vuelve al backlog)', 'board', ''),
    ('board.task_delete_confirm_msg', 'Esta tarea se moverá a Borradas.', 'board', ''),
    ('board.task_delete_confirm_title', '¿Borrar tarea?', 'board', ''),
    ('board.sin_tareas', 'Sin tareas', 'board', ''),
    ('board.anadir_tarea_placeholder', 'Añadir tarea...', 'board', ''),
    ('board.boton_columna', '+ Columna', 'board', ''),
    ('board.nueva_columna_titulo', 'Nueva columna', 'board', ''),
    ('board.col_nombre_placeholder', 'Ej: En revision', 'board', ''),
    ('board.col_es_done_label', 'Marca tareas como "hecho" al mover aqui', 'board', ''),
    ('board.editar_columna_titulo', 'Editar columna', 'board', ''),
    ('board.limite_wip_label', 'LÍMITE WIP', 'board', ''),
    ('board.limite_wip_hint', '0 = sin límite', 'board', ''),
    ('board.anclada_label', 'Anclada', 'board', ''),
    ('board.anclada_hint', 'se marca sutilmente en el Calendario', 'board', ''),
    ('board.detail_default_title', 'Selecciona una tarea', 'board', ''),
    ('board.borrar_seleccionadas', 'Borrar seleccionadas', 'board', ''),
    ('board.atajo_deshacer', 'Deshacer mover', 'board', ''),
    ('board.atajo_rehacer', 'Rehacer mover', 'board', ''),
    ('board.atajo_cerrar', 'Cerrar modal / panel', 'board', ''),
    ('board.atajo_ayuda', 'Mostrar esta ayuda', 'board', ''),
    ('board.atajo_detalle', 'Ver detalle de tarea', 'board', ''),
    ('board.info_creada', 'Creada', 'board', ''),
    ('board.info_actualizada', 'Actualizada', 'board', ''),
    ('board.info_inicio', 'Inicio', 'board', ''),
    ('board.info_fin', 'Fin', 'board', ''),
    ('board.info_test', 'T. Estimado', 'board', ''),
    ('board.info_treal', 'T. Real', 'board', ''),
    ('board.doc_delete_confirm_msg', 'Se eliminará el archivo.', 'board', ''),
    ('board.doc_delete_confirm_title', '¿Eliminar archivo?', 'board', ''),
    ('board.sin_adjuntos', 'Sin adjuntos', 'board', ''),
    ('board.tarea_singular', 'tarea', 'board', ''),
    ('board.plural_suffix', 's', 'board', ''),
    ('board.seleccionada_singular', 'seleccionada', 'board', ''),
    ('board.bulk_delete_confirm_pre', 'Se moverán ', 'board', ''),
    ('board.bulk_delete_confirm_post', ' tarea(s) a Borradas.', 'board', ''),
    ('board.bulk_delete_confirm_title', '¿Borrar tareas seleccionadas?', 'board', ''),
    ('comun.categoria', 'CATEGORIA', 'comun', ''),
    ('comun.todas', 'Todas', 'comun', ''),
    ('comun.sistema', 'SISTEMA', 'comun', ''),
    ('comun.todos', 'Todos', 'comun', ''),
    ('comun.iniciativa', 'INICIATIVA', 'comun', ''),
    ('comun.prioridad', 'PRIORIDAD', 'comun', ''),
    ('comun.alta', 'Alta', 'comun', ''),
    ('comun.normal', 'Normal', 'comun', ''),
    ('comun.baja', 'Baja', 'comun', ''),
    ('comun.renombrar', 'Renombrar', 'comun', ''),
    ('comun.eliminar', 'Eliminar', 'comun', ''),
    ('comun.sprint', 'Sprint', 'comun', ''),
    ('comun.editar', 'Editar', 'comun', ''),
    ('comun.duplicar', 'Duplicar', 'comun', ''),
    ('comun.quitar', 'Quitar', 'comun', ''),
    ('comun.borrar', 'Borrar', 'comun', ''),
    ('comun.restaurar', 'Restaurar', 'comun', ''),
    ('comun.crear', 'Crear', 'comun', ''),
    ('comun.titulo', 'TITULO', 'comun', ''),
    ('comun.proyecto', 'PROYECTO', 'comun', ''),
    ('comun.ninguno', 'Ninguno', 'comun', ''),
    ('comun.ninguna', 'Ninguna', 'comun', ''),
    ('comun.empresa', 'EMPRESA', 'comun', ''),
    ('comun.opcional', 'opcional', 'comun', ''),
    ('comun.proximo_paso', 'PROXIMO PASO', 'comun', ''),
    ('comun.subtareas', 'SUBTAREAS', 'comun', ''),
    ('comun.mas_subtarea', '+ Subtarea', 'comun', ''),
    ('comun.tiempo_estimado', 'T. ESTIMADO', 'comun', ''),
    ('comun.tiempo_real', 'T. REAL', 'comun', ''),
    ('comun.horas_unidad', 'h', 'comun', ''),
    ('comun.info', 'INFO', 'comun', ''),
    ('comun.cerrar', 'Cerrar', 'comun', ''),
    ('comun.adjuntos', 'ADJUNTOS', 'comun', ''),
    ('comun.subtarea_placeholder', 'Subtarea...', 'comun', ''),
    ('comun.mas_anadir', '+ Añadir', 'comun', ''),
    ('project.tareas_totales', 'Tareas totales', 'project', ''),
    ('project.hitos', 'Hitos', 'project', ''),
    ('project.sin_hitos', 'Sin hitos definidos', 'project', ''),
    ('project.categorias', 'Categorias', 'project', ''),
    ('project.cat_delete_confirm_msg', 'Se eliminará esta categoría.', 'project', ''),
    ('project.cat_delete_confirm_title', '¿Eliminar categoría?', 'project', ''),
    ('project.sin_categorias', 'Sin categorias', 'project', ''),
    ('project.tareas_activas', 'Tareas activas', 'project', ''),
    ('project.ver_tablero', 'Ver tablero', 'project', ''),
    ('project.sin_tareas_activas', 'Sin tareas activas', 'project', ''),
    ('project.actividad_reciente', 'Actividad reciente', 'project', ''),
    ('comun.meses_abrev', 'Ene,Feb,Mar,Abr,May,Jun,Jul,Ago,Sep,Oct,Nov,Dic', 'comun', ''),
    ('dashboard.progreso_general', 'Progreso general', 'dashboard', ''),
    ('dashboard.completadas', 'Completadas', 'dashboard', ''),
    ('dashboard.vencidas', 'Vencidas', 'dashboard', ''),
    ('dashboard.por_estado', 'Por estado', 'dashboard', ''),
    ('dashboard.por_categoria', 'Por categoria', 'dashboard', ''),
    ('dashboard.por_prioridad', 'Por prioridad (pendientes)', 'dashboard', ''),
    ('dashboard.tareas_vencidas', 'Tareas vencidas', 'dashboard', ''),
    ('dashboard.velocidad_sprints', 'Velocidad de sprints', 'dashboard', ''),
    ('dashboard.burndown', 'Burndown', 'dashboard', ''),
    ('dashboard.ideal', 'Ideal', 'dashboard', ''),
    ('dashboard.real', 'Real', 'dashboard', ''),
    ('dashboard.actividad_52_semanas', 'Actividad — últimas 52 semanas', 'dashboard', ''),
    ('backlog.importar_excel', 'Importar Excel', 'backlog', ''),
    ('backlog.titulo', 'Backlog', 'backlog', ''),
    ('backlog.tareas_plural', 'tareas', 'backlog', ''),
    ('backlog.desc', 'Tareas sin sprint asignado.', 'backlog', ''),
    ('backlog.asignar_sprint', 'Asignar a sprint', 'backlog', ''),
    ('backlog.asignar_btn', 'Asignar', 'backlog', ''),
    ('backlog.sin_sprints_abiertos', 'Sin sprints abiertos', 'backlog', ''),
    ('backlog.vacio_msg', 'El backlog esta vacio. Todas las tareas tienen sprint asignado o no hay tareas.', 'backlog', ''),
    ('backlog.importar_modal_titulo', 'Importar tareas desde Excel', 'backlog', ''),
    ('backlog.archivo_label', 'ARCHIVO (.xlsx)', 'backlog', ''),
    ('backlog.import_hint_pre', 'Cada fila se crea como una tarea en "Pendiente". Las filas cuyo titulo ya exista en el proyecto se omiten (se avisa al terminar), maximo', 'backlog', ''),
    ('backlog.import_hint_post', 'filas por archivo.', 'backlog', ''),
    ('backlog.sprint_destino_label', 'SPRINT DESTINO', 'backlog', ''),
    ('backlog.sin_sprint_opcion', 'Backlog (sin sprint)', 'backlog', ''),
    ('backlog.importar_btn', 'Importar', 'backlog', ''),
    ('comun.tarea', 'Tarea', 'comun', ''),
    ('comun.pendiente', 'Pendiente', 'comun', ''),
    ('gantt.por_fechas', 'Por fechas', 'gantt', ''),
    ('gantt.por_sprint', 'Por sprint', 'gantt', ''),
    ('gantt.leyenda_con_fechas', 'Tarea con fechas', 'gantt', ''),
    ('gantt.leyenda_sin_fechas', 'Sin fechas', 'gantt', ''),
    ('gantt.leyenda_hito', 'Hito', 'gantt', ''),
    ('gantt.sin_fechas_asignadas', 'Sin fechas asignadas', 'gantt', ''),
    ('gantt.anadir_fechas', 'Añadir fechas', 'gantt', ''),
    ('gantt.vacio_msg', 'No hay tareas con fechas para mostrar el Gantt.', 'gantt', ''),
    ('gantt.vacio_hint', 'Edita las tareas y añade fecha inicio y fin.', 'gantt', ''),
    ('gantt.ir_al_tablero', 'Ir al tablero', 'gantt', ''),
    ('comun.cargando', 'Cargando...', 'comun', ''),
    ('sprints.dias', 'dias', 'sprints', ''),
    ('sprints.anadir_existentes', 'Añadir existentes', 'sprints', ''),
    ('sprints.close_confirm_pre', 'Las tareas pendientes de', 'sprints', ''),
    ('sprints.close_confirm_post', 'se copiarán al siguiente sprint.', 'sprints', ''),
    ('sprints.close_confirm_title', '¿Cerrar sprint?', 'sprints', ''),
    ('sprints.cerrar_sprint', 'Cerrar sprint', 'sprints', ''),
    ('sprints.vacio_msg', 'No hay sprints creados todavia.', 'sprints', ''),
    ('sprints.crear_primer_sprint', 'Crear primer sprint', 'sprints', ''),
    ('sprints.anadir_modal_titulo', 'Añadir tareas al sprint', 'sprints', ''),
    ('sprints.anadir_modal_desc', 'Tareas del proyecto sin sprint asignado. Selecciona una o varias.', 'sprints', ''),
    ('sprints.anadir_seleccionadas', 'Añadir seleccionadas', 'sprints', ''),
    ('sprints.sin_tareas_sin_sprint', 'No hay tareas sin sprint.', 'sprints', ''),
    ('docs.titulo_proyecto', 'Documentos del proyecto', 'docs', ''),
    ('docs.subir_archivo', 'Subir archivo', 'docs', ''),
    ('docs.descargar', 'Descargar', 'docs', ''),
    ('docs.sin_documentos', 'Sin documentos adjuntos al proyecto.', 'docs', ''),
    ('docs.titulo_por_tarea', 'Documentos por tarea', 'docs', ''),
    ('comun.tareas', 'Tareas', 'comun', ''),
    ('dup.copia_de', 'Copia de', 'dup', ''),
    ('dup.nombre_nuevo_label', 'NOMBRE DEL PROYECTO NUEVO', 'dup', ''),
    ('dup.copia_sufijo', 'copia', 'dup', ''),
    ('dup.que_copiar', '¿Qué copiar?', 'dup', ''),
    ('dup.solo_pendientes', 'Solo pendientes', 'dup', ''),
    ('dup.solo_pendientes_hint', 'Las que no están hechas', 'dup', ''),
    ('dup.todas_hint', 'Incluyendo hechas', 'dup', ''),
    ('dup.ninguna_opcion', 'Ninguna', 'dup', ''),
    ('dup.ninguna_hint', 'Solo estructura', 'dup', ''),
    ('dup.fechas_tareas', 'Fechas de tareas', 'dup', ''),
    ('dup.limpiar_fechas', 'Limpiar fechas', 'dup', ''),
    ('dup.limpiar_fechas_hint', 'Recomendado — empezar desde cero', 'dup', ''),
    ('dup.mantener_fechas', 'Mantener fechas', 'dup', ''),
    ('dup.mantener_fechas_hint', 'Las pasadas se limpian igualmente', 'dup', ''),
    ('dup.copiar_hitos', 'Copiar hitos', 'dup', ''),
    ('dup.copiar_hitos_hint', 'Las fechas se limpian si elegiste limpiar arriba', 'dup', ''),
    ('dup.crear_sprint', 'Crear Sprint 1 nuevo', 'dup', ''),
    ('dup.crear_sprint_hint', 'Fechas de hoy + 14 días · Las tareas se asignan aquí', 'dup', ''),
    ('dup.resumen_original', 'Resumen del original', 'dup', ''),
    ('dup.tipo_label', 'Tipo', 'dup', ''),
    ('tabs.resumen', 'Resumen', 'tabs', ''),
    ('tabs.dashboard', 'Dashboard', 'tabs', ''),
    ('tabs.tablero', 'Tablero', 'tabs', ''),
    ('tabs.gantt', 'Gantt', 'tabs', ''),
    ('tabs.sprints', 'Sprints', 'tabs', ''),
    ('tabs.documentos', 'Documentos', 'tabs', ''),
    ('tabs.sprint_mostrado_tooltip', 'Sprint mostrado en el Tablero', 'tabs', ''),
    ('tabs.toolbar_toggle_tooltip', 'Mostrar/ocultar barra de herramientas (buscar, filtros, vista)', 'tabs', ''),
    ('wiki.titulo', 'Wiki', 'wiki', ''),
    ('wiki.nueva_pagina', 'Nueva página', 'wiki', ''),
    ('wiki.sin_paginas', 'Sin páginas aún.', 'wiki', ''),
    ('wiki.actualizada', 'Actualizada', 'wiki', ''),
    ('wiki.creada', 'Creada', 'wiki', ''),
    ('wiki.subpagina', 'Subpágina', 'wiki', ''),
    ('wiki.delete_confirm_pre', 'Se eliminará «', 'wiki', ''),
    ('wiki.delete_confirm_post', '» y no se puede deshacer.', 'wiki', ''),
    ('wiki.delete_confirm_title', '¿Eliminar página?', 'wiki', ''),
    ('wiki.pagina_vacia', 'Esta página está vacía.', 'wiki', ''),
    ('wiki.anadir_contenido', 'Añadir contenido', 'wiki', ''),
    ('wiki.subpaginas', 'Subpáginas', 'wiki', ''),
    ('wiki.de_proyecto', 'de', 'wiki', ''),
    ('wiki.welcome_sub', 'Documenta tu proyecto, guarda conocimiento del equipo y mantén todo organizado en un solo lugar.', 'wiki', ''),
    ('wiki.crear_primera', 'Crear primera página', 'wiki', ''),
    ('wiki.paginas_recientes', 'Páginas recientes', 'wiki', ''),
    ('calendario.semana_anterior', 'Semana anterior', 'calendario', ''),
    ('calendario.semana_siguiente', 'Semana siguiente', 'calendario', ''),
    ('calendario.mes_anterior', 'Mes anterior', 'calendario', ''),
    ('calendario.mes_siguiente', 'Mes siguiente', 'calendario', ''),
    ('calendario.vista_mes', 'Mes', 'calendario', ''),
    ('calendario.vista_semana', 'Semana', 'calendario', ''),
    ('calendario.todos_proyectos', 'Todos los proyectos', 'calendario', ''),
    ('calendario.todas_categorias', 'Todas las categorías', 'calendario', ''),
    ('calendario.limpiar_filtros_tooltip', 'Limpiar filtros', 'calendario', ''),
    ('calendario.limpiar_btn', 'Limpiar', 'calendario', ''),
    ('calendario.nueva_tarea_dia_tooltip', 'Nueva tarea para este día', 'calendario', ''),
    ('calendario.tarea_urgente_tooltip', 'Tarea urgente pendiente', 'calendario', ''),
    ('calendario.tarea_anclada_tooltip', 'Tarea anclada', 'calendario', ''),
    ('calendario.dow_lun', 'Lun', 'calendario', ''),
    ('calendario.dow_mar', 'Mar', 'calendario', ''),
    ('calendario.dow_mie', 'Mié', 'calendario', ''),
    ('calendario.dow_jue', 'Jue', 'calendario', ''),
    ('calendario.dow_vie', 'Vie', 'calendario', ''),
    ('calendario.dow_sab', 'Sáb', 'calendario', ''),
    ('calendario.dow_dom', 'Dom', 'calendario', ''),
    ('calendario.aviso_label', 'Aviso', 'calendario', ''),
    ('calendario.mas_sufijo', 'más', 'calendario', ''),
    ('notas.nueva', 'Nueva nota', 'notas', ''),
    ('notas.editar', 'Editar nota', 'notas', ''),
    ('notas.vacio_msg', 'Aún no tienes ninguna nota.', 'notas', ''),
    ('notas.crear_primera', 'Crear la primera', 'notas', ''),
    ('notas.titulo_label', 'TÍTULO', 'notas', ''),
    ('notas.contenido_label', 'CONTENIDO', 'notas', ''),
    ('notas.eliminar_titulo', 'Eliminar nota', 'notas', ''),
    ('notas.delete_confirm_pre', '¿Seguro que quieres eliminar', 'notas', ''),
    ('notas.delete_confirm_post', '? Esta acción no se puede deshacer.', 'notas', ''),
    ('notas.leer_mas', 'Leer más', 'notas', ''),
    ('notas.buscar_placeholder', 'Buscar en notas...', 'notas', ''),
    ('notas.sin_resultados_busqueda', 'Ninguna nota coincide con la búsqueda.', 'notas', ''),
    ('notas.filtro_todas', 'Todas', 'notas', ''),
    ('notas.filtro_vinculadas', 'De una reunión', 'notas', ''),
    ('notas.filtro_sueltas', 'Sueltas', 'notas', ''),
    ('whiteboard.nuevo', 'Nuevo whiteboard', 'whiteboard', ''),
    ('whiteboard.vacio_msg', 'Aún no tienes ningún whiteboard.', 'whiteboard', ''),
    ('whiteboard.filtro_todas', 'Todas', 'whiteboard', ''),
    ('whiteboard.filtro_vinculadas', 'De una reunión', 'whiteboard', ''),
    ('whiteboard.filtro_sueltas', 'Sueltas', 'whiteboard', ''),
    ('whiteboard.sin_resultados_filtro', 'Ningún whiteboard coincide con el filtro.', 'whiteboard', ''),
    ('whiteboard.crear_primera', 'Crear el primero', 'whiteboard', ''),
    ('whiteboard.titulo_label', 'Sin título', 'whiteboard', ''),
    ('whiteboard.guardar', 'Guardar', 'whiteboard', ''),
    ('whiteboard.descargar_png', 'Descargar PNG', 'whiteboard', ''),
    ('whiteboard.volver', 'Volver', 'whiteboard', ''),
    ('whiteboard.eliminar_titulo', 'Eliminar whiteboard', 'whiteboard', ''),
    ('whiteboard.delete_confirm_pre', '¿Seguro que quieres eliminar', 'whiteboard', ''),
    ('whiteboard.delete_confirm_post', '? Esta acción no se puede deshacer.', 'whiteboard', ''),
    ('whiteboard.seleccionar', 'Seleccionar / mover', 'whiteboard', ''),
    ('whiteboard.pincel', 'Lápiz', 'whiteboard', ''),
    ('whiteboard.linea', 'Línea', 'whiteboard', ''),
    ('whiteboard.rectangulo', 'Rectángulo', 'whiteboard', ''),
    ('whiteboard.circulo', 'Círculo', 'whiteboard', ''),
    ('whiteboard.flecha', 'Flecha', 'whiteboard', ''),
    ('whiteboard.texto', 'Texto', 'whiteboard', ''),
    ('whiteboard.goma', 'Goma de borrar', 'whiteboard', ''),
    ('whiteboard.tamano_letra', 'Tamaño de letra', 'whiteboard', ''),
    ('whiteboard.vinetas_tooltip', 'Lista con viñetas', 'whiteboard', ''),
    ('whiteboard.numerada_tooltip', 'Lista numerada', 'whiteboard', ''),
    ('whiteboard.eliminar_objeto', 'Eliminar seleccionado', 'whiteboard', ''),
    ('whiteboard.deshacer', 'Deshacer', 'whiteboard', ''),
    ('reunion.volver', 'Volver al calendario', 'reunion', ''),
    ('reunion.ver_en_teams', 'Unirse en Teams', 'reunion', ''),
    ('reunion.pizarra_titulo', 'Whiteboard', 'reunion', ''),
    ('reunion.pizarra_sin_vincular_msg', 'Todavía no hay un whiteboard para esta reunión.', 'reunion', ''),
    ('reunion.pizarra_crear_btn', 'Crear whiteboard para esta reunión', 'reunion', ''),
    ('reunion.pizarra_vincular_btn', 'Vincular', 'reunion', ''),
    ('reunion.pizarra_vinculada_tooltip', 'Whiteboard vinculado a esta reunión', 'reunion', ''),
    ('reunion.tareas_titulo', 'Tareas de esta reunión', 'reunion', ''),
    ('reunion.tarea_placeholder', 'Añadir una tarea…', 'reunion', ''),
    ('reunion.tarea_anadir_btn', 'Añadir', 'reunion', ''),
    ('reunion.sin_tareas_msg', 'Todavía no hay tareas para esta reunión.', 'reunion', ''),
    ('reunion.notas_titulo', 'Notas de esta reunión', 'reunion', ''),
    ('reunion.nota_placeholder', 'Añadir una nota…', 'reunion', ''),
    ('reunion.nota_anadir_btn', 'Añadir', 'reunion', ''),
    ('reunion.sin_notas_msg', 'Todavía no hay notas para esta reunión.', 'reunion', ''),
    ('sla.subtitulo', 'Métricas de tiempo de resolución y ciclo de trabajo', 'sla', ''),
    ('sla.exportar_csv', 'Exportar CSV', 'sla', ''),
    ('sla.desde', 'DESDE', 'sla', ''),
    ('sla.hasta', 'HASTA', 'sla', ''),
    ('sla.aplicar', 'Aplicar', 'sla', ''),
    ('sla.abiertas', 'Abiertas', 'sla', ''),
    ('sla.cerradas', 'Cerradas', 'sla', ''),
    ('sla.lead_time_medio', 'Lead Time medio', 'sla', ''),
    ('sla.tareas_cerradas_nota', 'tareas cerradas', 'sla', ''),
    ('sla.cycle_time_medio', 'Cycle Time medio', 'sla', ''),
    ('sla.desde_inicio_nota', 'desde inicio hasta cierre', 'sla', ''),
    ('sla.resumen_proyecto', 'Resumen por proyecto', 'sla', ''),
    ('sla.total_col', 'Total', 'sla', ''),
    ('sla.pct_completado', '% Completado', 'sla', ''),
    ('sla.detalle_titulo', 'Detalle SLA por tarea', 'sla', ''),
    ('sla.columna_col', 'Columna', 'sla', ''),
    ('sla.iniciada_col', 'Iniciada', 'sla', ''),
    ('sla.cerrada_col', 'Cerrada', 'sla', ''),
    ('sla.lead_time', 'Lead Time', 'sla', ''),
    ('sla.cycle_time', 'Cycle Time', 'sla', ''),
    ('sla.vencida', 'Vencida', 'sla', ''),
    ('sla.cerrada', 'Cerrada', 'sla', ''),
    ('sla.abierta', 'Abierta', 'sla', ''),
    ('sla.sin_tareas_rango', 'No hay tareas en el rango seleccionado.', 'sla', ''),
    ('sla.horas_laborables_nota', 'Horas laborables: no cuentan fines de semana ni festivos', 'sla', ''),
    ('sla.tab_general', 'General', 'sla', ''),
    ('sla.tab_mantis', 'SLA Mantis', 'sla', ''),
    ('sla.mantis_titulo', 'SLA Mantis (asignadas a mí)', 'sla', ''),
    ('sla.mantis_abiertas_mias', 'Abiertas asignadas a mí', 'sla', ''),
    ('sla.mantis_tiempo_medio_abierto', 'Tiempo medio abierto', 'sla', ''),
    ('sla.mantis_sin_datos', 'No tienes incidencias de Mantis asignadas ahora mismo.', 'sla', ''),
    ('sla.mantis_sincronizar_btn', 'Sincronizar histórico', 'sla', ''),
    ('sla.mantis_sincronizando', 'Sincronizando…', 'sla', ''),
    ('sla.mantis_ultimo_sync_prefijo', 'Última sincronización:', 'sla', ''),
    ('sla.mantis_sin_historico', 'Todavía no has sincronizado el histórico. Pulsa "Sincronizar histórico" para traer tus incidencias resueltas y calcular tiempos de resolución reales.', 'sla', ''),
    ('sla.mantis_resueltas_historico', 'Resueltas (histórico)', 'sla', ''),
    ('sla.mantis_tiempo_medio_resolucion', 'Tiempo medio de resolución', 'sla', ''),
    ('sla.mantis_origen_titulo', 'Desglose por origen (Noel-IA / Correo / Manual)', 'sla', ''),
    ('sla.mantis_origen_desc', 'De todo el equipo (no solo lo asignado a ti), para el rango de fechas elegido. Clasificar cada incidencia cuesta una llamada extra a Mantis, asi que no se calcula solo -- elige el rango y pulsa "Calcular".', 'sla', ''),
    ('sla.mantis_origen_desde_label', 'DESDE', 'sla', ''),
    ('sla.mantis_origen_hasta_label', 'HASTA', 'sla', ''),
    ('sla.mantis_origen_btn', 'Calcular', 'sla', ''),
    ('sla.mantis_origen_calculando', 'Calculando...', 'sla', ''),
    ('sla.mantis_origen_sin_calcular', 'Elige un rango de fechas y pulsa "Calcular".', 'sla', ''),
    ('sla.mantis_origen_error_rango', 'Elige una fecha de inicio y de fin.', 'sla', ''),
    ('sla.mantis_origen_col_empresa', 'Empresa', 'sla', ''),
    ('sla.mantis_origen_col_usuario', 'Usuario', 'sla', ''),
    ('sla.mantis_origen_col_ia', 'Noel-IA', 'sla', ''),
    ('sla.mantis_origen_col_correo', 'Correo', 'sla', ''),
    ('sla.mantis_origen_col_manual', 'Manual', 'sla', ''),
    ('sla.mantis_origen_col_total', 'Total', 'sla', ''),
    ('config.grupo_tareas', 'Tareas', 'config', ''),
    ('config.categorias', 'Categorías', 'config', ''),
    ('config.empresas', 'Empresas', 'config', ''),
    ('config.sistemas', 'Sistemas', 'config', ''),
    ('config.iniciativas', 'Iniciativas', 'config', ''),
    ('config.dias_especiales', 'Días especiales', 'config', ''),
    ('config.tipos_dia_especial', 'Tipos de día especial', 'config', ''),
    ('config.desactivar', 'Desactivar', 'config', ''),
    ('config.activar', 'Activar', 'config', ''),
    ('config.categorias_desc', 'Tipo de trabajo — el mismo listado se usa en todos los proyectos.', 'config', ''),
    ('config.sin_categorias', 'Sin categorías todavía.', 'config', ''),
    ('config.empresas_desc', 'Compañías a las que das soporte — nombre comercial y fiscal.', 'config', ''),
    ('config.nueva_empresa', 'Nueva empresa', 'config', ''),
    ('config.editar_empresa', 'Editar empresa', 'config', ''),
    ('config.sin_empresas', 'Sin empresas todavía.', 'config', ''),
    ('config.sistemas_desc', 'Aplicación o herramienta de cada tarea — se filtra en el tablero.', 'config', ''),
    ('config.nuevo_sistema', 'Nuevo sistema', 'config', ''),
    ('config.editar_sistema', 'Editar sistema', 'config', ''),
    ('config.sin_sistemas', 'Sin sistemas todavía.', 'config', ''),
    ('config.iniciativas_desc', 'Tema transversal que puede cruzar varios sistemas y empresas.', 'config', ''),
    ('config.nueva_iniciativa', 'Nueva iniciativa', 'config', ''),
    ('config.editar_iniciativa', 'Editar iniciativa', 'config', ''),
    ('config.sin_iniciativas', 'Sin iniciativas todavía.', 'config', ''),
    ('config.dias_especiales_desc', 'Vacaciones, festivos, avisos y sede del día.', 'config', ''),
    ('config.nuevo_dia_especial', 'Nuevo día especial', 'config', ''),
    ('config.editar_dia_especial', 'Editar día especial', 'config', ''),
    ('config.dias_especiales_callout_pre', 'Lo que definas aquí no se ve en esta pantalla — se pinta en el', 'config', ''),
    ('config.dias_especiales_callout_post', '(fondo de color = Sede del día, puntos = Vacaciones/Festivo/Compensado, franja = Aviso).', 'config', ''),
    ('config.dia_delete_confirm_msg', 'Se eliminará este día especial.', 'config', ''),
    ('config.dia_delete_confirm_title', '¿Eliminar día especial?', 'config', ''),
    ('config.sin_dias_especiales', 'Sin días especiales todavía.', 'config', ''),
    ('config.tipos_dia_especial_desc', 'Los tipos que puedes elegir al crear un día especial — añade los que necesites, sin tocar código.', 'config', ''),
    ('config.nuevo_tipo', 'Nuevo tipo', 'config', ''),
    ('config.tipos_callout_pre', 'Las sedes de cada empresa ("Sede <empresa>") no aparecen aquí — se generan solas a partir de tus', 'config', ''),
    ('config.tipos_callout_post', 'activas. Aquí solo gestionas Anotación/Banner y sedes manuales (ej. Teletrabajo).', 'config', ''),
    ('config.categoria_sede', 'Sede', 'config', ''),
    ('config.categoria_banner', 'Banner', 'config', ''),
    ('config.categoria_anotacion', 'Anotación', 'config', ''),
    ('config.urgente_label', 'urgente', 'config', ''),
    ('config.sin_tipos', 'Sin tipos todavía.', 'config', ''),
    ('config.nombre_comercial', 'NOMBRE COMERCIAL', 'config', ''),
    ('config.nombre_fiscal', 'NOMBRE FISCAL', 'config', ''),
    ('config.optgroup_sede', 'Sede del día (fondo, un valor por día)', 'config', ''),
    ('config.optgroup_anotacion', 'Anotación en Calendario (punto)', 'config', ''),
    ('config.optgroup_banner', 'Banner en toda la app (mientras dura el rango)', 'config', ''),
    ('config.hasta_hint', 'opcional, si dura varios días', 'config', ''),
    ('config.nota_label', 'NOTA', 'config', ''),
    ('config.nota_placeholder', 'Ej. Horario de verano 7 a 15h', 'config', ''),
    ('config.nuevo_tipo_dia_especial', 'Nuevo tipo de día especial', 'config', ''),
    ('config.editar_tipo_dia_especial', 'Editar tipo de día especial', 'config', ''),
    ('config.tde_placeholder', 'Ej. Cierre de fábrica', 'config', ''),
    ('config.categoria_label', 'CATEGORÍA', 'config', ''),
    ('config.opcion_banner', 'Banner en toda la app', 'config', ''),
    ('config.opcion_sede', 'Sede del día (fondo, sin empresa asociada)', 'config', ''),
    ('config.urgente_checkbox_label', 'Mostrar como banner ROJO/urgente (en vez de tranquilo)', 'config', ''),
    ('config.hint_sede', 'Se pinta como fondo de todo el día en el Calendario. Solo puede haber una Sede por día.', 'config', ''),
    ('config.hint_banner_urgente', 'Aparece como banner en ROJO en toda la app mientras dura el rango de fechas (para cosas urgentes/criticas).', 'config', ''),
    ('config.hint_banner_normal', 'Aparece como banner discreto en toda la app mientras dura el rango de fechas (recordatorio tranquilo).', 'config', ''),
    ('config.hint_anotacion', 'Se pinta como un punto de color en el día del Calendario. Puede combinarse con una Sede y con otras anotaciones.', 'config', ''),
    ('login.acceder', 'Acceder', 'login', ''),
    ('login.subtitulo', 'Introduce tus credenciales para acceder', 'login', ''),
    ('login.error_credenciales', 'Usuario o contraseña incorrectos.', 'login', ''),
    ('login.usuario_label', 'USUARIO', 'login', ''),
    ('login.contrasena_label', 'CONTRASEÑA', 'login', ''),
    ('login.entrar_btn', 'Entrar', 'login', ''),
    ('backlog.error_sin_archivo', 'No se ha seleccionado ningun archivo.', 'backlog', ''),
    ('backlog.msg_importadas_sufijo', 'tareas importadas.', 'backlog', ''),
    ('backlog.msg_sin_importar', 'No se importo ninguna tarea nueva.', 'backlog', ''),
    ('backlog.avisos_mas_sufijo', 'avisos mas', 'backlog', ''),
    ('backlog.avisos_prefijo', 'filas con avisos:', 'backlog', ''),
    ('backlog.error_import_prefijo', 'No se pudo importar el Excel:', 'backlog', ''),
    ('base.import_excel_project_ok', 'Proyecto ''{nombre}'' creado con {n} tareas importadas.', 'base', ''),
    ('base.import_excel_project_error', 'No se pudo leer el Excel, el proyecto se creo sin tareas:', 'base', ''),
    ('wiki.guardar_hint', 'Ctrl+S para guardar', 'wiki', ''),
    ('wiki.titulo_placeholder', 'Título de la página', 'wiki', ''),
    ('wiki.pagina_padre_label', 'Página padre:', 'wiki', ''),
    ('wiki.raiz_opcion', 'Raíz', 'wiki', ''),
    ('wiki.editor_placeholder', '↵  Escribe algo, o usa / para insertar un bloque...', 'wiki', ''),
    ('wiki.editor_cita_placeholder', 'Cita...', 'wiki', ''),
    ('wiki.editor_fuente_placeholder', 'Fuente', 'wiki', ''),
    ('wiki.editor_aviso_titulo', 'Título', 'wiki', ''),
    ('wiki.editor_aviso_mensaje', 'Mensaje', 'wiki', ''),
    ('wiki.editorjs_texto', 'Texto', 'wiki', ''),
    ('wiki.editorjs_encabezado', 'Encabezado', 'wiki', ''),
    ('wiki.editorjs_lista', 'Lista', 'wiki', ''),
    ('wiki.editorjs_checklist', 'Lista de tareas', 'wiki', ''),
    ('wiki.editorjs_cita', 'Cita', 'wiki', ''),
    ('wiki.editorjs_codigo', 'Código', 'wiki', ''),
    ('wiki.editorjs_separador', 'Separador', 'wiki', ''),
    ('wiki.editorjs_tabla', 'Tabla', 'wiki', ''),
    ('wiki.editorjs_aviso', 'Aviso', 'wiki', ''),
    ('wiki.editorjs_enlace', 'Enlace', 'wiki', ''),
    ('wiki.editorjs_resaltar', 'Resaltar', 'wiki', ''),
    ('wiki.editorjs_codigo_linea', 'Código en línea', 'wiki', ''),
    ('wiki.editorjs_opciones', 'Opciones', 'wiki', ''),
    ('wiki.editorjs_arrastra', 'o arrastra', 'wiki', ''),
    ('wiki.editorjs_anadir', 'Añadir', 'wiki', ''),
    ('wiki.importar_word', 'Importar Word', 'wiki', ''),
    ('wiki.importar_modal_titulo', 'Importar página desde Word', 'wiki', ''),
    ('wiki.archivo_word_label', 'Documento (.docx)', 'wiki', ''),
    ('wiki.import_docx_hint', 'Se convertirán títulos, párrafos, listas, tablas y formato básico (negrita/cursiva/subrayado/tachado/enlaces). Las imágenes incrustadas no se importan todavía.', 'wiki', ''),
    ('wiki.importar_btn', 'Importar', 'wiki', ''),
    ('wiki.error_sin_archivo', 'No se ha seleccionado ningún archivo.', 'wiki', ''),
    ('wiki.error_import_prefijo', 'No se pudo importar el Word:', 'wiki', ''),
    ('wiki.import_docx_ok', 'Documento importado. Revisa el contenido antes de guardar.', 'wiki', ''),
    ('config.grupo_sistema', 'Sistema', 'config', ''),
    ('config.backups_titulo', 'Copias de seguridad', 'config', ''),
    ('config.backups_desc', 'Volcado completo de la base de datos real (mysqldump). Se guardan los últimos 15, los más antiguos se borran solos.', 'config', ''),
    ('config.hacer_backup_btn', 'Hacer backup ahora', 'config', ''),
    ('config.sin_backups', 'No hay backups todavía.', 'config', ''),
    ('config.whiteboard_borradores_titulo', 'Whiteboards sin guardar', 'config', ''),
    ('config.whiteboard_borradores_desc', 'Cambios detectados en este navegador que no llegaron a guardarse (por ejemplo, si se cerró de golpe). Solo aparecen aquí, nunca al abrir el whiteboard.', 'config', ''),
    ('config.whiteboard_borrador_restaurar', 'Restaurar', 'config', ''),
    ('config.whiteboard_borrador_descartar', 'Descartar', 'config', ''),
    ('config.mantis_nav_label', 'Mantis', 'config', ''),
    ('config.mantis_titulo', 'Importar incidencias de Mantis', 'config', ''),
    ('config.mantis_desc', 'Proyecto que recibe las tareas creadas a partir de las incidencias de Mantis que elijas importar.', 'config', ''),
    ('config.mantis_proyecto_label', 'PROYECTO DESTINO', 'config', ''),
    ('config.mantis_sin_elegir', 'Sin elegir', 'config', ''),
    ('config.mantis_pool_id_label', 'ID DEL PROYECTO POOL EN MANTIS', 'config', ''),
    ('config.mantis_umbral_ambar_label', 'SLA MANTIS: UMBRAL ÁMBAR (H)', 'config', ''),
    ('config.mantis_umbral_rojo_label', 'SLA MANTIS: UMBRAL ROJO (H)', 'config', ''),
    ('config.empresa_mantis_id_label', 'ID de proyecto en Mantis', 'config', ''),
    ('config.empresa_dominio_label', 'Dominio de email', 'config', ''),
    ('config.empresa_dominio_placeholder', 'ej. miempresa.com', 'config', ''),
    ('config.tipo_dia_cuenta_sla_label', 'Cuenta como no laborable para el SLA', 'config', ''),
    ('config.mantis_watcher_label', 'Vigilante de Mantis (aviso de escritorio)', 'config', ''),
    ('config.mantis_watcher_desc', 'Revisa Mantis cada 5 minutos en segundo plano y avisa con una notificación de Windows si llega una incidencia nueva. Pausarlo garantiza cero llamadas a la API hasta que lo reanudes.', 'config', ''),
    ('config.mantis_watcher_activo', 'Activo', 'config', ''),
    ('config.mantis_watcher_pausado', 'Pausado', 'config', ''),
    ('config.mantis_watcher_pausar', 'Pausar', 'config', ''),
    ('config.mantis_watcher_reanudar', 'Reanudar', 'config', ''),
    ('config.mantis_sync_asignadas_label', 'Sincronizar tareas asignadas a mí', 'config', ''),
    ('config.mantis_sync_asignadas_desc', 'Trae de golpe TODAS tus incidencias de Mantis (cualquier estado, incluidas resueltas/cerradas) que todavía no estén en tu sistema. Las ya resueltas/cerradas se crean directamente en "Hecha" — para ponerte al día si se te han ido acumulando.', 'config', ''),
    ('config.mantis_sync_asignadas_btn', 'Sincronizar ahora', 'config', ''),
    ('config.mantis_sync_asignadas_sincronizando', 'Sincronizando…', 'config', ''),
    ('config.mantis_sync_asignadas_ok_prefijo', 'Tareas nuevas creadas:', 'config', ''),
    ('config.mantis_sync_asignadas_error', 'No se pudo sincronizar.', 'config', ''),
    ('config.mantis_csv_map_titulo', 'Mapeo de estados (CSV de Mantis)', 'config', ''),
    ('config.mantis_csv_map_desc', 'El export nativo de Mantis (boton ''Exportar CSV'' en la propia Mantis) trae el estado como texto libre (''resuelta'', ''asignado''...) -- traduce cada uno a una columna real del proyecto destino. Lo que no este aqui cae en la primera columna que no sea "Hecha".', 'config', ''),
    ('config.mantis_csv_map_estado_label', 'Estado en Mantis', 'config', ''),
    ('config.mantis_csv_map_columna_label', 'Columna destino', 'config', ''),
    ('config.mantis_csv_map_add_btn', '+ Anadir fila', 'config', ''),
    ('config.mantis_csv_map_quitar', 'Quitar', 'config', ''),
    ('config.mantis_csv_importar_titulo', 'Importar CSV de Mantis', 'config', ''),
    ('config.mantis_csv_importar_desc', 'Sube el .csv tal cual lo exporta Mantis (no la plantilla propia de Excel) -- pensado para volcar de una vez todo el historico de un proyecto. Las incidencias que ya se hubieran importado antes (por su Id.) no se duplican.', 'config', ''),
    ('config.mantis_csv_importar_btn', 'Importar', 'config', ''),
    ('config.api_nav_label', 'API', 'config', ''),
    ('config.api_titulo', 'Claves de la API externa', 'config', ''),
    ('config.api_desc', 'Para crear/consultar tareas desde un script externo (curl, Python...) sin pasar por el navegador. Cada clave puede restringirse a un solo proyecto. El valor en claro solo se muestra una vez, al crearla, a partir de ahi solo se puede revocar y crear una nueva.', 'config', ''),
    ('config.api_nombre_label', 'NOMBRE (para identificarla luego)', 'config', ''),
    ('config.api_proyecto_label', 'PROYECTO (opcional)', 'config', ''),
    ('config.api_todos_proyectos', 'Todos los proyectos', 'config', ''),
    ('config.api_crear_btn', 'Crear token', 'config', ''),
    ('config.api_tabla_nombre', 'Nombre', 'config', ''),
    ('config.api_tabla_proyecto', 'Proyecto', 'config', ''),
    ('config.api_tabla_creado', 'Creado', 'config', ''),
    ('config.api_tabla_ultimo_uso', 'Ultimo uso', 'config', ''),
    ('config.api_ultimo_uso_nunca', 'Nunca', 'config', ''),
    ('config.api_revocar_btn', 'Revocar', 'config', ''),
    ('config.api_revocar_confirm', 'Revocar este token? Cualquier script que lo use dejara de funcionar inmediatamente.', 'config', ''),
    ('config.api_sin_tokens', 'No hay ninguna clave creada todavia.', 'config', ''),
    ('config.api_maestra_activa', 'Tambien esta activa la clave maestra de .env (API_IMPORT_TOKEN), con acceso a todos los proyectos.', 'config', ''),
    ('config.api_maestra_inactiva', 'La clave maestra de .env (API_IMPORT_TOKEN) no esta configurada.', 'config', ''),
    ('config.calendario_sync_nav_label', 'Calendario externo', 'config', ''),
    ('config.calendario_sync_titulo', 'Sincronizar reuniones', 'config', ''),
    ('config.calendario_sync_desc', 'Guarda aquí la URL del feed ICS que publiques desde tu calendario de Outlook/Office 365 (Configuración → Calendario → Publicar calendario). Es un ajuste por usuario. De momento solo se guarda la URL — la sincronización automática todavía no está construida.', 'config', ''),
    ('config.calendario_sync_url_label', 'URL DEL FEED ICS', 'config', ''),
    ('config.calendario_sync_url_placeholder', 'https://outlook.office365.com/owa/calendar/.../calendar.ics', 'config', ''),
    ('config.calendario_sync_btn', 'Sincronizar ahora', 'config', ''),
    ('config.calendario_sync_sincronizando', 'Sincronizando…', 'config', ''),
    ('config.calendario_sync_ok_prefijo', 'Reuniones sincronizadas:', 'config', ''),
    ('config.calendario_sync_error', 'No se pudo sincronizar.', 'config', ''),
    ('mantis.nav_label', 'Mantis', 'mantis', ''),
    ('mantis.pagina_titulo', 'Incidencias de Mantis', 'mantis', ''),
    ('mantis.destino_actual_prefijo', 'Proyecto destino:', 'mantis', ''),
    ('mantis.cambiar_destino', 'Cambiar', 'mantis', ''),
    ('mantis.boton_importar', 'Importar de Mantis', 'mantis', ''),
    ('mantis.modal_titulo', 'Incidencias del pool', 'mantis', ''),
    ('mantis.modal_desc', 'Incidencias no resueltas de Mantis. Elige las que quieras traer a este proyecto.', 'mantis', ''),
    ('mantis.sin_incidencias', 'No hay incidencias disponibles.', 'mantis', ''),
    ('mantis.importar_seleccionadas', 'Importar seleccionadas', 'mantis', ''),
    ('mantis.error_prefijo', 'No se pudo consultar Mantis:', 'mantis', ''),
    ('mantis.proyecto_no_configurado', 'Configura primero el proyecto destino en Configuración → Mantis.', 'mantis', ''),
    ('mantis.asignada_a_label', 'Asignada a', 'mantis', ''),
    ('mantis.reporta_label', 'Reporta', 'mantis', ''),
    ('mantis.leyenda_pool', 'Incidencias', 'mantis', ''),
    ('mantis.leyenda_sin_asignar', 'Sin asignar', 'mantis', ''),
    ('mantis.leyenda_tuya', 'Negrita = tuya (reportada o asignada a ti)', 'mantis', ''),
    ('mantis.tu_marca', 'tú', 'mantis', ''),
    ('mantis.mover_solo_importar', 'Solo importar', 'mantis', ''),
    ('mantis.mover_prefijo', 'Importar y mover a', 'mantis', ''),
    ('mantis.movidas_fallidas_aviso', 'Se importaron las tareas, pero no se pudo mover en Mantis:', 'mantis', ''),
    ('mantis.ya_importadas_aviso', 'Ya estaban importadas (no se duplicaron): #', 'mantis', ''),
    ('mantis.no_se_movera', 'no se moverá', 'mantis', ''),
    ('mantis.empresa_manual_label', 'Empresa:', 'mantis', ''),
    ('mantis.empresa_manual_placeholder', '— elegir —', 'mantis', '');

-- ────────────────────────────────────────────────────────────
-- Catalogos base genericos. Empresas, sistemas e iniciativas los define cada
-- instalacion en Configuracion (o los trae scripts/datos_demo.py).
-- 5 categorias globales:
INSERT INTO categorias (id, proyecto_id, nombre, color, orden, activo) VALUES
    ('cat-incidencia', NULL, 'Incidencia',      '#dc2626', 1, TRUE),
    ('cat-peticion',   NULL, 'Petición/Mejora', '#2563eb', 2, TRUE),
    ('cat-desarrollo', NULL, 'Desarrollo',      '#16a34a', 3, TRUE),
    ('cat-doc',        NULL, 'Documentación',   '#6b7280', 4, TRUE),
    ('cat-infra',      NULL, 'Infraestructura', '#ca8a04', 5, TRUE);

-- tipos de dia especial (catalogo editable, Configuracion -> Calendario):
INSERT INTO tipos_dia_especial (id, nombre, categoria, color, orden, activo, urgente, cuenta_para_sla) VALUES
    ('tde-teletrabajo', 'Teletrabajo', 'sede',      '#16a34a', 1, TRUE, FALSE, FALSE),
    ('tde-vacaciones',  'Vacaciones',  'anotacion', '#0891b2', 1, TRUE, FALSE, FALSE),
    ('tde-festivo',     'Festivo',     'anotacion', '#dc2626', 2, TRUE, FALSE, TRUE),
    ('tde-compensado',  'Compensado',  'anotacion', '#84cc16', 3, TRUE, FALSE, FALSE),
    ('tde-aviso',       'Aviso',       'banner',    '#ca8a04', 1, TRUE, FALSE, FALSE),
    ('tde-alarma',      'Alarma',      'banner',    '#e11d48', 2, TRUE, TRUE, FALSE);

-- ────────────────────────────────────────────────────────────
-- recordatorio_mensajes: lista de mensajes del Recordatorio ergonomico
-- (antes APP_RECORDATORIO/data/messages.txt, ahora integrado en la app --
-- ver app_fastapi/escritorio_servicios.py). Se edita desde Configuracion ->
-- Recordatorio; el resto de su configuracion (intervalo, horario, icono...)
-- vive en ajustes_app con el prefijo 'recordatorio.'.
CREATE TABLE recordatorio_mensajes (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    texto           VARCHAR(500) NOT NULL,
    categoria       VARCHAR(50)  NOT NULL DEFAULT '',
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    orden           INT NOT NULL DEFAULT 0,
    veces_mostrado  INT NOT NULL DEFAULT 0,
    ultimo_mostrado DATETIME NULL,
    creado_en       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
-- Buzon (notas entre personas) + notificaciones de la campana: fase 1 de
-- mensajeria inspirada en CS Manager (otra app interna). Ver routers/buzon.py
-- y routers/notificaciones.py.
CREATE TABLE buzon_notas (
    id                      INT AUTO_INCREMENT PRIMARY KEY,
    de_user_id              INT NOT NULL,
    para_user_id            INT NOT NULL,
    contenido               TEXT NOT NULL,
    leida                   BOOLEAN NOT NULL DEFAULT FALSE,
    leida_en                DATETIME NULL,
    vence_en                DATE NULL,
    aviso_cantidad          SMALLINT NOT NULL DEFAULT 1,
    aviso_unidad            VARCHAR(10) NOT NULL DEFAULT 'dias',
    recordatorio_enviado_en DATETIME NULL,
    reenviada_de            INT NULL,
    creada_en               DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    editada_en              DATETIME NULL,
    FOREIGN KEY (de_user_id)   REFERENCES auth_user(id) ON DELETE CASCADE,
    FOREIGN KEY (para_user_id) REFERENCES auth_user(id) ON DELETE CASCADE,
    FOREIGN KEY (reenviada_de) REFERENCES buzon_notas(id) ON DELETE SET NULL,
    INDEX idx_buzon_para (para_user_id, leida),
    INDEX idx_buzon_de (de_user_id)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE buzon_nota_tareas (
    nota_id  INT NOT NULL,
    tarea_id VARCHAR(32) NOT NULL,
    PRIMARY KEY (nota_id, tarea_id),
    FOREIGN KEY (nota_id)  REFERENCES buzon_notas(id) ON DELETE CASCADE,
    FOREIGN KEY (tarea_id) REFERENCES tareas(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE notificaciones (
    id        INT AUTO_INCREMENT PRIMARY KEY,
    user_id   INT NOT NULL,
    tipo      VARCHAR(30)  NOT NULL,
    texto     VARCHAR(300) NOT NULL,
    url       VARCHAR(300) NOT NULL DEFAULT '',
    leida     BOOLEAN NOT NULL DEFAULT FALSE,
    creada_en DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES auth_user(id) ON DELETE CASCADE,
    INDEX idx_notif_user (user_id, leida, creada_en)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ────────────────────────────────────────────────────────────
-- Salas y mensajes del muro de actividad (uno por espacio; cada mensaje puede
-- llevar su proyecto). Hoy solo hay salas tipo 'muro': los chats directos y
-- de grupo se quitaron (scripts/migrar_unificar_muro.py). Ver muro.py.
CREATE TABLE chat_salas (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    tipo       VARCHAR(10)  NOT NULL DEFAULT 'muro',
    espacio_id VARCHAR(32)  NULL UNIQUE,
    nombre     VARCHAR(200) NOT NULL DEFAULT '',
    creada_en  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (espacio_id) REFERENCES espacios(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE chat_mensajes (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    sala_id    INT NOT NULL,
    user_id    INT NULL,
    contenido  TEXT NOT NULL,
    url        VARCHAR(300) NOT NULL DEFAULT '',
    es_sistema BOOLEAN NOT NULL DEFAULT FALSE,
    es_aviso   BOOLEAN NOT NULL DEFAULT FALSE,
    caduca_en  DATETIME NULL,
    borrado_en DATETIME NULL,
    -- muro: de que proyecto del espacio es el mensaje (NULL = del espacio en general)
    proyecto_id VARCHAR(32) NULL,
    creado_en  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sala_id) REFERENCES chat_salas(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES auth_user(id) ON DELETE SET NULL,
    INDEX idx_chat_mensajes_sala (sala_id, id),
    INDEX idx_chat_mensajes_proyecto (sala_id, proyecto_id, id)
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE chat_lecturas (
    sala_id         INT NOT NULL,
    user_id         INT NOT NULL,
    ultimo_leido_id INT NOT NULL DEFAULT 0,
    silenciada      BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (sala_id, user_id),
    FOREIGN KEY (sala_id) REFERENCES chat_salas(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES auth_user(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ────────────────────────────────────────────────────────────
-- conectores: modulo opcional "conectores de entrada" (MODULO_CONECTORES,
-- app_fastapi/conectores/). Cada fila es una fuente externa configurada
-- (tipo = clave de conectores.TIPOS) cuyos elementos se convierten en tareas
-- de proyecto_id. config = JSON con los campos del tipo; los de tipo
-- 'secreto' van cifrados (AES-GCM, clave CONECTORES_CLAVE o
-- SESSION_SECRET_KEY). intervalo_min = 0 -> solo a mano.
CREATE TABLE conectores (
    id               VARCHAR(32)  PRIMARY KEY,
    nombre           VARCHAR(150) NOT NULL,
    tipo             VARCHAR(40)  NOT NULL,
    config           TEXT         NOT NULL,
    proyecto_id      VARCHAR(32)  NULL,
    estado_inicial   VARCHAR(100) NOT NULL DEFAULT '',
    asignar_a        INT NULL,
    activo           BOOLEAN NOT NULL DEFAULT TRUE,
    intervalo_min    INT NOT NULL DEFAULT 0,
    ultima_sync      DATETIME NULL,
    ultimo_resultado VARCHAR(500) NOT NULL DEFAULT '',
    ultimo_ok        BOOLEAN NULL,
    creado_en        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (proyecto_id) REFERENCES proyectos(id) ON DELETE SET NULL,
    FOREIGN KEY (asignar_a) REFERENCES auth_user(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- que elementos externos ya se convirtieron en tarea (evita duplicados: un
-- mismo id_externo del mismo conector nunca crea dos tareas, aunque la tarea
-- se borre despues)
CREATE TABLE conector_elementos (
    conector_id VARCHAR(32)  NOT NULL,
    id_externo  VARCHAR(191) NOT NULL,
    tarea_id    VARCHAR(32)  NULL,
    creado_en   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (conector_id, id_externo),
    FOREIGN KEY (conector_id) REFERENCES conectores(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
