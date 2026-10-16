# Despliegue por entornos: DEV, PRE y PRO

Tres copias de la app en el mismo servidor, cada una con su subdominio, su base
de datos y su versión:

| Entorno | Para qué | Se actualiza | Ejemplo de dirección |
|---|---|---|---|
| **DEV** | Probar cualquier cambio en cuanto llega a `main` | Solo, en cada push a `main` | `dev-tareas.tudominio.com` |
| **PRE** | Ensayo general de una versión antes de darla por buena | Solo, al publicar una *release* | `pre-tareas.tudominio.com` |
| **PRO** | La que se usa de verdad | Tras pulsar **Approve** en GitHub | `tareas.tudominio.com` |

Todo pasa por git: cada versión es una etiqueta (`v1.0.0`, `v1.1.0`...) y una
imagen Docker con ese mismo nombre en GitHub Packages (`ghcr.io`). Volver atrás
es poner la imagen anterior, que sigue guardada en el servidor.

```
push a main ──► pruebas ──► imagen sha-1a2b3c4 ──► DEV
release v1.2.0 ──► pruebas ──► imagen v1.2.0 ──► PRE ──(Approve)──► PRO
"Run workflow" ──► cualquier versión ya construida, o "anterior", al entorno que elijas
pull request ──► solo pruebas
```

Si una versión no arranca, el servidor vuelve solo a la que había.

## Qué hay en el repositorio

| Fichero | Qué hace |
|---|---|
| `.github/workflows/despliegue.yml` | Pruebas, imagen y despliegue |
| `.github/actions/desplegar/` | Llama al servidor por SSH |
| `despliegue/servidor/tareas.sh` | Todo lo del servidor: preparar, desplegar, rollback, copias |
| `despliegue/servidor/docker-compose.yml` | Un entorno; va dentro de la imagen, así cada versión trae el suyo |

## En el servidor

```
/opt/apps/tareas/
  tareas.sh
  bd/            MariaDB compartida (contenedor tareas-bd, sin puertos abiertos)
  dev/ pre/ pro/
    .env         secretos y versión actual (no sale del servidor)
    app.env      marca, módulos y login de ese entorno
    historial.log
  copias/<entorno>/   copia de la BD antes de cada despliegue en pre y pro
```

Los tres entornos comparten **una** MariaDB (menos memoria), pero cada uno tiene
su usuario y solo ve sus bases (`app_tareas_dev`, `app_tareas_pre`, `app_tareas_pro`).
DEV arranca con datos de demostración; PRE y PRO, vacíos. Memoria máxima por
defecto: 512 MB para DEV y PRE, 768 MB para PRO y 1 GB para MariaDB (se cambian
con `APP_MEMORIA` en `<entorno>/.env` y `BD_MEMORIA`/`BD_BUFFER` en `bd/.env`).

## Puesta en marcha (una vez)

### 1. DNS

Tres registros `A` hacia la IP del servidor (en Cloudflare, con la nube en gris,
*DNS only*, para que el proxy pueda sacar el certificado):

| Tipo | Nombre | Valor |
|---|---|---|
| A | `dev-tareas` | IP del servidor |
| A | `pre-tareas` | IP del servidor |
| A | `tareas` | IP del servidor |

### 2. Servidor

Con el usuario que vaya a desplegar (root, o uno del grupo `docker`):

```bash
mkdir -p /opt/apps/tareas && cd /opt/apps/tareas
curl -fsSLO https://raw.githubusercontent.com/<usuario>/<repo>/main/despliegue/servidor/tareas.sh
chmod 700 tareas.sh
./tareas.sh preparar ghcr.io/<usuario>/<repo>
```

`preparar` (se puede repetir sin miedo, no pisa nada):

- crea las carpetas y genera **en el servidor** todas las contraseñas y claves;
- levanta la MariaDB compartida y crea un usuario por entorno;
- crea la clave SSH con la que GitHub entra, **limitada** a `tareas.sh ci`
  (solo puede desplegar, hacer rollback y consultar; nunca abrir una shell);
- te enseña qué copiar a GitHub.

Si la red del proxy no se llama `proxy_default`: `RED_PROXY=<red> ./tareas.sh preparar ...`.

### 3. GitHub

En el repositorio → *Settings*:

**Secrets and variables → Actions → Secrets**

| Secreto | Valor |
|---|---|
| `DEPLOY_SSH_KEY` | `cat /opt/apps/tareas/.ssh/github_despliegue` (la clave privada entera) |
| `DEPLOY_HOST` | IP o nombre del servidor |
| `DEPLOY_KNOWN_HOSTS` | La línea que imprime `preparar` (o `ssh-keyscan -t ed25519 <servidor>` desde tu PC) |

