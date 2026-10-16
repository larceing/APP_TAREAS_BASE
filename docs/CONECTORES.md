# Conectores de entrada

Un **conector** trae elementos de otro sistema y los convierte en **tareas** de un proyecto. Ejemplos de elementos: tickets de un servicio de soporte, incidencias de MantisBT, pedidos atascados que devuelve un script propio…

Cada elemento se importa **una sola vez**, aunque se sincronice mil veces.

Es un módulo opcional: `MODULO_CONECTORES=1` en `app_fastapi/.env`. Se gestiona en **Configuración → Conectores** (solo IT).

## Tipos incluidos

| Tipo | Para qué |
|---|---|
| **API REST genérica** | Cualquier dirección que devuelva una lista en JSON. Se configura sin programar: dónde está la lista y qué campo es el id, el título, la descripción, el enlace, la prioridad, la fecha límite y el responsable. |
| **MantisBT** | Incidencias abiertas de un proyecto de Mantis, por su API REST. Admite varios conectores (uno por instancia o proyecto), cada uno con su token. Es independiente del módulo Mantis completo. |

## Qué pasa al sincronizar

1. Se traen los elementos del origen.
2. Se descartan los ya importados por ese conector (tabla `conector_elementos`). Si se borra una tarea importada, **no** vuelve a crearse.
3. Por cada elemento nuevo se crea una tarea con la **misma lógica que una tarea creada a mano** (`acciones.crear_tarea`):
   - en el **proyecto destino**, en la **columna inicial** elegida (vacía = la primera del tablero);
   - prioridad traducida a Alta/Normal/Baja (`urgent`, `high`, `alta` → Alta; `low`, `baja` → Baja);
   - responsable: el usuario de la app cuyo usuario o email coincida con el del origen; si no hay ninguno, el "Asignar a" del conector. La persona asignada recibe el aviso en la campana;
   - la descripción termina con `Origen: <enlace>`.
4. En el muro del proyecto se publica **un único** resumen ("Conector · X importó 5 tareas").
5. El resultado queda en el propio conector: "3 tarea(s) nueva(s), 12 ya importada(s)", o el error del origen.

**Cuándo se sincroniza:**
- **A mano**, con el botón *Sincronizar ahora*.
- **Automáticamente**, cada *N minutos* (0 = solo a mano). Lo hace un hilo de la app que revisa cada minuto qué conectores toca lanzar.

La sincronización automática **solo corre con el entorno real activo**. En el de pruebas se pausa, para no llenar la base de pruebas sin querer.

## Seguridad

- Los campos de tipo *secreto* (tokens, cabeceras de autenticación) se guardan **cifrados con AES-GCM**, con la clave `CONECTORES_CLAVE` del `.env` (o `SESSION_SECRET_KEY` si está vacía).
- Si esa clave cambia, los tokens guardados no se pueden descifrar: el conector lo indica y hay que volver a escribirlos.
- En pantalla, un secreto guardado nunca se muestra. Si se deja el campo vacío al editar, se conserva.
- Al sistema de origen se le pide un usuario de **solo lectura**: el conector solo lee.

## Ejemplo: API REST genérica

Respuesta del origen:

```json
{ "data": { "tickets": [
  { "id": 4711, "subject": "No imprime", "body": "...", "priority": "high",
    "due": "2026-11-05T12:00:00Z", "agent": { "email": "ana.lopez@empresa.com" },
    "links": { "web": "https://soporte.empresa.com/t/4711" } }
] } }
```

| Campo del conector | Valor |
|---|---|
| URL | `https://soporte.empresa.com/api/tickets?estado=abierto` |
| Cabecera / valor | `Authorization` / `Bearer …` |
| Dónde está la lista | `data.tickets` |
| Campo id / título / descripción | `id` / `subject` / `body` |
| Campo enlace | `links.web` |
| Campo prioridad / fecha / asignado | `priority` / `due` / `agent.email` |

## Añadir un tipo nuevo (desarrollo)

Un tipo es un único fichero en `app_fastapi/conectores/`, con una subclase de `Conector` que solo sabe **traer**:

```python
# app_fastapi/conectores/glpi.py
import requests
from .base import Campo, Conector, ConectorError, Elemento

class Glpi(Conector):
    tipo = "glpi"
    nombre = "GLPI"
    descripcion = "Tickets abiertos de GLPI."
    campos = [
        Campo("url", "URL de GLPI", "url", True),
        Campo("app_token", "App-Token", "secreto", True),
        Campo("user_token", "User token", "secreto", True),
    ]

    def traer(self, config: dict) -> list[Elemento]:
        self.validar(config)
        ...  # pedir la lista; ante un fallo esperable, raise ConectorError("mensaje legible")
        return [Elemento(id_externo=str(t["id"]), titulo=t["name"], descripcion=t["content"],
                         url=f"{config['url']}/front/ticket.form.php?id={t['id']}")]
```

Y una línea en `app_fastapi/conectores/__init__.py`:

```python
TIPOS = {c.tipo: c() for c in (RestGenerico, Mantis, Glpi)}
```

La pantalla de Configuración se dibuja sola a partir de `campos`, y el cifrado de los secretos, la deduplicación, la creación de tareas, los avisos y la programación los pone el motor (`conectores/motor.py`). Para los tests, hay que copiar el patrón de `ConectoresPurosTests` en `app_fastapi/tests.py`, con la red mockeada.

## Tablas

```
conectores          id · nombre · tipo · config (JSON; secretos cifrados) · proyecto_id · estado_inicial
                    · asignar_a · activo · intervalo_min · ultima_sync · ultimo_resultado · ultimo_ok
conector_elementos  (conector_id, id_externo) PK · tarea_id · creado_en
```
