# Guía de Datos e Integración de Antigravity CLI (Google, `agy`)

Esta guía documenta la estructura de datos que genera **Antigravity CLI**
(`~/.gemini/antigravity-cli/`) y el mecanismo usado por **AI Session Analyzer v5.2**
para parsear sus sesiones y adjudicarlas al proyecto Claude correspondiente.

---

## 1. Dónde vive todo (`~/.gemini/antigravity-cli/`)

```
~/.gemini/antigravity-cli/
├── conversations/            # UNA base SQLite POR conversación (la fuente de verdad)
│   ├── {uuid}.db             # 49 KB – 7 MB; una fila por step de la trajectory
│   └── {uuid}.pb             # formato antiguo (jun 2026): protobuf suelto → IGNORAR
├── cache/
│   ├── conversation_metadata.json  # {ID: {summary:{Preview, NumSteps, UpdatedAt,
│   │                               #   WorkspaceURIs[], ProjectID}}} → título/metadata fácil
│   └── projects.json               # {workspace_path: project_id}
├── history.jsonl             # prompts sueltos: {display, timestamp(ms), workspace, conversationId}
├── brain/{uuid}/             # artefactos del agente (logs, scratch): NO leer
├── conversation_summaries.db # tablas vacío en la build observada → no usar
└── annotations/  implicit/  log/  mcp/  ...   # irrelevantes
```

Cada `.db` se abre **read-only**: `sqlite3.connect('file:...?mode=ro&immutable=1', uri=True)`
(`immutable=1` evita escribir el `-shm`/`-wal` de bases ajenas; la app puede estar corriendo).

## 2. Esquema de una base de conversación

| Tabla | Uso |
|-------|-----|
| `steps` (`idx`, `step_type`, `status`, `step_payload` BLOB) | la trajectory completa, ordenada por `idx` |
| `gen_metadata` (`idx`, `data` BLOB) | una fila por generación LLM (modelo + usage) |
| `trajectory_meta` (`trajectory_id`, `cascade_id`, `trajectory_type`) | metadatos de trajectory |
| `trajectory_metadata_blob` (`id='main'`, `data` BLOB) | **workspace URI** de la conversación |

**Los BLOBS son Protocol Buffers sin schema disponible** → se decodifican con un
lector wire-format genérico mínimo (~30 líneas, stdlib puro): varint / length-delimited /
fixed64 / fixed32, extrayendo solo los números de campo listados abajo. Nunca
`pickle`/`str()`/regex sobre el binario completo para sacar campos.

## 3. `steps.step_payload` (protobuf)

Nivel raíz: `f1` = step_type, `f4` = status, `f5` = envelope, `f19`/`f20` = payload del paso.

Envelope `f5`: `f1` = mensaje `{f1: epoch_segundos, f2: nanos}` (timestamp), `f9` = usage
de la generación (mismo blob que `gen_metadata`), `f12` = request-id.

### `step_type = 14` — mensaje del usuario
- `f19.f2` = **texto del prompt** (UTF-8; `f19.f3` es duplicado con prefijo → usar solo f2).
- `f19.f12.f12` = workspace `file:///...ruta-del-proyecto` (cwd de la sesión).

### `step_type = 15` — paso del agente (LLM)
- `f20.f1` = texto de respuesta visible (ausente en pasos solo-de-tools).
- `f20.f3` = título/pensamiento del paso (Markdown corto, ej. `**Initiating…`).
- `f20.f6` = id del bot/Agente (`bot-…`).
- `f20.f7` (repetido) = tool call: `f1` call-id, `f2` **nombre**, `f3` **arguments JSON**
  (con `DirectoryPath` / `AbsolutePath` / `Command` → señales de paths y comando).

### `step_type = 132` — resultado de tool
- `f5.f4.f2` = nombre de la tool ejecutada (para correlacionar); el output (`f140`)
  puede medir decenas de KB → **no se extrae**, solo se escanean rutas del `step_payload`
  con búsqueda limitada.

