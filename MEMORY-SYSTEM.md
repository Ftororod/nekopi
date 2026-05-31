# Kit: memoria viva por archivos (plantilla generica)

Sistema portable para que cualquier instancia de Claude Code mantenga memoria
persistente del proyecto en archivos versionados, sin depender de lo que el
modelo "recuerde". Copia este kit a cualquier proyecto nuevo.

---

## 1. Que problema resuelve

El modelo no recuerda nada entre sesiones. Su unica memoria es el contexto de
la conversacion actual; al cerrarse, se pierde. La memoria viva por archivos
mueve los hechos importantes a archivos versionados que el modelo LEE al
arrancar y ESCRIBE durante el trabajo. El conocimiento vive en el repo, no en
el modelo. Cualquier code, en cualquier maquina, en cualquier sesion, arranca
con el mismo estado.

Tres piezas, todas necesarias:

1. Un directorio `memory/` con **un hecho por archivo** (markdown + frontmatter).
2. Un indice `MEMORY.md` con **una linea por hecho**. Es lo que el modelo carga al arrancar.
3. Un **ritual en `CLAUDE.md`** que obliga al modelo a leer el indice al arrancar y a mantener los archivos. Sin el ritual los archivos existen pero el modelo no los usa.

La pieza 3 es la critica. Tener archivos no sirve si el modelo no tiene
instruccion explicita de leerlos y mantenerlos.

---

## 2. Donde vive la memoria: dos opciones

| | Repo-committed (recomendada) | Nativa del harness |
|---|---|---|
| Ubicacion | `.claude/memory/` dentro del repo | `~/.claude/projects/<slug>/memory/` |
| Versionada en git | Si | No (vive en el home de la maquina) |
| Compartida entre maquinas / equipo | Si | No, es local a esa maquina |
| Se inyecta sola al contexto | No, requiere ritual en CLAUDE.md | Si, el harness inyecta `MEMORY.md` solo |
| Portable a otro proyecto | Si, copias la carpeta | No directamente |

Recomendacion: **repo-committed** (`.claude/memory/`). Es portable, versionada y
compartida, que es justo lo que buscas para "no depender del modelo" y poder
replicarla en otro code. El unico costo es agregar el ritual de lectura al
`CLAUDE.md` (incluido abajo, listo para pegar).

La opcion nativa se auto-inyecta sin ritual, pero queda atada al home de una
maquina y no viaja con el repo. Si la prefieres, el formato de archivos es
identico; solo cambia la ruta.

---

## 3. Estructura de archivos

```
<repo>/
  CLAUDE.md                  <- instrucciones del proyecto + ritual de memoria
  .claude/
    memory/
      MEMORY.md              <- indice: una linea por hecho (esto se lee al arrancar)
      user_<slug>.md         <- un hecho
      feedback_<slug>.md     <- un hecho
      project_<slug>.md      <- un hecho
      reference_<slug>.md    <- un hecho
```

Convencion de nombres: `<tipo>_<slug-kebab-case>.md`. El prefijo de tipo es
opcional pero ayuda a escanear la carpeta. El `slug` debe coincidir con el campo
`name:` del frontmatter (para que los enlaces `[[name]]` resuelvan).

---

## 4. Anatomia de un archivo de memoria

Un archivo = un hecho. Frontmatter + cuerpo.

```markdown
---
name: <slug-kebab-case>
description: <resumen de una linea — se usa para decidir relevancia al recordar>
metadata:
  type: user | feedback | project | reference
---

<el hecho>
```

### Los 4 tipos

| type | Que guarda | Como deriva de no-obvio |
|---|---|---|
| `user` | Quien es el usuario: rol, expertise, preferencias de trabajo. | Lo que no se deduce del codigo. |
| `feedback` | Guia que el usuario dio sobre como debes trabajar: correcciones y enfoques confirmados. | Incluir **siempre** el porque. |
| `project` | Trabajo en curso, metas, restricciones que NO se derivan del codigo ni del git. | Convertir fechas relativas a absolutas. |
| `reference` | Punteros a recursos externos: URLs, dashboards, tickets. | El puntero, no el contenido. |

