# Nexus — plan de acción para ponerlo en marcha

**Nexus** es el buscador documental de la aplicación. Su objetivo es que cualquiera del equipo encuentre en un solo sitio lo que hay sobre un sistema:
- su **ficha** (qué es, quién lo lleva, tecnologías);
- sus **documentos**, en la carpeta de red donde ya están;
- lo **relacionado** (proyectos, pizarras, otras fichas);
- sus **credenciales** técnicas, cifradas.

Este plan sirve para arrancarlo en una empresa nueva. El modelo de datos está en [NEXUS_ESTRUCTURA_DE_GRAFOS.md](NEXUS_ESTRUCTURA_DE_GRAFOS.md).

> **Regla de oro:** Nexus no sustituye a la carpeta de red ni a la wiki: las **enlaza**. Los documentos siguen donde están, y Nexus guarda su ruta y su texto para poder buscarlos.

---

## Fase 0 — Decidir (½ día, responsable de IT)

| Decisión | Pregunta | Recomendación |
|---|---|---|
| Alcance | ¿Qué carpetas se indexan? | Empezar por **una**: la documentación de IT. Ampliar cuando funcione. |
| Acceso | ¿Quién busca? | Configuración → Nexus: *Solo IT* al principio, *Todos* cuando el catálogo esté curado. Las credenciales y la búsqueda técnica son siempre solo de IT. |
| Catálogo | ¿Qué es una "ficha"? | Una por **sistema o servicio** (ERP, correo, VPN, copias…), no una por documento. |
| Responsables | ¿Quién mantiene cada ficha? | El responsable del sistema. Se apunta en la propia ficha. |

## Fase 1 — Activar e indexar (1 día)

1. `MODULO_NEXUS=1` en `app_fastapi/.env` y reiniciar.
2. La app tiene que poder **leer** la carpeta:
   - Windows: el usuario del servicio necesita permiso de lectura en la ruta UNC.
   - Docker: hay que montar la carpeta en el contenedor (`volumes: - /mnt/docs:/mnt/docs:ro`) e indexar con esa ruta.
3. Indexar:
   ```bash
   python scripts/nexus_indexar.py "\\servidor\documentacion" --tecnico-auto
   ```
   Extrae el texto de txt/md/csv/código, docx, pdf y xlsx. Lo de más de 30 MB se indexa sin texto.
4. Comprobar en la pestaña Nexus que la búsqueda encuentra documentos por su **contenido**, no solo por el nombre.
5. **Reindexar periódicamente** (los cambios en la carpeta no se detectan solos):
   - Windows: Programador de tareas, diario de madrugada.
   - Linux: `cron`.
   ```bash
   python scripts/nexus_indexar.py "\\servidor\documentacion" --tecnico-auto --limpiar
   ```

## Fase 2 — Fichas (1–2 semanas, en paralelo con el trabajo normal)

1. Crear en la **Wiki** de un proyecto de documentación (p. ej. "Sistemas") una página por sistema, con esta estructura:
   - qué es, para qué se usa y quién es su responsable;
   - cómo pedir algo sobre él;
   - un título **"Info para desarrolladores"** y, debajo, los servidores, puertos, bases de datos y dependencias. Nexus enseña esta parte aparte.
2. Convertir cada página en ficha:
   ```bash
   python scripts/nexus_fichas.py paginas
   python scripts/nexus_fichas.py ficha <pagina_id> --alias "ERP, Gestión" --codigo SIS-01 \
          --tecnologias "SQL Server, IIS" --estado activo --rol negocio
   ```
3. Enlazar los documentos de cada sistema:
   ```bash
   python scripts/nexus_fichas.py enlazar <pagina_id> --carpeta "documentacion/ERP"
   ```
   Así un archivo técnico enlazado deja de ser "sin curar" y entra en la búsqueda normal.

## Fase 3 — Relaciones (continuo)

Relacionar cada ficha con su sistema del catálogo, con los proyectos que le afectan y con otras fichas de las que depende:

```bash
python scripts/nexus_fichas.py relacionar wiki_pagina:<id> sistema:<sis-id>
python scripts/nexus_fichas.py relacionar wiki_pagina:<id> proyecto:<proyecto-id>
```

Criterio: se relaciona lo que alguien que busca A **querría ver** junto a A. No se relaciona todo con todo: los grupos crecen y no se separan solos (ver limitaciones en el documento de grafos).

## Fase 4 — Credenciales (cuando haya fichas)

Las credenciales técnicas (cuentas de servicio, accesos a consolas) se guardan **dentro de la ficha** del sistema, cifradas, con una contraseña de desbloqueo que conoce el equipo de IT y que **no se guarda** en ningún sitio de la app.
- Si se pierde esa contraseña, esas credenciales no se pueden recuperar.
- Hay que acordar dónde se custodia: ⟨gestor de contraseñas / sobre en caja fuerte⟩.

## Fase 5 — Abrir a todos y medir (a partir del mes 1)

1. Configuración → Nexus → *Cualquiera con sesión*.
2. Una vez al mes, revisar `nexus_busquedas_log`: las búsquedas **sin resultados** dicen qué falta documentar.
   ```sql
   SELECT termino, COUNT(*) veces FROM nexus_busquedas_log
   WHERE resultados = 0 AND creado_en > NOW() - INTERVAL 30 DAY
   GROUP BY termino ORDER BY veces DESC LIMIT 20;
   ```
3. Rellenar los **temas curados** (`TOPICS` en `app_fastapi/nexus/search.py`) con las palabras que más se buscan.

---

## Desarrollo pendiente (para que Nexus no dependa de scripts)

| # | Mejora | Por qué | Esfuerzo |
|---|---|---|---|
| 1 | **Pantalla de relaciones** en cada entidad: "Relacionar con…" y la lista de lo relacionado | Hoy solo se relaciona con `nexus_fichas.py` | Medio |
| 2 | **Convertir en ficha** desde la propia página de wiki (campos alias, código, tecnologías…) | Ídem | Bajo |
| 3 | **Enlazar documentos** a la ficha desde el resultado de búsqueda ("esto es de…") | Ídem | Bajo |
| 4 | **Reindexado programado** desde la app (carpetas e intervalo en Configuración, en el hilo de servicios) | Quitar la tarea programada externa | Medio |
| 5 | **Separar grupos** al borrar un nodo puente (recalcular componentes conexas) | Limitación del Union-Find | Medio |
| 6 | **Tipos de relación** ("depende de", "documenta a") | Hoy todas las aristas son iguales | Alto (cambio de modelo) |
| 7 | **Temas curados en la base de datos**, editables en Configuración | Hoy están en el código | Bajo |

Orden recomendado: 2 → 1 → 3 → 4. Con las tres primeras, la curación del catálogo pasa a hacerse desde la web.

## Riesgos

| Riesgo | Mitigación |
|---|---|
| Indexar carpetas con datos personales o confidenciales | Decidir el alcance en la Fase 0. Excluir esas carpetas. Acceso solo IT hasta revisar. |
| El índice se queda desactualizado | Reindexado programado con `--limpiar` (Fase 1.5). |
| Pérdida de la contraseña de credenciales | Custodia acordada (Fase 4). |
| Fichas que nadie mantiene | Un responsable por ficha, y revisión anual en el `estado` de la ficha. |
