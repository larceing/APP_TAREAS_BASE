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
| Crear otra aplicación | *Otras aplicaciones → Crear una aplicación* |
| Versión de otra aplicación | Su fila en *Otras aplicaciones* → *Poner* o *↩* |
| Dominio propio para una app de PRO | *Llevar una app de PRO a su dominio* |

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
./tareas.sh portada                 # rehace la portada de DEV y PRO
./tareas.sh copia pro               # copia de la BD ahora
./tareas.sh restaurar pro FICHERO   # volver la BD a una copia (hace otra antes)
./tareas.sh pro-a-dev               # copia los datos de PRO en DEV para probar con datos reales
./tareas.sh importar pro ORIGEN     # datos de una instalación de antes (ver más abajo)
./tareas.sh publicar URL ALIAS      # PRO toma su dirección (ver más abajo)
```

**Cambiar la configuración** de un entorno (marca, login, módulos): edita
`<entorno>/app.env` y vuelve a desplegar su versión actual
(`./tareas.sh desplegar pro $(grep ^VERSION= pro/.env | cut -d= -f2)`).

## Login con Keycloak (todas las apps)

Para que los usuarios y sus permisos se gestionen en Keycloak y una sola
sesión valga para todas las apps del realm (`AUTH_MODO=sso`):

1. **Grupos** (Groups), uno por app con subgrupos:

   | Grupo | Qué da |
   |---|---|
   | `IT` | Entra en todas las apps y las administra |
   | `/Tareas` | Entra en el Gestor de Tareas |
   | `/Tareas/Admin` | Administra solo el Gestor de Tareas |
   | `/Tareas/<Departamento>` | Entra (para separar por departamento) |

   Quien no esté en `/Tareas` (ni en un subgrupo, ni en `IT`) no puede entrar,
   aunque sea admin de otra app.

2. **Cliente** por entorno (Clients → *Create client*), p. ej. `tareas-dev`:
   *Client authentication* activado, *Standard flow* activado,
   *Valid redirect URIs* = `https://dev.<dominio>/tareas/login/sso/`,
   *Valid post logout redirect URIs* = `https://dev.<dominio>/*`.
   En *Client scopes* → `tareas-dev-dedicated` → *Add mapper* → *By
   configuration* → *Group Membership*: *Token Claim Name* `groups`,
   **Full group path activado**, *Add to userinfo* activado.
   Copia el secreto de *Credentials*.

3. **En el servidor**, con la versión que trae este cambio ya desplegada:

   ```bash
   ./tareas.sh keycloak dev https://dev.<dominio>/tareas https://<keycloak>/auth/realms/<realm>
   ```

   Pide el client secret (no se ve al escribirlo), lo guarda en `dev/app.env`
   y vuelve a arrancar el entorno. Igual con `pro` y su cliente `tareas-pro`.
   Otro nombre de grupo: `GRUPO_APP=Otro ./tareas.sh keycloak ...`.

Con `sso`, el usuario `admin` local deja de servir: se entra siempre por
Keycloak y la primera vez se da de alta sola la persona en la app.

## Dominio propio de una app

Desde el panel: *Otras aplicaciones → Llevar una app de PRO a su dominio*
(sirve también para esta app). Antes, en el DNS, un registro `A` con ese
nombre hacia el servidor, **sin proxy**. El servidor (`tareas.sh dominio APP
DOMINIO`) crea el *Proxy Host* en Nginx Proxy Manager con certificado, añade
la dirección al cliente de PRO en Keycloak y vuelve a arrancar la app con ella
(`APP_URL_PUBLICA`). La dirección de antes queda en `APP_URLS_ALTERNATIVAS` y
sigue funcionando: el login vuelve siempre por donde se entró.

Para que el servidor pueda crear el *Proxy Host*, una vez y en el servidor:
`./tareas.sh npm-acceso` (pide el email y la contraseña del admin de Nginx
Proxy Manager; se guardan en `.npm.env`, solo para root).

## Otras apps en los entornos

Desde el panel: *Otras aplicaciones → Crear una aplicación* (nombre, ruta,
imagen sin versión y puerto). El servidor (`tareas.sh app-nueva`) la deja
lista en DEV y PRO:

- `apps/<ruta>/<entorno>/` con su `.env` (imagen y versión), su `app.env` y su
  `docker-compose.yml`; el contenedor se llama `<ruta>-<entorno>` en la red del
  proxy y guarda lo suyo en el volumen `/datos`.
