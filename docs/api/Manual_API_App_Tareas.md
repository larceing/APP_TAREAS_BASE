# API de la App de Tareas — manual

Escrito para que **un agente (por ejemplo, Claude) o un script** pueda trabajar con la app teniendo solo la URL de la API y una clave. El caso típico: has hecho un análisis y quieres que se convierta en tareas, notas o mensajes de muro, sin explicar cómo funciona la app.

Este manual también se puede pedir a la propia API: `GET <URL>/manual`.

---

## 1. Qué necesitas

Dos valores, normalmente en un `.env`:

```
APP_TAREAS_API_URL=http://localhost:8000/api
APP_TAREAS_API_KEY=<la clave que da Configuración → API al crear un token>
```

- Todas las llamadas llevan la cabecera `X-API-Key: <clave>`. Sin ella, o con una incorrecta, la respuesta es `401`.
- Cuerpos y respuestas en JSON (UTF-8). Las fechas en formato `AAAA-MM-DD` (también se aceptan `DD/MM/AAAA` y `DD-MM-AAAA`).
- La API solo responde donde corre la app: el PC donde se ejecuta, o la red local. Un agente que se ejecuta en la nube no llegará a `localhost`.

**Quién firma lo que hagas.** Cada clave tiene un dueño: quien la creó en Configuración → API. La API actúa **como esa persona**, con sus mismos permisos. Por ejemplo, en el muro sale "Ana López (vía API: análisis ERP) creó la tarea…". Hay dos excepciones, que firman como "API · …":

- la clave maestra del `.env` del servidor;
- los tokens antiguos sin dueño.

Estas dos no pueden escribir en muros ni enviar notas.

Algunas claves están **restringidas a un proyecto**. Con ellas solo se puede trabajar en ese proyecto, y no se pueden enviar notas.

---

## 2. Cómo está organizada la app (lo mínimo)

- **Espacio** → agrupa **proyectos** y personas (miembros con rol Admin, Editor o Lector).
- **Proyecto** → tiene un **tablero** con **columnas**. Los nombres de las columnas los pone cada proyecto (no hay estados fijos); alguna está marcada como "hecha".
- **Tarea** → vive en una columna de un proyecto. Tiene título, descripción, próximo paso, prioridad (`Normal`, `Alta` o `Baja`), fechas, persona asignada, **subtareas** (una checklist) y, opcionalmente, categoría, sistema, empresa, iniciativa, sprint y nº de Mantis.
- **Muro** → cada espacio tiene uno, y cada proyecto ve la parte que le toca. Ahí se publica sola la actividad y se habla del trabajo.
- **Buzón** → notas de una persona a otra (o a uno mismo), con fecha de vencimiento y recordatorio opcionales.
- **Campana** → los avisos de cada persona.

**Una acción pequeña tiene efectos en varias partes de la app.** Por ejemplo, crear una tarea asignada a alguien:

- guarda la tarea;
- avisa a esa persona en su campana;
- publica "X creó la tarea…" en el muro del proyecto.

La API hace exactamente lo mismo que la web, y cada respuesta lo indica en `efectos`.

---

## 3. Flujo de trabajo recomendado (para agentes)

1. **`GET /api/`** — comprueba la clave y quién vas a ser (`actor`), y si la clave está restringida a un proyecto.
2. **`GET /api/dimensiones/`** — trae los proyectos con sus **columnas reales**, sprints, usuarios y catálogos. **No inventes nada**: proyecto, columna, usuario, categoría, sistema, empresa o iniciativa tienen que salir de aquí. Lo que no coincide se deja vacío y se avisa.
3. **Decide el proyecto.** Si el análisis no dice claramente a qué proyecto va, **pregunta a la persona** antes de crear nada. La API no crea proyectos.
4. **Convierte el análisis en tareas accionables** (ver §5): una tarea por cosa que alguien tiene que hacer, con los pasos como subtareas.
5. **`POST /api/tareas/importar/` con `"simular": true`**. Revisa `se_crearian` y `avisos`, corrige lo que haga falta y, si trabajas con una persona, enséñale el plan.
6. **La misma llamada sin `simular`.** Las tareas con un título ya existente en el proyecto se omiten, así que **se puede reintentar sin duplicar**.
7. Opcional:
   - un mensaje en el muro del proyecto con el resumen del análisis (`POST /api/muro/`);
   - notas a personas concretas (`POST /api/notas/`);
   - mover, asignar o editar tareas ya existentes.
8. **Informa** a la persona: cuántas tareas se crearon, sus ids, los avisos y los `efectos`.

---

## 4. Endpoints