### Cuerpo segun el tipo

- `user` y `reference`: el hecho directo, una o dos lineas.
- `feedback` y `project`: el hecho, seguido de dos lineas:
  - `**Why:**` por que importa (sin esto la memoria es una regla sin contexto y se aplica mal).
  - `**How to apply:**` que hacer concretamente la proxima vez.

### Enlaces entre memorias

En el cuerpo, enlaza memorias relacionadas con `[[name]]`, donde `name` es el
slug del campo `name:` de la otra memoria. Enlaza con generosidad: un `[[name]]`
que aun no existe como archivo no es un error, marca algo que vale la pena
escribir despues.

---

## 5. El indice MEMORY.md

Es el archivo que se carga al arrancar cada sesion. Una linea por memoria, sin
frontmatter. Nunca pongas contenido de memoria aqui, solo el puntero.

```markdown
# Memoria del proyecto

- [Titulo corto](feedback_<slug>.md) — gancho de una linea para decidir si abrir el archivo.
- [Titulo corto](project_<slug>.md) — gancho de una linea.
- [Titulo corto](user_<slug>.md) — gancho de una linea.
```

El "gancho" debe permitir al modelo decidir, sin abrir el archivo, si esa
memoria es relevante a la tarea actual.

---

## 6. Bloque para pegar en el CLAUDE.md del otro proyecto

Esta es la pieza que hace que el modelo USE la memoria. Pegala tal cual en el
`CLAUDE.md` del proyecto destino (ajusta la ruta si usas la opcion nativa).

```markdown
## Memoria viva del proyecto

Tienes memoria persistente en archivos bajo `.claude/memory/`. El conocimiento
del proyecto vive ahi, no en tu contexto. Cada memoria es UN archivo con UN
hecho, mas frontmatter:

    ---
    name: <slug-kebab-case>
    description: <resumen de una linea — se usa para decidir relevancia al recordar>
    metadata:
      type: user | feedback | project | reference
    ---

    <el hecho; para feedback/project, sigue con lineas **Why:** y **How to apply:**.
     Enlaza memorias relacionadas con [[su-name]].>

### Al arrancar (obligatorio)

1. Lee `.claude/memory/MEMORY.md`. Es el indice, una linea por hecho.
2. Para cada hecho cuyo gancho parezca relevante a la tarea, abre su archivo.
3. Una memoria refleja lo que era cierto cuando se escribio. Si nombra un
   archivo, funcion o flag, verifica que aun exista antes de recomendarlo.

### Cuando guardar un hecho

Guarda cuando aparezca algo de estos tipos:
- `user`: quien es el usuario (rol, expertise, preferencias).
- `feedback`: guia sobre como trabajar (correcciones y enfoques confirmados); incluye el porque.
- `project`: trabajo en curso, metas, restricciones no derivables del codigo/git; fechas relativas a absolutas.
- `reference`: punteros a recursos externos (URLs, dashboards, tickets).

Procedimiento:
1. Escribe el archivo en `.claude/memory/<tipo>_<slug>.md` con su frontmatter.
2. Agrega una linea-puntero en `MEMORY.md`: `- [Titulo](archivo.md) — gancho`.

### Disciplina (no negociable)

- Antes de guardar, busca un archivo que ya cubra el hecho; ACTUALIZA ese, no dupliques.
- Borra memorias que resulten falsas.
- No guardes lo que el repo ya registra (estructura de codigo, fixes pasados, historia de git, el propio CLAUDE.md).
- No guardes lo que solo importa a la conversacion actual.
- Si te piden recordar algo que el repo ya registra, pregunta que fue lo no-obvio y guarda ESO.
- Convierte fechas relativas a absolutas (hoy es <fecha>).
```

