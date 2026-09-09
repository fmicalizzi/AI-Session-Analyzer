# Guía de Datos e Integración de OpenCode

Esta guía documenta la estructura de datos que genera **OpenCode** (CLI de agentes
open-source, `opencode`) y el mecanismo usado por **AI Session Analyzer v5.1** para
parsear sus sesiones y adjudicarlas al proyecto Claude correspondiente.

---

## 1. Dónde vive todo (`~/.local/share/opencode/`)

```
~/.local/share/opencode/
├── opencode.db          # SQLite (WAL): ÚNICA fuente de verdad de sesiones
├── opencode.db-wal      # write-ahead log (puede estar activo mientras se lee)
├── auth.json / account.json / mcp-auth.json   # credenciales: NO leer
├── log/  snapshot/  storage/  tool-output/    # auxiliares, no se usan
```

El `.db` observado pesa ~1.9 GB (la mayor parte está en la tabla `event`, que
**no** se lee). Se abre en modo read-only (`file:...?mode=ro`) para no interferir
con la app en ejecución. Las versiones nuevas de OpenCode **ya no** usan
`storage/` con JSON por sesión: todo está normalizado en SQLite.

## 2. Esquema relevante (estructura `session → message → part`)

### `session` (547 filas típicas; columnas reales, no JSON)

| Columna | Uso |
|---------|-----|
| `id` | `ses_...` |
| `project_id` | FK a `project` (que tiene `worktree` = raíz del repo) |
| `parent_id` | no-null ⇒ sesión de **sub-agente** (hijo de un `task`) |
| `title`, `slug`, `agent` | encabezados (`agent`: build/plan/subagent…) |
| `directory` | **cwd de la sesión** → clave del matching (puede ser subcarpeta del worktree) |
| `model` | JSON `{"id","providerID","variant"}` del modelo vigente |
| `cost`, `tokens_input/output/reasoning/cache_read/cache_write` | **rollup exacto** (verificado = suma de mensajes assistant) |
| `time_created`, `time_updated` | epoch **milisegundos** |

### `message` (~20k filas) — `data` es JSON

- role `user`: `{role, time.created, agent, model:{providerID,modelID,variant}}` y
  `summary.diffs` que puede medir **decenas de MB** (diffs de git). ⇒ Nunca
  seleccionar `data` crudo de user: solo `json_extract` de campos específicos.
- role `assistant`: `{role, parentID, mode, agent, variant, path:{cwd,root}, cost,
  tokens:{total,input,output,reasoning,cache:{read,write}}, modelID, providerID,
  time:{created,completed}, finish}`; opcional `error` (p.ej.
  `MessageAbortedError`).

### `part` (~93k filas) — `data` JSON, ordenable por `(message_id, id)`

| `type` | Contenido usado |
|--------|-----------------|
| `text` | texto de user/assistant. `synthetic: true` ⇒ inyección de contexto (AGENTS.md, etc.) → **descartar** |
| `reasoning` | chain-of-thought (no se reporta, se ignora) |
| `tool` | `{tool, callID, state:{status, input, output}}`. `state.output` puede medir MB → **nunca extraer**; sí `input.filePath`, `input.path`, `input.command` (truncados) |
| `step-finish` | `{reason, tokens, cost}` por step |
| `patch` | `{files: [...]}` rutas absolutas modificadas → señal de paths para matching |
| `file` | adjuntos `file://` del mensaje user |
| `step-start`, `compaction` | ignorar |

Índices aprovechados: `message(session_id,time_created,id)`,
`part(message_id,id)`, `part(session_id)`.

## 3. Estrategia de parseo (performance)

- **Nunca** `SELECT data` completo. Todo se extrae server-side con
  `json_extract(...)` + `substr(...,1,N)` para los campos de texto:
  fila user más grande observada = 31 MB, parte más grande = 14 MB.
- Tres consultas secuenciales (sessions, messages, parts) indexadas por
  `session_id`; agrupación en Python. Extract completo del DB real: **< 2 s**.
- Solo se retienen: prompts de usuario (cap 8 KB), respuestas assistant (cap 12 KB),
  nombres de tool + rutas de input (cap), usage por modelo.

## 4. Algoritmo de Adjudicación de Proyecto (modo "paralelo con adjudicación")

Reutiliza `_collect_claude_project_cwds()` / `_best_project_match()` de Pencil:

1. **Regla `cwd`** — `session.directory` contra los cwd Claude: prefijo común de
   segmentos con **contención real** (el cwd debe estar en la raíz del proyecto o por
   debajo; mínimo 4 segmentos). `project.worktree` solo refuerza cuando `directory`
   viene vacío. Empate o sin match ⇒ regla 2.
2. **Regla `paths`** — votación sobre rutas extraídas de `patch.files`,
   `tool.state.input.filePath/path` y adjuntos `file` (mismo criterio de prefijo).
3. **Regla `tiempo`** — solape `[time_created, time_updated]` de la sesión con
   timestamps de mensajes Claude; gana el cwd más frecuente en la ventana.
4. Sin match ⇒ sección "Sin proyecto identificable".

Cada sesión reporta **qué regla** la adjudicó. Las sesiones con `parent_id`
(sub-agentes) se listan como tal bajo su proyecto y **no** generan Q&A propio
(su "user" es un prompt de tarea generado por el padre).

## 5. Uso

```bash
python3 process_sessions.py <dir-sesiones-claude> -o reportes --opencode-dir ~/.local/share/opencode/
```

Reportes generados:

- `14_opencode_sesiones.md` — sesiones por proyecto Claude (cronología, títulos,
  agente, tokens/costo, regla de matching), Q&A de sesiones raíz.
- `15_opencode_modelos_uso.md` — ranking por modelo (provider+modelID): requests,
  tokens, costo, tasa de turnos con respuesta de texto, distribución de tools.
- Sección "Consumo OpenCode" dentro de `09_eficiencia_tokens.md`.

## 6. Notas y trampas

- `event`/`event_sequence` (~1.2 GB de JSON) son el bus interno de OpenCode:
  ignorar por completo.
- El reloj es **milisegundos**; Claude usa ISO-8601 — convertir al comparar.
- Tabla `project` incluye una fila `global` con `worktree='/'`: descartarla.
- `opencode.db` puede estar bloqueado si falta permiso de lectura: el loader
  debe degradar a "fuente no disponible" sin romper los demás reportes.
- Herramienta `invalid` en parts `tool`: errores de tool-call del modelo — contar
  en estadísticas de tools.