| Método | Ruta | Para qué |
|---|---|---|
| GET | `/api/` | Quién soy y lista de endpoints |
| GET | `/api/manual` | Este manual (Markdown) |
| GET | `/api/dimensiones/` | Proyectos (columnas, sprints), usuarios y catálogos |
| GET | `/api/tareas/` | Consultar tareas (filtros) |
| GET | `/api/tareas/<id>/` | Una tarea |
| POST | `/api/tareas/` | Crear **una** tarea |
| POST | `/api/tareas/importar/` | Crear **muchas** (con `simular`) |
| POST | `/api/tareas/<id>/` | Editar solo los campos enviados |
| POST | `/api/tareas/<id>/mover/` | Cambiar de columna |
| POST | `/api/tareas/<id>/asignar/` | Asignar o quitar la asignación |
| POST | `/api/tareas/<id>/eliminar/` | A la papelera |
| POST | `/api/tareas/<id>/restaurar/` | Sacar de la papelera |
| POST | `/api/muro/` | Escribir en un muro |
| POST | `/api/notas/` | Nota del Buzón a una persona |

### 4.1 `GET /api/dimensiones/`

```json
{
  "prioridades": ["Normal", "Alta", "Baja"],
  "categorias": ["Desarrollo", "Documentación", "Incidencia", "Infraestructura", "Petición/Mejora"],
  "empresas":   [{"id": "emp-demo", "nombre": "Empresa Demo"}],
  "sistemas":   [{"id": "sis-erp", "nombre": "ERP", "empresa_id": "emp-demo"}],
  "iniciativas":[{"id": "ini-ia", "nombre": "Importación IA"}],
  "usuarios":   [{"id": 2, "usuario": "ana.lopez", "nombre": "Ana López"}],
  "proyectos":  [{"id": "migracion-correo", "nombre": "Migración de correo", "tipo": "kanban", "estado": "Activo",
                  "columnas": ["Pendiente", "En curso", "En espera", "Hecha"], "sprints": []}]
}
```

### 4.2 Crear una tarea — `POST /api/tareas/`

Mínimo: `proyecto_id` y `titulo`.

```json
{
  "proyecto_id": "docu-pbi",
  "titulo": "Revisar buzones con más de 50 GB",
  "descripcion": "Sale en ATENCIÓN en la auditoría del 14/10: 43 días sin refresco correcto.",
  "proximo_paso": "Mirar el error en auditoria_historial_*.csv",
  "status": "Pendiente",
  "prioridad": "Alta",
  "fecha_fin": "2026-10-20",
  "asignado": "ana.lopez",
  "subtareas": ["Abrir el historial de refrescos", "Decidir: arreglar o desprogramar"],
  "categoria": "Documentación", "sistema": "Correo", "empresa": "", "iniciativa": "", "sprint": "",
  "mantis_id": null
}
```

- `status` es el nombre de una columna del proyecto; si no existe, va a la primera columna no "hecha" y se avisa.
- `asignado`: un nombre de usuario o un id de `usuarios`.
- `subtareas`: una lista de textos, o de objetos `{"texto": "...", "hecho": false}`.
- Categoría, sistema, empresa, iniciativa y sprint se emparejan **por nombre**; lo que no coincide queda vacío y se avisa.
- `mantis_id` evita crear dos tareas del mismo Mantis (`409`).

Respuesta (`201`):

```json
{"ok": true, "id": "a1b2c3d4", "proyecto_id": "docu-pbi", "estado": "Pendiente",
 "efectos": ["tarea_creada", "aviso:marta", "muro"], "avisos": []}
```

### 4.3 Crear muchas — `POST /api/tareas/importar/`

```json
{"proyecto_id": "docu-pbi", "simular": true,
 "tareas": [{"titulo": "...", "subtareas": ["..."]}, {"titulo": "...", "asignado": "marta"}]}
```

- Admite los mismos campos por tarea que la creación de una sola. Hasta **500 tareas** por llamada.
- Es **tolerante fila a fila**: una tarea inválida se omite con aviso y no estropea las demás.
- Se omiten los títulos ya existentes en el proyecto y los `mantis_id` ya importados en cualquier proyecto.
- Cada persona asignada recibe su aviso, pero **en el muro sale un solo resumen** ("importó N tareas").
- Con `"simular": true` no crea nada: devuelve `se_crearian` (título, columna, asignado y nº de subtareas) y `avisos`.

Respuesta real: `{"ok": true, "creadas": 2, "avisos": [...], "efectos": ["tareas_creadas:2", "aviso:marta", "muro"]}`

### 4.4 Cambiar tareas

- **Editar** — `POST /api/tareas/<id>/` con solo los campos que cambian:
  - campos admitidos: `titulo`, `descripcion`, `proximo_paso`, `prioridad`, `status`, `fecha_inicio`, `fecha_fin`, `asignado` (`null` quita la asignación);
  - un cuerpo vacío devuelve `400`.
- **Mover** — `POST /api/tareas/<id>/mover/` con `{"status": "En curso"}`:
  - la columna tiene que existir (`400` si no);
  - llevarla a una columna "hecha" publica "completó" en el muro; sacarla de la primera columna publica "empezó a trabajar".
- **Asignar** — `POST /api/tareas/<id>/asignar/` con `{"usuario": "marta"}` o `{"usuario": null}`.
- **Eliminar / restaurar** — `POST /api/tareas/<id>/eliminar/` y `.../restaurar/`, sin cuerpo.
- **Cerrar con subtareas pendientes**: si el proyecto exige tener todas las subtareas hechas, cerrar la tarea con alguna pendiente devuelve `409`.
- **Permisos**: mover y eliminar siguen los permisos del dueño de la clave en ese espacio. Por ejemplo, un Lector no puede (`403`).

