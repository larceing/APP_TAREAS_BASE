# Versiones y aplicaciones, sin terminal

Todo se hace desde la portada de DEV o de PRO (`https://dev.tudominio.com/`,
`https://pro.tudominio.com/`): arriba a la derecha, **⚙ Ajustes**, que abre
`https://pro.tudominio.com/ajustes/` (el mismo desde las dos portadas). Solo lo ve
quien está en el grupo `IT` de Keycloak; el Admin de una sola app no lo ve. No
hace falta entrar en GitHub ni en el servidor: el panel se lo pide a GitHub por
detrás y te enseña el resultado.

En Ajustes hay **una tarjeta por aplicación** (Tareas, las creadas desde aquí y
las que tienen su propio repositorio), cada una con su versión en DEV y en PRO
y los mismos botones.

Si no ves **⚙ Ajustes** siendo de IT, pulsa **Salir** (arriba a la derecha de
la portada, junto a tu usuario) y vuelve a entrar: la sesión de antes no sabía
aún que eres IT. **Salir** también sirve para entrar con otro usuario.

## Lo que tienes que saber

- **DEV** es para probar. Cada cambio que se guarda en el código llega solo a
  DEV en unos minutos. Puedes romperlo sin miedo.
- **PRO** es lo que usa la gente. Solo cambia cuando tú lo apruebas.
- Una **versión** (`v1.0.0`, `v1.0.1`...) es una foto de lo que había en DEV.
  Se puede volver a cualquiera de antes.
- Si una versión nueva no arranca, el servidor **vuelve solo** a la anterior.
  En PRO, además, guarda una copia de la base de datos antes de cada cambio.

## El día a día

### Pasar a PRO lo que ya funciona en DEV

1. Prueba en DEV lo que hayas cambiado.
2. En la tarjeta de la app, pulsa **Pasar a PRO**. En Tareas eliges antes qué
   trae (*Arreglos* es lo normal); las demás apps ponen en PRO justo la versión
   que tiene DEV.
3. Espera unos 5 minutos: la casilla de PRO enseña la versión nueva con el
   punto verde. Ya está.

Si en algún momento sale un aviso amarillo con **Aprobar**, es una versión
esperando tu visto bueno para PRO: púlsalo.

### Algo ha ido mal en PRO

En la tarjeta de la app, en PRO, pulsa **↩ Anterior**. En unos minutos PRO
vuelve a estar como antes. (DEV tiene el mismo botón.) Si una app no lo
tiene, escribe la versión de antes y pulsa **Poner**.

### Saber qué ha pasado

- Cada tarjeta dice qué versión tiene la app en DEV y en PRO. El punto verde
  quiere decir que responde.
- En la de Tareas, **Últimas ejecuciones y versiones** dice si cada paso fue
  *bien* o *falló*. *detalle* abre lo que pasó.

## Otras aplicaciones

En el mismo servidor caben más apps, cada una en DEV y en PRO, con el mismo
inicio de sesión de siempre (Keycloak).

### Crear una

En **Ajustes → Crear una aplicación nueva**:

- **Nombre**: lo que se ve en la portada (*Inventario*).
- **Ruta**: cómo se llega a ella (`inventario` → `dev.tudominio.com/inventario/`).
- **Imagen**: dónde está la app empaquetada, sin versión
  (`ghcr.io/usuario/inventario`). Te la da quien la programa.
- **Puerto** y **Comprobación**: te los da quien la programa. Si no sabes,
  deja los que vienen.

Pulsa **Crear**. En *Últimas peticiones* sale *hecho* cuando está lista. Para
que funcione hay que ponerle una versión: en su tarjeta, escribe la versión en DEV
(p. ej. `v1.0.0`) y pulsa **Poner**. Cuando va bien en DEV, haz lo mismo en PRO.

### Quién puede entrar

En Keycloak (`https://users.<tu dominio>/auth/admin/`, realm **general**), cada
app tiene sus grupos: `/DEV/Inventario` y `/PRO/Inventario`, y dentro `Admin`
para quien la administra. Abre la persona → *Groups* → *Join group*. Quien está
en `IT` entra en todas.

### Añadir una app que ya tiene su propio repositorio

Si la app se despliega con su propio workflow de GitHub (otro proyecto), no
hace falta tocarla: **Ajustes → Añadir una app que ya existe**, con su ruta en
la portada, su repositorio, el nombre del fichero del workflow y cómo llama
ese workflow a los campos del entorno y de la versión (te lo dice quien la
programa). El token de *Conexión con GitHub* tiene que ver también ese
repositorio: en GitHub, edita el token y añádelo en *Repository access*.

## Darle a una app su propio dominio

Cuando una app de PRO ya va bien y quieres que tenga su dirección
(`inventario.tudominio.com`):

1. En tu DNS (Cloudflare o el que uses) crea un registro **A** con ese nombre
   hacia la IP del servidor, con el proxy **apagado** (nube gris).
2. En el panel, **Llevar una app de PRO a su dominio**: elige la app, escribe
   el dominio y pulsa **Poner dominio**.

El servidor hace el resto: el proxy, el certificado y el inicio de sesión. La
dirección de antes sigue funcionando.

La primera vez, el servidor necesita el usuario de Nginx Proxy Manager para
poder crear el proxy. Es lo único que se hace en el servidor, una sola vez:
`/opt/apps/tareas/tareas.sh npm-acceso`.

## Si algo falla

| Lo que ves | Qué hacer |
|---|---|
| *Últimas peticiones* o *Últimas ejecuciones* dice **falló** | Pulsa *respuesta* o *detalle*: la última parte dice por qué, en castellano |
| La tarjeta de la portada dice *Sin desplegar o arrancando* | Aún no tiene versión, o está arrancando: espera un minuto |
| Sale *Esta aplicación no está disponible* | Igual: se está actualizando o no tiene versión en ese entorno |
| *«... dominio aún no apunta a ningún sitio»* | El registro del DNS aún no existe o no ha llegado: espera unos minutos y vuelve a pulsar |
| El panel dice que *GitHub no acepta el token* | El token ha caducado: crea otro (ver `docs/DESPLIEGUE.md`, paso 6) y pégalo en *Conexión con GitHub* |

Los detalles técnicos están en [DESPLIEGUE.md](DESPLIEGUE.md).
