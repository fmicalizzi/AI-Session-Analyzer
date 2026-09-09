# Guía de Datos e Integración de pi (pi coding agent)

Esta guía documenta la estructura de datos que genera **pi** (agente de código de
[badlogic/pi-mono](https://github.com/badlogic/pi-mono), CLI `pi`) y el mecanismo usado por
**AI Session Analyzer v5.3** para parsear sus sesiones y adjudicarlas al proyecto Claude
correspondiente.

> El formato de logs de pi es **idéntico** al que Pencil usa en `~/.pencil/pi-sessions/`
> (Pencil embebe el agente pi): JSONL "pi" v3 con eventos encadenados por `id`/`parentId`.
> Lo que cambia es la ubicación y el descubrimiento: pi guarda una carpeta **por proyecto**.

---

## 1. Estructura de Directorios de pi (`~/.pi/`)

```
~/.pi/
└── agent/
    └── sessions/                          # sesiones del CLI, agrupadas por proyecto
        ├── --Users-foo-Downloads-proj--/  # cwd codificado con dobles guiones
        │   ├── {timestamp}_{uuid}.jsonl   # ej: 2026-09-09T03-45-03-295Z_01a08444-....jsonl
        │   └── ...
        └── --Users-francomicalizzi--/     # sesiones lanzadas desde $HOME
```

- El nombre de carpeta **codifica el cwd** reemplazando `/` por `-` y enmarcando con `--`.
  Es decodificable, pero **no se usa como fuente de verdad**: la primera línea de cada
  JSONL trae el `cwd` real (`type:"session"`). El parser lee ese header (regla 1 del
  matching, estilo Pencil).
- `--pi-dir` acepta tanto `~/.pi/` como `~/.pi/agent/sessions/` (se resuelve buscando
  `agent/sessions/`, `sessions/` o `*.jsonl` sueltos en la base).
- La carpeta ya es por-proyecto → el matching principal es casi siempre exacto.

---

## 2. `*.jsonl` (eventos)

Línea 1 = cabecera de sesión con el **cwd del proyecto**:

```json
{"type":"session","version":3,"id":"01a08444-...","timestamp":"2026-09-09T03:45:03.295Z","cwd":"/Users/.../AI-Session-Analyzer"}
```

Eventos relevantes:

| `type` | Contenido usado |
|--------|-----------------|
| `session` | `id`, `timestamp`, `cwd` (fuente de verdad del proyecto) |
| `model_change` | `provider`, `modelId` → modelo vigente hasta el próximo cambio (pi puede cambiar de modelo a mitad de sesión) |
| `thinking_level_change` | ignorable |
| `message` role=`user` | `content[]` con `text` (+ `timestamp`) |
| `message` role=`assistant` | `provider`, `model` **por mensaje**, `usage`, `content[]` con `thinking`, `toolCall` (`name`, `arguments`), `text` |
| `message` role=`toolResult` | `toolName`, `isError`, `content[]` → **NO** cuenta como respuesta del asistente; solo se escanea para extraer rutas absolutas |

Cada evento (incluso los `message`) trae `timestamp` ISO-8601 UTC de nivel superior y
encadenamiento `id`/`parentId` (thread de la conversación; el analyzer lo recorre lineal).

**`usage` del mensaje assistant** (fuente de tokens/costo):

```json
{"input": 6, "output": 1760, "cacheRead": 11059, "cacheWrite": 1022,
 "totalTokens": 13847,
 "cost": {"input": 9e-07, "output": 0.0008, "cacheRead": 0.0002,
          "cacheWrite": 0.0002, "total": 0.0012},
 "cacheWrite1h": 0}
```

- `reasoning` puede no existir (no todos los proveedores lo publican) → se acumula como 0.
- Como el modelo viene **por mensaje**, el uso se acumula **por modelo** (`model_usage`):
  los cambios a mitad de sesión quedan reflejados en el ranking.

**Bloques `toolCall`:** `arguments` es un dict según la tool:
`read`/`write`/`edit` usan `path`; `bash` usa `command` (contiene rutas absolutas dentro
del texto). Se extraen rutas de las claves conocidas **y** escaneando strings con límite
(`[:4000]`) con el patrón de clase compilado — nunca `re.findall` sobre dumps MB.

**Límites defensivos:** los textos de user/assistant se capen al parsear
(`_PI_TEXT_CAP = 12000` chars por bloque, con sufijo `[... N caracteres ...]`), por si una
sesión contiene payloads grandes.

---

## 3. Emparejamiento Q&A

Mensaje `user` con texto (tras limpiar marcadores de inyección compartidos con Pencil:
`The result of \`x\` tool call:`, `[Image: `, `<system-reminder>`, adjuntos `@{...}`) →
primeros textos `assistant` del turno (se concatenan los bloques `text`; turnos que solo
hacen tool calls se marcan "sin respuesta de texto"). Un `user` nuevo cierra el turno
anterior. `toolResult` no interrumpe ni cuenta como respuesta.

---

## 4. Algoritmo de Adjudicación de Proyecto (v5.3)

Input: set de `cwd`s de los mensajes Claude procesados (`_collect_claude_project_cwds`,
pool propio `self.pi_projects`).

1. **Regla `cwd`** — prefijo de segmentos con **contención real** entre el `cwd` del header
   y cada proyecto Claude (`_best_project_match`, `min_common=4`, empate ⇒ regla 2).
   Como las carpetas de pi son por-proyecto, esta regla resuelve la casi totalidad.
2. **Regla `paths`** — votación con rutas extraídas de `toolCall.arguments` (`path`,
   `filePath`, `file_path`, `file` y rutas dentro de `command`) y de `toolResult`: gana la
   puntuación más alta sin empate.
3. **Regla `tiempo`** — último recurso: la ventana `[start_time, end_time]` de la sesión pi
   (timestamps ISO de los eventos) se solapa con mensajes Claude; se toma el `cwd` más
   frecuente de la ventana.
4. Sin match ⇒ sección "Sin proyecto identificable" (auditable en el reporte).

Cada sesión reporta **qué regla** la adjudicó y el score de prefijo.

**Sin duplicación con Pencil:** `--pencil-dir` lee `~/.pencil/pi-sessions/` y `--pi-dir` lee
`~/.pi/agent/sessions/` — directorios disjuntos (sesiones de la app de diseño vs. del CLI).

---

## 5. Uso

```bash
python3 process_sessions.py <dir-sesiones-claude> -o reportes --pi-dir ~/.pi/agent/sessions/
```

Reportes generados:

- `18_pi_sesiones.md` — sesiones agrupadas por proyecto Claude, cronología y Q&A completo
  (prompt usuario + respuesta agente) con tokens/costo por sesión.
- `19_pi_modelos_uso.md` — ranking por modelo: requests, tokens, costo, $/turno y tasa de
  turnos con respuesta de texto.
- Sección "Consumo pi (coding agent)" dentro de `09_eficiencia_tokens.md` y resumen en
  `00_resumen_sesiones.md`.

## 6. Notas de rendimiento

- Parseo **streaming línea a línea** (`for line in f: json.loads(line)`): nunca
  `json.load()` del archivo completo.
- Cap de texto al parsear (12 KB por bloque) + truncado al render (8 KB user / 12 KB
  agente por turno).
- Patrones de extracción de rutas compilados a nivel de clase y escaneo limitado a 4 KB
  por string de argumento (regla de la Fase 3 de HOW_TO_ADD_A_PROVIDER.md).
- Sesiones típicas: KBs a pocos MB; no se observaron tool-results con blobs MB, pero el
  parser no los carga: de `toolResult` solo se extraen rutas con límite.