### 4.5 Muro — `POST /api/muro/`

```json
{"proyecto_id": "docu-pbi", "texto": "He revisado la auditoría de refrescos: 6 modelos vivos OK, 2 a revisar (tareas creadas)."}
```

- Se publica con `proyecto_id` (en el muro de ese proyecto, que es el de su espacio con la etiqueta del proyecto) o con `espacio_id` (en el muro general del espacio).
- Avisa en la campana a los demás miembros.
- Hace falta una clave con dueño que pueda escribir en ese espacio (Admin o Editor, o IT).

### 4.6 Buzón — `POST /api/notas/`

```json
{"para": "marta", "texto": "Te he dejado 3 tareas del análisis de Clave en Incidencias.",
 "vence_en": "2026-10-20", "aviso_cantidad": 1, "aviso_unidad": "dias"}
```

- Si `para` va vacío, la nota es para el dueño de la clave (un recordatorio personal).
- El recordatorio llega a la campana `aviso_cantidad` `horas`, `dias` o `semanas` antes de `vence_en` (a las 09:00).

### 4.7 Consultar — `GET /api/tareas/` y `GET /api/tareas/<id>/`

- **Filtros** (querystring): `proyecto_id`, `status`, `empresa_id`, `categoria`, `mantis_id`, `solo_mantis=1`, `incluir_borradas=1`, `actualizada_desde=AAAA-MM-DD`, `limit` (200 por defecto, 1000 como máximo) y `offset`.
- **Orden**: de la más reciente a la más antigua por `actualizada_en`.
- **Qué devuelve cada tarea**: todos sus campos, incluidos `asignado_a` (id), `asignado` (nombre de usuario) y `subtareas`.

---

## 5. Cómo convertir un análisis en buenas tareas

- **Una tarea = algo que alguien tiene que hacer.** No conviertas en tareas los hallazgos que no requieren acción: van en la descripción o en el mensaje del muro.
- **El título empieza por un verbo y es corto**: "Revisar…", "Pedir al proveedor…", "Documentar…". Los títulos se usan para no duplicar, así que conviene que sean concretos.
- **La descripción da el contexto**: qué se encontró, de dónde sale (fichero, consulta, nº de Mantis) y por qué importa. Que se entienda sin el análisis delante.
- **Próximo paso**: la siguiente acción concreta.
- **Subtareas**: los pasos de la tarea, cuando hay varios.
- **Prioridad `Alta`** solo si el análisis lo justifica (seguridad, producción parada, fecha cercana).
- **Asigna solo si la persona lo ha dicho.** Si no, deja la tarea sin asignar.
- **`mantis_id`** si la tarea sale de una incidencia de Mantis.
- **Al final, un mensaje en el muro** del proyecto con el resumen del análisis y cuántas tareas se crearon.

---

## 6. Errores

Todas las respuestas de error tienen la forma `{"ok": false, "error": "…"}`.

| Código | Cuándo |
|---|---|
| 400 | Falta un dato obligatorio, un JSON está mal formado o una columna no existe |
| 401 | Falta la clave o no es válida |
| 403 | La clave no llega a ese proyecto, o su dueño no tiene permiso, o la clave no tiene dueño para muro o notas |
| 404 | No existe el proyecto, la tarea o el usuario (o es de otro proyecto que la clave no ve) |
| 409 | Cerrar con subtareas pendientes, o un Mantis ya importado |

---

## 7. Ejemplo en Python

```python
import os, requests
from dotenv import load_dotenv

load_dotenv()
URL, H = os.environ["APP_TAREAS_API_URL"], {"X-API-Key": os.environ["APP_TAREAS_API_KEY"]}

print(requests.get(f"{URL}/", headers=H).json()["actor"])
dim = requests.get(f"{URL}/dimensiones/", headers=H).json()
proyecto = next(p for p in dim["proyectos"] if p["nombre"] == "Migración de correo")

tareas = [
    {"titulo": "Revisar buzones con más de 50 GB", "prioridad": "Alta",
     "descripcion": "43 días sin refresco correcto (auditoría 14/10).",
     "subtareas": ["Abrir el historial", "Decidir: arreglar o desprogramar"]},
]
plan = requests.post(f"{URL}/tareas/importar/", headers=H,
                     json={"proyecto_id": proyecto["id"], "tareas": tareas, "simular": True}).json()
print(plan["se_crearian"], plan["avisos"])

hecho = requests.post(f"{URL}/tareas/importar/", headers=H,
                      json={"proyecto_id": proyecto["id"], "tareas": tareas}).json()
print(hecho["creadas"], hecho["efectos"])

requests.post(f"{URL}/muro/", headers=H,
              json={"proyecto_id": proyecto["id"], "texto": f"Análisis de refrescos: {hecho['creadas']} tareas creadas."})
```

En PowerShell, lo mismo con `Invoke-RestMethod -Headers @{ "X-API-Key" = $env:APP_TAREAS_API_KEY } -ContentType "application/json; charset=utf-8"`.