Otros step_types (5, 8, 9, 17, 21, 23, 25, 90, 98, 101, 127, 138): eventos internos
(mensajes task/subagent, planeador, perfiles) → ignorar por ahora; las tareas
sub-agente de Antigravity no generan conversaciones hijas separadas en estas builds.

## 4. `gen_metadata.data` (modelo + usage)

`f1` = registro de generación:
- `f19` = **modelo** (`gemini-3.8-flash`, `gemini-3.8-flash-high`, …).
- `f4` = usage: `f3` = tokens de salida, `f5` = tokens de contexto/entrada (crece con
  la conversación = prompt total), `f9` ≈ tokens de razonamiento/generación intermedia
  (semántica no confirmada del todo). Campos `f1` (constante por conversación) y `f6=24`
  sin interpretar.
- `f20` (repetido, map key/value) = tags: `model_enum`, `used_claude`, `trajectory_id`…

En la build observada no hay **costo en dinero** por generación → los reportes de
Antigravity muestran tokens, no `$`. La suma por conversación sale de agregar todas
las filas `gen_metadata` (índices `f19` modelo + `f4` usage por fila; ~1 MB por db
conversa grande → trivial).

## 5. Algoritmo de Adjudicación de Proyecto (modo "paralelo con adjudicación")

Reutiliza `_collect_claude_project_cwds()` / `_best_project_match()` de Pencil/OpenCode:

1. **Regla `cwd`** — workspace de `trajectory_metadata_blob` (fallback: `f19.f12.f12` del
   primer step 14, fallback: `WorkspaceURIs` del cache): prefijo común con contención
   real contra los cwd Claude (mínimo 4 segmentos). Empate ⇒ regla 2.
2. **Regla `paths`** — votación sobre rutas extraídas de `arguments` de tool calls
   (`DirectoryPath`/`AbsolutePath`/`Command`) y texto de prompts (mismo criterio).
3. **Regla `tiempo`** — solape `[start,end]` (min/max timestamps de `steps`) con
   mensajes Claude; gana el cwd más frecuente de la ventana.
4. Sin match ⇒ sección "Sin proyecto identificable".

Cada sesión reporta **qué regla** la adjudicó. Nota: los workspaces de Antigravity
suelen estar fuera de `.claude/projects` (p. ej. el mismo repo) — la regla cwd usa el
mismo `_best_project_match` que Pencil, que ya exige contención real sobre los cwd
observados en las sesiones Claude procesadas.

## 6. Uso

```bash
python3 process_sessions.py <dir-sesiones-claude> -o reportes --antigravity-dir ~/.gemini/antigravity-cli/
```

Reportes generados:

- `16_antigravity_sesiones.md` — conversaciones agrupadas por proyecto Claude
  (cronología, modelo, workspace, tokens, regla de matching) + Q&A.
- `17_antigravity_modelos_uso.md` — ranking por modelo: requests, tokens, contexto
  máximo, tools.
- Sección "Consumo Antigravity" dentro de `09_eficiencia_tokens.md`.

## 7. Notas y trampas

- Un `.db` por conversación: el descubrimiento es `conversations/*.db` (el `.pb` antiguo
  y las rutas de `cache/` que no tienen `.db` se listan como no-parseables si no hay datos).
- `immutable=1` + `mode=ro` es obligatorio: si falta una de las dos, SQLite puede crear
  `-wal`/`-shm` o bloquear la escritura de la app.
- Timestamps en **segundos + nanos** protobuf (no ms como OpenCode); `history.jsonl`
  usa ms. Convertir a ISO-8601 UTC para el matching temporal.
- `step_payload` puede traer tool-results de ~100 KB → el escaneo de rutas se limita a
  los primeros N bytes de los strings de arguments, nunca regex sobre el blob completo.
- El prompt del usuario llega crudo (sin inyecciones tipo Pencil): la limpieza aplica
  solo recorte por longitud.
- `cache/conversation_metadata.json` aporta `Preview` (título generado) y `WorkspaceURIs`
  sin abrir el db, pero puede estar desactualizado → los datos finos salen siempre del db.
```
