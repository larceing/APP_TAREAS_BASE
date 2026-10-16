# Administración

Guía para el equipo de IT que instala y mantiene la aplicación. La instalación inicial está en el [README](../README.md).

Los comandos se lanzan desde la **raíz del repositorio**. Con Docker, hay que anteponer `docker compose exec app`.

## Usuarios y permisos

| Modo de login (`AUTH_MODO`) | Altas | Contraseñas | Quién es IT |
|---|---|---|---|
| `local` | `scripts/usuarios.py crear` | `scripts/usuarios.py password` | `auth_user.is_staff` (`usuarios.py it <user> --si`) |
| `keycloak` | Solas, en el primer login | En Keycloak | Grupo `IT` del realm (claim `groups`) |

**Bajas:** `scripts/usuarios.py activar <user> --no`. Nunca se borra un usuario: de él cuelgan tareas, mensajes y notas.

**Keycloak:**
1. Crear un cliente *confidential* con **Direct Access Grants** activado.
2. Añadir un *protocol mapper* de tipo **Group Membership** con el nombre de claim `groups` (sin la ruta completa) y activarlo en userinfo.
3. Rellenar `KEYCLOAK_ISSUER` (URL del realm, sin barra final), `KEYCLOAK_CLIENT_ID` y `KEYCLOAK_CLIENT_SECRET`.

**Permisos dentro de la app:** los roles por espacio (Admin, Editor, Lector) y sus interruptores se gestionan en cada espacio (*Espacios → el espacio → Miembros y permisos*). Ver [MANUAL_DE_USO.md](MANUAL_DE_USO.md#roles-en-un-espacio-compartido).

> **Ojo:** hoy todo usuario con sesión **ve** todos los proyectos. Los roles limitan lo que se puede **hacer**, no lo que se puede ver. Si dos áreas no deben verse entre sí, conviene una instalación por área, o esperar a que se desarrolle el filtrado de visibilidad por espacio.

## Configuración (pantalla)

Solo IT. Ahí se gestionan:
- los **catálogos**: empresas, categorías, sistemas, iniciativas, días especiales y sus tipos;
- los **textos** de la interfaz;
- las **copias de seguridad**;
- las claves de la **API**;
- el **calendario externo**;
- los módulos activos: Conectores, Nexus, Mantis, Recordatorio, Vigía de carpeta.

Los cambios se aplican al momento, sin reiniciar. Lo que está en el `.env` (marca, módulos, login, base de datos) sí necesita reiniciar la app.

## Entorno real y de pruebas

Si `DB_NAME_TEST` está definido, el menú de usuario permite cambiar entre la base de datos **real** y la de **pruebas**.
- El cambio es **global**: afecta a todos los usuarios. Se guarda en `data/entorno_db.txt`.
- Para rehacer **solo** la base de pruebas desde cero (con demo), lanza el instalador con `DB_NAME` apuntando a ella. Sin ese cambio, `--recrear` borraría también la real:
  ```bash
  DB_NAME=app_tareas_test python scripts/instalar.py --recrear --si --sin-test
  ```

## Copias de seguridad

- **Desde la app:** Configuración → Copias de seguridad → *Hacer backup ahora*.
  - Hace un volcado de la base **real** con `mariadb-dump`/`mysqldump` en `data/backups_bd/`.
  - En Docker la herramienta ya viene incluida. Sin Docker, la busca en el `PATH` o en `MYSQLDUMP_PATH`.
- **Programadas** (recomendado): la app no las programa sola. Hay que usar `cron` o el Programador de tareas, por ejemplo:
  ```bash
  mariadb-dump -h$DB_HOST -u$DB_USER -p --single-transaction --routines $DB_NAME | gzip > /backups/app_$(date +%F).sql.gz
  ```
- **Qué copiar:**
  - la base de datos;
  - la carpeta `media/` (adjuntos, imágenes de wiki, miniaturas de pizarras, iconos);
  - `app_fastapi/.env`.

  En Docker son los volúmenes `bd`, `media` y `datos`.
- **Restaurar:** `mariadb -u root -p app_tareas < copia.sql` con la app parada, y después copiar `media/`.

## Actualizar a una versión nueva

```bash
git pull
docker compose up -d --build        # o, sin Docker: pip install -r app_fastapi/requirements.txt y reiniciar
```

El instalador **no** modifica una base de datos que ya existe. Cuando una versión nueva cambie el esquema, traerá un script en `scripts/` (`migrar_*.py`) que hay que lanzar una vez, y que vendrá indicado en las notas de la versión. Antes de cualquier migración, hacer una copia.

## Registros (logs)

En `app_fastapi/logs/` (volumen `logs` en Docker):

| Fichero | Qué guarda |
|---|---|
| `accesos.log` | Cada petición: usuario, ruta, código y tiempo |
| `cambios.log` | Cada POST (cualquier modificación) |
| `errores.log` | Excepciones no controladas: lo primero que hay que mirar ante un fallo |
| `queries.log` | Todas las consultas SQL (crece rápido: rotarlo o vaciarlo) |
| `escritorio.log` | Servicios en segundo plano y conectores |

## Publicar la app

- Detrás de un proxy inverso (IIS, nginx, Traefik) con **HTTPS**. La app ya respeta `X-Forwarded-*` (`--proxy-headers`).
- `SESSION_SECRET_KEY` **fija**: si cambia, todo el mundo tiene que volver a entrar. Si está vacía, cambia en cada reinicio.
- La API (`/api/*`) se autentica con `X-API-Key`. Si no se va a usar desde fuera, conviene limitarla en el proxy a la red interna.

## Módulos: dónde se configura cada uno

| Módulo | `.env` | Pantalla | Documentación |
|---|---|---|---|
| Conectores | `MODULO_CONECTORES`, `CONECTORES_CLAVE` | Configuración → Conectores | [CONECTORES.md](CONECTORES.md) |
| Nexus | `MODULO_NEXUS` | Configuración → Nexus | [NEXUS_PLAN_DE_ACCION.md](NEXUS_PLAN_DE_ACCION.md) |
| Mantis | `MODULO_MANTIS`, `MANTIS_*` | Configuración → Mantis | — |
| Escritorio | `MODULO_ESCRITORIO` | Configuración → Recordatorio / Vigía de carpeta / Vigilante | — |

**Vigía de carpeta** (módulo Escritorio): vigila una carpeta, por ejemplo la cola de entrada de una integración por ficheros. Avisa por Buzón y campana (y con un aviso emergente en Windows) en cuatro casos:
- aparece un archivo en la subcarpeta de **fallidos**;
- un archivo lleva más de *N* minutos sin procesarse;
- se pierde el acceso a la carpeta;
- cuando cada problema se resuelve.

Sin destinatario configurado no vigila nada.

Los servicios en segundo plano (Escritorio y Conectores) corren en **un solo proceso** de la app (con un fichero de bloqueo en `data/`). Para que un segundo proceso no los arranque: `APP_TAREAS_SIN_ESCRITORIO=1`.
