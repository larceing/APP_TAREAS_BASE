# Despliegue por entornos: DEV y PRO

Dos entornos generales en el mismo servidor, cada uno con **un** dominio que
comparten todas las apps que se sumen a este sistema (cada app en su ruta):

| Entorno | Para qué | Se actualiza | Dirección de esta app |
|---|---|---|---|
| **DEV** | Probar cualquier cambio en cuanto llega a `main` | Solo, en cada push a `main` | `dev.tudominio.com/tareas/` |
| **PRO** | Probar en producción una versión ya cerrada | Al sacar una versión, tras pulsar **Aprobar** | `pro.tudominio.com/tareas/` |

Cuando una app sale de verdad, se le da **su propio dominio** (p. ej.
`tareas.tudominio.com`) apuntando a su instancia de PRO: no hay que mover nada
ni se rompe nada, la misma instancia contesta en las dos direcciones (ver
[Dominio propio de una app](#dominio-propio-de-una-app)). Las apps que no
entren en este sistema siguen desplegándose como siempre.

Todo pasa por git: cada versión es una etiqueta (`v1.0.0`, `v1.1.0`...) y una
imagen Docker con ese mismo nombre en GitHub Packages (`ghcr.io`). Volver atrás
es poner la imagen anterior, que sigue guardada en el servidor.

```
push a main ──► pruebas ──► imagen sha-1a2b3c4 ──► DEV
release v1.2.0 ──► pruebas ──► imagen v1.2.0 ──(Aprobar)──► PRO
"Run workflow" ──► cualquier versión ya construida, o "anterior", al entorno que elijas
pull request ──► solo pruebas
```

El camino de un cambio: se prueba en DEV, se saca como versión y pasa a PRO; si
además hay un cliente con su propia instalación, se le lleva esa misma versión
(ver [Pasar una versión al cliente](#pasar-una-versión-al-cliente)).

Si una versión no arranca, el servidor vuelve solo a la que había.

Todo esto se maneja **sin terminal** desde la propia app: *Configuración →
Despliegues* (en DEV y PRO) enseña qué versión tiene cada entorno y tiene
botones para sacar una versión nueva, ponerla en un entorno, volver a la
anterior y aprobar el paso a PRO. Ver [Panel de despliegues](#panel-de-despliegues).

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
  dev/ pro/
    .env         secretos y versión actual (no sale del servidor)
    app.env      marca, módulos y login de ese entorno
    historial.log
  copias/<entorno>/   copia de la BD antes de cada despliegue en pro
```

Los dos entornos comparten **una** MariaDB (menos memoria), pero cada uno tiene
su usuario y solo ve sus bases (`app_tareas_dev`, `app_tareas_pro`).
DEV arranca con datos de demostración; PRO, vacío. Memoria máxima por
defecto: 512 MB para DEV, 768 MB para PRO y 1 GB para MariaDB (se cambian
con `APP_MEMORIA` en `<entorno>/.env` y `BD_MEMORIA`/`BD_BUFFER` en `bd/.env`).

## Puesta en marcha (una vez)

### 1. DNS

Dos registros `A` hacia la IP del servidor (en Cloudflare, con la nube en gris,
*DNS only*, para que el proxy pueda sacar el certificado). Sirven para todas
las apps, así que solo se crean una vez:

| Tipo | Nombre | Valor |
|---|---|---|
| A | `dev` | IP del servidor |
| A | `pro` | IP del servidor |

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
(por defecto `22`), y `URL_DEV` y `URL_PRO` para que GitHub enseñe el
enlace de cada entorno.

**Environments**: `dev` y `pro`, con *Required reviewers* en **pro** (tú)
para que nada llegue a producción sin tu aprobación. Lo hace solo el botón
*Crear los entornos en GitHub* del panel (paso 6); a mano: *Settings →
Environments → New environment*.

Mientras falten los secretos, las pruebas y las imágenes se hacen igual y el
paso de desplegar solo avisa.

### 4. Nginx Proxy Manager

Un *Proxy Host* por entorno, los dos con *Block Common Exploits*, *Websockets
Support* y en la pestaña SSL *Request a new SSL Certificate* + *Force SSL*.
Apuntan a la **entrada** de cada entorno (un nginx pequeño que crea `preparar`
y que reparte por ruta: `/tareas/` a esta app, y las que se sumen después):

| Domain Names | Forward Hostname | Port |
|---|---|---|
| `dev.tudominio.com` | `entrada-dev` | `80` |
| `pro.tudominio.com` | `entrada-pro` | `80` |

En *Advanced*: `client_max_body_size 50m;`

### 5. Primer despliegue

Haz un push a `main` (o *Actions → Despliegue → Run workflow*, `dev`): DEV queda
en marcha. Entra con `admin` y la contraseña de
`grep INSTALAR_ADMIN_PASSWORD /opt/apps/tareas/*/.env`, y cámbiala.

### 6. Panel de despliegues

En DEV (y luego en PRO, que se rellena igual) → *Configuración → Despliegues →
Conexión con GitHub*:

- **Repositorio**: `usuario/nombre`.
- **Token**: en GitHub, tu foto → *Settings → Developer settings → Personal access
  tokens → Fine-grained tokens → Generate new token*. *Repository access*: solo
  este repositorio. *Permissions → Repository*: **Actions**, **Contents**,
  **Deployments** y **Administration** en *Read and write* (Administration solo
  hace falta para el botón de crear entornos; se puede quitar después).
  Se pega en el panel y se guarda cifrado; no se vuelve a enseñar.
- **Direcciones** de DEV y PRO: `https://dev.tudominio.com/tareas` y
  `https://pro.tudominio.com/tareas` (o su dominio propio, si ya lo tiene).

Guarda, pulsa *Crear los entornos en GitHub* y saca la primera versión con
*Crear versión* (será la `v1.0.0`).

## Panel de despliegues

*Configuración → Despliegues* (solo IT, módulo `MODULO_DESPLIEGUES=1`, que
`preparar` deja activo en DEV y PRO):

| Qué quieres | Qué pulsas |
|---|---|
| Ver qué versión tiene cada entorno | Las tarjetas de arriba (punto verde = responde) |
| Probar un cambio | Nada: cada cambio en `main` llega solo a DEV |
| Sacar una versión | *Sacar una versión nueva* → tipo (arreglos, funciones nuevas, cambios grandes) → *Crear versión* |
| Pasarla a PRO | Aviso amarillo *espera aprobación para PRO* → **Aprobar** |
| Volver atrás | *↩ Volver a la anterior* en la tarjeta del entorno |
| Poner una versión concreta | Escribirla (o elegirla de la lista) en la tarjeta → *Poner* |
| Ver si algo falló | *Últimas ejecuciones* → *detalle* |

El panel no despliega por sí mismo: le pide a GitHub que lance el workflow, así
que todo queda registrado en *Actions* igual que si se hiciera allí. Si PRO no
está en marcha, el panel de DEV sirve igual (y viceversa).

## Sin el panel

Lo mismo se puede hacer desde GitHub o desde el servidor.

**Probar un cambio**: push (o merge de un PR) a `main` → en unos minutos está en DEV.

**Sacar una versión**: GitHub → *Releases* → *Draft a new release* → *Choose a tag*,
escribe la nueva (`v1.3.0`) → *Generate release notes* → *Publish release*.
Se construye y la ejecución queda esperando en *Actions*: *Review deployments* →
`pro` → *Approve and deploy*.

Numeración: `v<grande>.<mediano>.<pequeño>`; sube el último para arreglos, el
del medio para funciones nuevas y el primero para cambios que obligan a algo
(migraciones, configuración nueva).

**Volver atrás (rollback)**:

- Desde GitHub: *Actions → Despliegue → Run workflow*, entorno y versión
  `anterior` (o una concreta, `v1.2.0`). En `pro` también pide aprobación.
- Desde el servidor (lo más rápido si hay prisa, y funciona aunque la app no):
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
./tareas.sh pro-a-dev               # copia los datos de PRO en DEV para probar con datos reales
```

**Cambiar la configuración** de un entorno (marca, login, módulos): edita
`<entorno>/app.env` y vuelve a desplegar su versión actual
(`./tareas.sh desplegar pro $(grep ^VERSION= pro/.env | cut -d= -f2)`).

## Dominio propio de una app

Cuando la app ya se usa de verdad: un registro `A` más (`tareas`) y un *Proxy
Host* `tareas.tudominio.com` → `tareas-pro`, puerto `8000`, con las mismas
opciones. Nada más: la instancia de PRO sigue también en
`pro.tudominio.com/tareas/` y las versiones nuevas llegan a las dos direcciones
a la vez. (La app sabe en qué ruta está por la cabecera `X-Forwarded-Prefix`
que pone la entrada; ver `app_fastapi/ruta_base.py`.)

## Sumar otra app a los entornos

Cada entorno lee `entrada/<entorno>/apps/<app>.conf` (en la carpeta de
`tareas.sh`). Para otra app: su contenedor en la red del proxy y un fichero
como el de `tareas.conf` con su ruta, nombre de contenedor y puerto; luego
`docker exec entrada-dev nginx -s reload`. La línea `# app: Nombre` del fichero
es lo que sale en la portada del entorno. La app tiene que saber vivir bajo una
ruta (enlaces relativos, o leer `X-Forwarded-Prefix`).

## Pasar una versión al cliente

La instalación de un cliente vive en su propio repositorio, que parte de este
y solo añade su configuración. Llevarle una versión
ya probada en tu PRO es traer esa etiqueta y desplegar allí:

```bash
# en el repositorio del cliente, una vez:
git remote add base https://github.com/<usuario>/<este-repo>.git
# cada vez:
git fetch base --tags && git merge v1.3.0 && git push
```

y en su servidor, lo que use esa instalación (`git pull && docker compose up -d --build`,
o este mismo sistema si el cliente también lo tiene).

## Base de datos y rollback

Volver a la imagen anterior no deshace los cambios en la base de datos. Por eso:

- antes de cada despliegue en PRO se guarda una copia en `copias/<entorno>/`
  (se quedan las 15 últimas);
- una versión que cambie el esquema (un `scripts/migrar_<algo>.py`) debe poder
  convivir con la versión anterior, o se acompaña de `restaurar` al volver atrás:
  ```bash
  ./tareas.sh rollback pro v1.1.0
  ./tareas.sh restaurar pro 20261016-224254_antes-de-v1.2.0.sql.gz
  ```
- las migraciones se lanzan a mano tras desplegar:
  `docker exec tareas-pro-app-1 python scripts/migrar_<algo>.py`. Pruébalas antes
  en DEV con datos de PRO (`pro-a-dev`).

## Imágenes

Cada push a `main` crea `sha-<commit>` y `main`; cada release, `v<x.y.z>` y
`latest`. El servidor guarda las de las 4 últimas versiones buenas de cada
entorno (para volver sin descargar nada) y borra las demás.

Si el paquete de `ghcr.io` es privado, el servidor solo puede descargar durante
los despliegues lanzados desde GitHub (reciben un permiso temporal). Para
desplegar desde el servidor una versión que aún no tiene, haz público el paquete
(*Packages* → el paquete → *Package settings* → *Change visibility*) o entra una
vez con `docker login ghcr.io` y un token con permiso `read:packages`.