- La entrada de cada entorno le manda `/<ruta>/` **quitando el prefijo** (la app
  vive en `/`; la ruta le llega en `X-Forwarded-Prefix`) y sale su tarjeta en la
  portada.
- En Keycloak, el mismo de todo el servidor: clientes `<ruta>-dev` y
  `<ruta>-pro` y grupos `/DEV/<Ruta>` y `/PRO/<Ruta>` (con `/Admin`). Dar acceso
  a alguien es meterlo en esos grupos.

La app recibe en su `app.env` lo que necesita para el login: `APP_URL_PUBLICA`,
`AUTH_MODO=sso`, `KEYCLOAK_ISSUER`, `KEYCLOAK_CLIENT_ID`,
`KEYCLOAK_CLIENT_SECRET`, `KEYCLOAK_GRUPO_APP` (`DEV/<Ruta>` o `PRO/<Ruta>`) y
`KEYCLOAK_GRUPO_ADMIN_GLOBAL=IT`. Tiene que responder 200 en el camino de
comprobación (o en `/`): así sabe el servidor que una versión arranca bien; si
no, vuelve sola a la anterior.

Versiones: cada fila de la app en el panel tiene *Poner* (una etiqueta de su
imagen, p. ej. `v1.0.0`) y *↩* (volver a la anterior) para DEV y para PRO. Si la
imagen es privada en ghcr.io, en el paquete → *Package settings → Manage
Actions access* hay que dar lectura a este repositorio.

Una app que no se crea así (como Lin-AI) también puede sumarse: un fichero
`entrada/<entorno>/apps/<app>.conf` como `tareas.conf`, y `./tareas.sh portada`.
La línea `# app: Nombre` es su tarjeta en la portada; con `# salud: <camino>`
(por defecto `version/`) la portada pide `<ruta><camino>` para ver si está en
marcha, y su versión si responde JSON con `"version"`. Si la app no responde,
la entrada enseña una página de "no disponible" en vez de un 502.

## Una instalación de antes pasa a ser PRO

Cuando ya había un Gestor de Tareas suelto (con sus datos y su dirección, p.
ej. detrás de un portal que manda `/tareas` a `spsil-tareas:8000`) y se quiere
que a partir de ahora sea el PRO de este sistema, con versiones desde el panel.
En el servidor, en `/opt/apps/tareas`, una orden detrás de otra (lo que se
escriba entre las dos en la instalación de antes no pasa):

```bash
# 1. sus datos y sus adjuntos a PRO (antes guarda copia de lo que hay en PRO)
./tareas.sh importar pro <contenedor-de-su-bd> <contenedor-de-su-app>
# 2. PRO toma su dirección y su nombre en la red del proxy
./tareas.sh publicar https://portal.tudominio.com/tareas spsil-tareas Tareas
```

`importar` acepta también un volcado (`.sql` o `.sql.gz`) en vez del
contenedor; si en el contenedor hay más de una base, se elige con
`BD_ORIGEN=<base> ./tareas.sh importar ...`.

`publicar URL [ALIAS|-] [GRUPO]`:

- añade la dirección al cliente `tareas-pro` de Keycloak, la pone en
  `APP_URL_PUBLICA` (la de `pro.<dominio>/tareas` queda en
  `APP_URLS_ALTERNATIVAS` y sigue valiendo) y, si la dirección acaba en
  `/tareas`, pone `APP_RUTA_BASE=/tareas` (el portal de delante no avisa de la ruta);
- con `GRUPO`, cambia quién entra (`KEYCLOAK_GRUPO_APP`): p. ej. `Tareas`, el
  grupo que ya usaba la instalación de antes, en vez de `PRO/Tareas`;
- con `ALIAS`, PRO responde también a ese nombre en la red del proxy
  (`ALIAS_PUBLICO`) y se **para** (no se borra) lo que respondía a él; el
  portal no se toca. Necesita una versión de PRO que ya traiga este cambio;
- vuelve a arrancar PRO y comprueba que responde por ese nombre. Si algo
  falla, deja todo como estaba y vuelve a arrancar la instalación de antes.

Volver a la de antes a mano: `docker start <su contenedor>`, y en `pro/.env` y
`pro/app.env` quitar lo que puso `publicar`.

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