**Variables** (opcionales): `DEPLOY_USER` (por defecto `root`), `DEPLOY_PORT`
(por defecto `22`), y `URL_DEV`, `URL_PRE`, `URL_PRO` para que GitHub enseñe el
enlace de cada entorno.

**Environments**: crea `dev`, `pre` y `pro`. En **pro** marca *Required reviewers*
y ponte a ti: así nada llega a producción sin que lo apruebes.

Mientras falten los secretos, las pruebas y las imágenes se hacen igual y el
paso de desplegar solo avisa.

### 4. Nginx Proxy Manager

Un *Proxy Host* por entorno, todos con *Block Common Exploits*, *Websockets
Support* y en la pestaña SSL *Request a new SSL Certificate* + *Force SSL*:

| Domain Names | Forward Hostname | Port |
|---|---|---|
| `dev-tareas.tudominio.com` | `tareas-dev` | `8000` |
| `pre-tareas.tudominio.com` | `tareas-pre` | `8000` |
| `tareas.tudominio.com` | `tareas-pro` | `8000` |

En *Advanced*: `client_max_body_size 50m;`

### 5. Primer despliegue

- DEV: haz un push a `main` (o *Actions → Despliegue → Run workflow*, `dev`, versión `sha-xxxxxxx`).
- PRE y PRO: publica la primera release `v1.0.0` (abajo).

Entra con `admin` y la contraseña de `grep INSTALAR_ADMIN_PASSWORD /opt/apps/tareas/*/.env`,
y cámbiala.

## Día a día

**Probar un cambio**: push (o merge de un PR) a `main` → en unos minutos está en DEV.

**Sacar una versión**: GitHub → *Releases* → *Draft a new release* → *Choose a tag*,
escribe la nueva (`v1.3.0`) → *Generate release notes* → *Publish release*.
Se construye, va a PRE y la ejecución queda esperando en *Actions*; cuando la
hayas probado en PRE, *Review deployments* → `pro` → *Approve and deploy*.

Numeración: `v<grande>.<mediano>.<pequeño>`; sube el último para arreglos, el
del medio para funciones nuevas y el primero para cambios que obligan a algo
(migraciones, configuración nueva).

**Volver atrás (rollback)**:

- Desde GitHub: *Actions → Despliegue → Run workflow*, entorno y versión
  `anterior` (o una concreta, `v1.2.0`). En `pro` también pide aprobación.
- Desde el servidor (lo más rápido si hay prisa):
  ```bash
  /opt/apps/tareas/tareas.sh rollback pro            # a la versión buena anterior
  /opt/apps/tareas/tareas.sh rollback pro v1.1.0     # a una concreta
  ```

**Otras órdenes** (en `/opt/apps/tareas`):

```bash
./tareas.sh estado                  # versión y salud de cada entorno
./tareas.sh historial pro           # qué se desplegó y cuándo
./tareas.sh logs pro                # log de la app
./tareas.sh copia pro               # copia de la BD ahora
./tareas.sh restaurar pro FICHERO   # volver la BD a una copia (hace otra antes)
./tareas.sh pro-a-pre               # copia los datos de PRO en PRE para ensayar con datos reales
```

**Cambiar la configuración** de un entorno (marca, login, módulos): edita
`<entorno>/app.env` y vuelve a desplegar su versión actual
(`./tareas.sh desplegar pro $(grep ^VERSION= pro/.env | cut -d= -f2)`).

## Base de datos y rollback

Volver a la imagen anterior no deshace los cambios en la base de datos. Por eso:

- antes de cada despliegue en PRE y PRO se guarda una copia en `copias/<entorno>/`
  (se quedan las 15 últimas);
- una versión que cambie el esquema (un `scripts/migrar_<algo>.py`) debe poder
  convivir con la versión anterior, o se acompaña de `restaurar` al volver atrás:
  ```bash
  ./tareas.sh rollback pro v1.1.0
  ./tareas.sh restaurar pro 20261016-224254_antes-de-v1.2.0.sql.gz
  ```
- las migraciones se lanzan a mano tras desplegar:
  `docker exec tareas-pro-app-1 python scripts/migrar_<algo>.py`. Pruébalas antes
  en PRE con datos de PRO (`pro-a-pre`).

## Imágenes

Cada push a `main` crea `sha-<commit>` y `main`; cada release, `v<x.y.z>` y
`latest`. El servidor guarda las de las 4 últimas versiones buenas de cada
entorno (para volver sin descargar nada) y borra las demás.

Si el paquete de `ghcr.io` es privado, el servidor solo puede descargar durante
los despliegues lanzados desde GitHub (reciben un permiso temporal). Para
desplegar desde el servidor una versión que aún no tiene, haz público el paquete
(*Packages* → el paquete → *Package settings* → *Change visibility*) o entra una
vez con `docker login ghcr.io` y un token con permiso `read:packages`.
