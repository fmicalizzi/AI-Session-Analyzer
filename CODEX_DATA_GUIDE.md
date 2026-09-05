# Guía de Datos e Integración de Codex CLI

Esta guía documenta la estructura de datos interna de **Codex CLI** (OpenAI, modelo GPT-5.4) y el mecanismo utilizado por **AI Session Analyzer** para detectar, correlacionar y enriquecer reportes cuando Claude Code delega trabajo a Codex.

---

## 1. Estructura de Directorios de Codex (`~/.codex/`)

Por defecto, Codex CLI almacena sus estados, metadatos y registros en el directorio del usuario:

```
~/.codex/
├── state_5.sqlite                  # Base de datos SQLite principal con hilos y sesiones
├── session_index.jsonl             # Índice de nombres asignados a cada sesión
└── sessions/                       # Registros detallados (rollouts) por sesión
    └── {subdirectorios_opcionales}/
        └── rollout-{timestamp}-{thread_id}.jsonl
```

---

## 2. Base de Datos SQLite (`state_5.sqlite`)

La base de datos contiene la tabla principal `threads`, la cual registra metadatos de alto nivel de cada ejecución:

### Esquema de la tabla `threads`

| Columna | Tipo | Descripción |
| :--- | :--- | :--- |
| `id` | TEXT (PK) | Identificador único del hilo / sesión (UUID) |
| `title` | TEXT | Título inferido o asignado a la tarea |
| `first_user_message`| TEXT | Primer prompt enviado por el usuario o agente invocador |
| `cwd` | TEXT | Directorio de trabajo en el que operó Codex |
| `tokens_used` | INTEGER | Cantidad total de tokens consumidos en la ejecución |
| `created_at` | INTEGER | Timestamp UNIX en segundos de creación |
| `updated_at` | INTEGER | Timestamp UNIX en segundos de última actividad |
| `model` | TEXT | Modelo utilizado (por defecto `gpt-5.4`) |
| `cli_version` | TEXT | Versión del binario de Codex CLI |
| `source` | TEXT | Origen de la sesión (ej. `vscode`, `cli`, etc.) |

AI Session Analyzer filtra los registros relevantes con:
```sql
SELECT id, title, first_user_message, cwd, tokens_used,
       created_at, updated_at, model, cli_version
FROM threads
WHERE source = 'vscode' OR tokens_used > 1000
ORDER BY created_at
```

---

## 3. Archivo de Índice (`session_index.jsonl`)

Contiene entradas individuales en formato JSONL asociando IDs con nombres legibles:

```json
{"id": "c71a3962-e9a2-4632-a589-3dfa3014a081", "thread_name": "fix-order-processing-bug"}
```

---

## 4. Archivos de Ejecución Detallada (`rollout-*.jsonl`)

Cada archivo `rollout-{timestamp}-{thread_id}.jsonl` almacena cada paso paso del ciclo de inferencia y ejecución:

### Tipos de eventos registrados:
1. **`user` (`type: "response_item", role: "user"`)**:
   - Prompts de entrada y contenido de contexto (`input_text`).
2. **`reasoning` (`type: "response_item", payload.type: "reasoning"`)**:
   - Los pasos de razonamiento y cadena de pensamiento (*thought process*) del modelo GPT-5.4.
3. **`function_call` (`type: "response_item", payload.type: "function_call"`)**:
   - Comandos bash ejecutados, argumentos y scripts corridos.
4. **`function_call_output`**:
   - Salidas del terminal (stdout / stderr) generadas tras la ejecución de los comandos.
5. **`assistant` (`type: "response_item", role: "assistant"`)**:
   - Respuestas finales y resúmenes completos generados por Codex.

---

## 5. Algoritmo de Correlación Claude → Codex

Cuando Claude Code delega una tarea a Codex, lo hace mediante:
- Herramienta `Agent` con `subagent_type: "codex:codex-rescue"`
- Herramienta `Skill` con prefijo `codex:*`
- Comando `Bash` ejecutando `codex-companion.mjs`

### Criterios de Matching:
1. **Proximidad Temporal (Ventana de ±120 segundos)**:
   - Se compara la marca de tiempo de la delegación en Claude con el `created_at` del hilo en Codex.
2. **Coincidencia de Proyecto y CWD**:
   - Mismo nombre de carpeta o ruta base (`bonus -50` en el score). Discrepancias aplican una penalización severa (`penalty +200`).
3. **Superposición de Palabras Clave del Prompt**:
   - Análisis de palabras clave entre la tarea delegada por Claude y el prompt inicial registrado en Codex (`bonus -30` o `-10`).
4. **Umbral de Aceptación**:
   - Puntuaciones con `score > 150` se descartan para prevenir falsos positivos.

---

## 6. Reporte Generado (`10_codex_integrado.md`)

El reporte integrado unifica la visión de ambos agentes:
- El prompt completo original que Claude le envió a Codex.
- Todo el razonamiento interno y pasos reflexivos de GPT-5.4.
- Los comandos de shell ejecutados por Codex junto con sus resultados.
- La respuesta final íntegra (superando los resúmenes truncados a 5KB que Claude recibe de regreso).