---

## 7. Reglas de disciplina (las mismas, expandidas)

Por que cada regla, para que no se erosionen con el tiempo:

- **Un hecho por archivo.** Archivos atomicos se actualizan y se borran sin tocar lo demas. Un archivo con cinco hechos se vuelve intocable.
- **Update sobre create.** La duplicacion silenciosa es el modo de falla numero uno: dos archivos con la misma regla en versiones distintas, y nadie sabe cual gana. Antes de crear, busca.
- **Borra lo falso.** Una memoria equivocada es peor que ninguna: el modelo la trata como ground truth. Si se invalida, eliminala (archivo + linea en el indice).
- **No dupliques el repo.** Si esta en el codigo, en el git log o en el CLAUDE.md, el modelo ya lo ve. La memoria es para lo que NO esta escrito en ningun lado: el porque de una decision, una preferencia del usuario, una restriccion externa.
- **No guardes ruido de sesion.** "Estamos depurando el bug X ahora mismo" no es memoria, es contexto. Memoria es lo que seguira siendo cierto la proxima sesion.
- **Fechas absolutas.** "La semana pasada" no significa nada dentro de tres meses. Escribe la fecha real.
- **Verifica antes de recomendar.** Una memoria es una foto del pasado. Si menciona un archivo/funcion/flag, confirma que sigue existiendo antes de actuar sobre el.
- **Enlaza.** `[[name]]` conecta hechos relacionados y revela cuales faltan por escribir.

---

## 8. Ejemplos (genericos, con placeholders)

`.claude/memory/MEMORY.md`:

```markdown
# Memoria del proyecto

- [Preferencia de output](feedback_output_conciso.md) — respuesta primero, razonamiento despues.
- [Rol del usuario](user_rol.md) — es el tech lead, decide arquitectura, no quiere micro-explicaciones.
- [Meta del trimestre](project_meta_q3.md) — migrar auth a OIDC antes del 2026-09-30.
- [Dashboard de metricas](reference_dashboard.md) — Grafana con los SLOs de produccion.
```

`.claude/memory/feedback_output_conciso.md`:

```markdown
---
name: feedback_output_conciso
description: El usuario quiere respuesta en la primera linea, razonamiento despues.
metadata:
  type: feedback
---

El usuario pide la conclusion o el resultado en la primera linea; el razonamiento
va despues, nunca antes. Cero preambulo y cero postambulo.

**Why:** pega el output en otra herramienta y solo necesita el hecho, no la prosa.
**How to apply:** abre cada respuesta con el cambio o la respuesta directa; si hace
falta explicar, ponlo en una seccion posterior. Ver tambien [[user_rol]].
```

`.claude/memory/project_meta_q3.md`:

```markdown
---
name: project_meta_q3
description: Migracion de auth a OIDC, deadline 2026-09-30.
metadata:
  type: project
---

El proyecto migra el login de sesiones propias a OIDC. Deadline duro 2026-09-30
por requisito de cumplimiento.

**Why:** auditoria externa exige SSO federado; no es negociable la fecha.
**How to apply:** al tocar codigo de auth, asume OIDC como destino; no inviertas
en el flujo de sesiones viejo salvo para mantenerlo vivo hasta el cutover.
```

---

## 9. Bootstrap en un proyecto nuevo (pasos)

1. `mkdir -p .claude/memory` en el repo destino.
2. Crea `.claude/memory/MEMORY.md` con un encabezado y la lista vacia.
3. Pega el bloque de la seccion 6 en el `CLAUDE.md` del proyecto (creandolo si no existe).
4. Commit: la carpeta y el indice entran al repo. Desde aqui la memoria viaja con el codigo.
5. En la primera sesion, el modelo lee `MEMORY.md` (vacio) y empieza a poblarlo conforme aparecen hechos.

Eso es todo. La memoria crece sola con el uso, siempre que el ritual de la
seccion 6 este en el CLAUDE.md.
