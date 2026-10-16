# Manual de uso

Guía para las personas que usan la aplicación día a día. La configuración y la instalación están en [ADMINISTRACION.md](ADMINISTRACION.md).

## 1. Conceptos básicos

| Concepto | Qué es |
|---|---|
| **Espacio** | Un área de trabajo con sus proyectos y su gente. Cada persona tiene uno **personal** (solo suyo) y puede pertenecer a espacios **compartidos** (p. ej. "Equipo IT"). |
| **Proyecto** | Un conjunto de tareas con su tablero. Puede ser **Kanban** (flujo continuo, p. ej. Soporte) o **Scrum** (trabajo por sprints). |
| **Columna** | Cada etapa del tablero (Pendiente, En curso, En espera, Hecha…). Las columnas son propias de cada proyecto y se pueden renombrar. Las marcadas como "terminada" cuentan como trabajo cerrado. |
| **Tarea** | Lo que hay que hacer: título, descripción, próximo paso, prioridad, fechas, responsable, subtareas y etiquetas (categoría, sistema, empresa, iniciativa). |

### Roles en un espacio compartido

| Rol | Puede |
|---|---|
| **Admin** | Todo: gestionar miembros y permisos, editar o desactivar el espacio, crear y borrar proyectos. |
| **Editor** | Crear y trabajar tareas y proyectos. El Admin puede limitarle mover o borrar tareas **ajenas**, tocar columnas o apariencia, y gestionar documentos o wiki. Sobre sus propias tareas siempre puede. |
| **Lector** | Ver. Puede leer el muro, pero no escribir en él. |

Además existe el perfil **IT**, que no depende de los espacios:
- da acceso a **Configuración**;
- permite publicar **Avisos** en los muros;
- permite leer y escribir en todos los muros.

## 2. Portada ("mi día")

Al entrar ves de un vistazo:
- **Hoy**: tareas que vencen hoy, notas y pizarras del día, y reuniones (si tienes el calendario externo conectado).
- **Mi trabajo**: tus tareas pendientes, con las vencidas primero.
- **Actividad en mis muros**, **Buzón** y **Novedades** de la campana.
- **Proyectos por espacio**, con cuántas tareas pendientes y vencidas tiene cada uno.

## 3. Tableros y tareas

- **Crear una tarea**: botón *Nueva tarea* en el tablero, o escribe el título directamente en la columna (creación rápida).
- **Mover**: arrastra la tarjeta a otra columna o a otra posición. Mover una tarea al tablero de otra persona no la reasigna: para eso, cambia el responsable.
- **Subtareas**: una lista de pasos dentro de la tarea. Si el proyecto lo exige, no se puede cerrar una tarea con subtareas pendientes.
- **Anclar**: deja la tarea fija arriba de su columna.
- **Borrar**: la tarea queda marcada como borrada y se puede **Restaurar** desde el propio tablero.
- **Asignar a otra persona**: le llega un aviso a la campana. Nunca te avisa de lo que te asignas a ti mismo.

Pestañas de un proyecto:

| Pestaña | Para qué |
|---|---|
| Resumen | Estado general, hitos, descripción |
| Dashboard | Progreso, reparto por estado, categoría y prioridad, tareas vencidas, velocidad de sprints y actividad del último año |
| Tablero | El día a día |
| Backlog / Sprints | (Scrum) Planificar sprints, añadir tareas al sprint, cerrar el sprint |
| Gantt | Tareas con fechas en línea de tiempo |
| Documentos | Ficheros adjuntos del proyecto |
| Wiki | Documentación del proyecto, con páginas anidadas |
| Muro | La conversación de ese proyecto (si el proyecto está en un espacio) |

**Vistas globales** (cabecera): *Kanban* y *Scrum* juntan las tareas de todos los proyectos de ese tipo.

**Importar de Excel**: descarga la plantilla desde el propio tablero, rellénala y súbela. Las tareas cuyo título ya existe en el proyecto no se duplican.

**Duplicar proyecto**: crea un proyecto nuevo a partir de otro, eligiendo qué tareas copiar (solo pendientes, todas o ninguna), si mantener sus fechas y si copiar los hitos.

## 4. Calendario y Agenda

- El **Calendario** muestra las tareas por fecha límite y los días especiales (festivos, vacaciones, avisos, sede del día).
- Al pulsar un día se abre su **Agenda**: tareas que vencen ese día, notas y una pizarra del día. Lo que crees ahí aparece también en el calendario.
- **Reuniones**: si conectas tu calendario de Outlook (Configuración → Calendario externo, con un enlace ICS), cada reunión tiene su página con tareas, notas y pizarra propias.

Los festivos y los días no laborables se usan también para calcular el **SLA**: no cuentan como horas de trabajo.

## 5. Comunicación: Buzón, Muro y campana

Esta aplicación no tiene chat. La comunicación va por dos sitios distintos:

**Buzón**: notas de persona a persona (o a ti mismo como recordatorio).
- Puede llevar **fecha límite** y aviso previo ("avísame 2 días antes").
- Se puede **reenviar** y **convertir en tarea**.
- Solo quien la envía puede editarla o borrarla. Solo quien la recibe puede marcarla como leída.

**Muro**: la conversación de un espacio.
- Cada proyecto tiene su vista filtrada (pestaña *Muro*).
- Se publica solo lo importante: tarea creada, empezada, completada o reabierta; miembros que entran o salen.
- Un mensaje propio se puede borrar durante 30 segundos ("deshacer").
- Puedes **silenciar** un muro para no recibir avisos de él.
- **Avisos** (solo IT): mensajes destacados, con caducidad opcional, publicados en uno o varios muros a la vez.

**Campana** (arriba a la derecha): avisos de tareas asignadas, notas recibidas, recordatorios de notas, mensajes en tus muros y avisos generales. Se actualiza sola cada pocos segundos. Al abrir la lista se marcan como leídos.

## 6. Notas, Wiki y Pizarras

- **Notas**: post-its personales de colores, para apuntes rápidos.
- **Wiki** (en cada proyecto): páginas con formato (títulos, listas, tablas, código, avisos), anidadas como un árbol. Se puede importar un `.docx`.
- **Whiteboard**: pizarras para dibujar, con formas y texto. Se guardan y se pueden volver a editar o descargar como PNG.

## 7. Otras herramientas

- **Buscador** (cabecera): busca en tareas, proyectos y wiki a la vez.
- **Marcadores**: guarda como acceso directo personal cualquier pantalla (un tablero filtrado, un sprint…).
- **SLA** (IT): tiempos de resolución en horas laborables, por proyecto y categoría, exportable a CSV.
- **Entorno de pruebas** (menú de usuario): cambia a una base de datos de ensayo donde se puede probar sin miedo. Una franja de color avisa de que estás en pruebas. El cambio afecta a toda la aplicación, no solo a tu sesión.

## 8. Si algo no funciona

1. Recarga la página.
2. Comprueba que no estás en el **entorno de pruebas**: si la franja está visible, estás viendo otros datos.
3. Avisa a IT por el Buzón, indicando qué hacías, la hora y, si puedes, una captura de pantalla.
