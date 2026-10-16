# Normativa de uso

> **Plantilla.** Cada empresa debe revisarla y adaptarla antes de publicarla. Hay que fijar los responsables, los plazos y, sobre todo, ajustarla a su política de seguridad y de protección de datos. Los puntos marcados con ⟨…⟩ se rellenan en esa adaptación.

| | |
|---|---|
| Empresa | ⟨nombre⟩ |
| Responsable de la aplicación | ⟨persona / departamento de IT⟩ |
| Versión y fecha | ⟨1.0 — fecha de aprobación⟩ |

## 1. Objeto y alcance

La aplicación es la herramienta oficial para gestionar el trabajo de ⟨departamentos⟩: peticiones, incidencias, proyectos y su documentación. Esta normativa se aplica a todas las personas con usuario en ella.

## 2. Acceso y cuentas

1. Cada cuenta es **personal e intransferible**. No se comparten usuarios ni contraseñas.
2. Las altas, bajas y cambios de perfil los tramita **IT** a petición del responsable de cada área.
3. Cuando alguien deja la empresa, su usuario se **desactiva**, no se borra. Así se conserva el historial de lo que hizo.
4. El perfil **IT** da acceso a la configuración de toda la aplicación y se limita al personal técnico que la administra.
5. Contraseñas (modo de login local): mínimo ⟨12⟩ caracteres, sin reutilizar las de otros servicios. Con SSO, se aplica la política corporativa.

## 3. Qué va en cada sitio

| Necesidad | Dónde | Dónde **no** |
|---|---|---|
| Algo que hay que hacer, con responsable y plazo | **Tarea** en el proyecto que corresponda | Un mensaje del muro o una nota suelta |
| Pedir algo a una persona concreta | **Buzón** (convertible en tarea) | El muro |
| Informar al equipo de un espacio | **Muro** | El Buzón uno por uno |
| Aviso general (corte de servicio, cambio importante) | **Aviso** en los muros (IT) | — |
| Documentación de un proyecto o sistema | **Wiki** del proyecto | Notas personales |
| Apuntes personales | **Notas** | La wiki |

## 4. Buenas prácticas con las tareas

1. **El título empieza por un verbo y es concreto**: "Revisar copias del servidor de ficheros", no "copias".
2. **Toda tarea tiene responsable.** Las que no tienen, se revisan en la reunión de seguimiento ⟨semanal⟩.
3. **Fecha límite realista.** Si cambia, se actualiza: una tarea vencida que en realidad sigue en plazo distorsiona el SLA.
4. **El "próximo paso"** dice qué es lo siguiente que hay que hacer y quién lo hace.
5. **Cerrar** una tarea es moverla a la columna de terminadas. No se borran tareas hechas: borrar se reserva para errores y duplicados.
6. Las categorías, sistemas, empresas e iniciativas se eligen de los catálogos. Si falta uno, se pide a IT; no se escribe en el título.

## 5. Información sensible

1. **Prohibido** escribir contraseñas, claves, tokens o datos bancarios en tareas, notas, wiki, Buzón o muro.
2. Las credenciales técnicas solo se guardan en las **credenciales cifradas de Nexus** (si el módulo está activo), protegidas con contraseña. En su defecto, en ⟨gestor de contraseñas corporativo⟩.
3. **Datos personales** (de clientes, empleados, proveedores): solo los imprescindibles para resolver la tarea. Si basta con una referencia (número de pedido o de ticket), se usa la referencia. Lo que la app guarda se rige por ⟨política de protección de datos de la empresa⟩.
4. Los adjuntos (Documentos de proyecto, wiki) siguen las mismas reglas.

## 6. Integraciones y API

1. Las claves de API se crean en Configuración → API **a nombre de una persona**. La API actúa con los permisos de esa persona, y lo que hace queda firmado "(vía API: …)".
2. Una clave por uso: un script o agente, una clave. Si se filtra o deja de usarse, se **revoca** de inmediato.
3. Los conectores de entrada los configura solo IT. Sus tokens se guardan cifrados y deben tener **permisos de solo lectura** en el sistema de origen.
4. Un agente de IA que use la API sigue esta misma normativa. Su responsable es el dueño de la clave.

## 7. Entorno de pruebas

1. Para probar se usa el **entorno de pruebas** (menú de usuario), nunca datos reales.
2. El cambio de entorno afecta a **toda la aplicación** y a todas las personas, no solo a una sesión. Se usa en momentos acordados y se vuelve al entorno real al terminar.

## 8. Copias de seguridad y conservación

1. IT hace una copia de la base de datos ⟨diaria⟩ y la conserva ⟨30 días⟩, en un sitio distinto del servidor de la app.
2. La restauración se prueba al menos ⟨cada trimestre⟩.
3. Los proyectos terminados se **archivan** (estado), no se eliminan.
4. Los registros técnicos (accesos, cambios, errores) se conservan ⟨90 días⟩.

## 9. Incidencias con la propia aplicación

Se comunican a IT por el Buzón o por ⟨canal habitual⟩. Hay que indicar qué se estaba haciendo, la hora, y si se estaba en el entorno de pruebas.

## 10. Incumplimiento

El uso contrario a esta normativa puede suponer la retirada del acceso. Se aplica además el ⟨reglamento interno / política de uso de sistemas⟩ de la empresa.
