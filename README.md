# AI Session Analyzer

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Dependencies: Stdlib Only](https://img.shields.io/badge/dependencies-0%20(stdlib%20only)-brightgreen.svg)](requirements.txt)
[![CI](https://github.com/fmicalizzi/AI-Session-Analyzer/actions/workflows/ci.yml/badge.svg)](https://github.com/fmicalizzi/AI-Session-Analyzer/actions/workflows/ci.yml)

Script y suite en Python para procesar, auditar y analizar sesiones de múltiples agentes de IA (**Claude Code**, **OpenAI Codex**, **Qwen CLI**, **Pencil/pen.dev**, **OpenCode CLI**, **Antigravity CLI**), extrayendo información clave, métricas de tokens, operaciones de archivos y generando reportes estructurados.

## Descripción

Este script procesa sesiones de Claude Code como fuente principal, integrando delegaciones a Codex (GPT-5.4) y la actividad **paralela** que otros agentes realizaron sobre los mismos proyectos: Qwen CLI, Pencil (pen.dev), OpenCode CLI y Antigravity CLI (Google). Las sesiones de estos últimos se **adjudican automáticamente** al proyecto Claude correspondiente (3 reglas auditables: cwd → paths → tiempo). Genera reportes detallados que incluyen:
- Histórico de mensajes del usuario
- Respuestas del sistema
- Pares de preguntas y respuestas
- Operaciones de archivos ejecutadas
- Análisis de flujo de trabajo con contexto técnico
- **v3.0:** Actividad detallada de subagentes
- **v3.0:** Memoria del proyecto (decisiones, lecciones técnicas)
- **v3.0:** Tool-results externos (Playwright snapshots, etc.)
- **v3.1:** Reporte de eficiencia y consumo de tokens (por sesión, ranking, modelos)
- **v4.0:** Integración con Codex CLI (GPT-5.4) — detecta delegaciones, matchea sesiones, enriquece reportes
- **v4.1:** Integración con Qwen CLI — visibilidad de actividad paralela en el mismo proyecto
- **v5.0:** Integración con Pencil (pen.dev) — sesiones de diseño con Q&A recuperado y adjudicación inteligente al proyecto Claude (cwd/.pen/timestamps) + estadisticas por modelo
- **v5.1:** Integración con OpenCode CLI — sesiones paralelas leídas de `opencode.db` (SQLite), Q&A + tokens/costo por modelo y adjudicación al proyecto Claude (cwd/paths/timestamps)
- **v5.2 (Actual):** Integración con Antigravity CLI (Google, `agy`) — conversaciones leídas de `conversations/*.db` (SQLite + protobuf), Q&A + tokens/modelos y adjudicación al proyecto Claude (workspace/paths/timestamps)

## Instalación

### Requisitos
- Python 3.8 o superior
- **Cero dependencias externas**: Utiliza exclusivamente la biblioteca estándar de Python (`json`, `sqlite3`, `pathlib`, `datetime`, `argparse`, `re`, `os`, `sys`).

### Opciones de Instalación

**Opción 1: Uso directo (sin instalación)**
```bash
git clone https://github.com/fmicalizzi/AI-Session-Analyzer.git
cd AI-Session-Analyzer
python3 process_sessions.py --help
# O alternativamente:
python3 ai_session_analyzer.py --help
```

**Opción 2: Instalación como comando CLI global o en entorno virtual**
```bash
pip install -e .
# Ahora puedes ejecutarlo desde cualquier directorio:
ai-session-analyzer --help
process-sessions --help
```

## Uso

### Uso Básico
```bash
# Procesar archivos JSONL en el directorio actual
python3 process_sessions.py .

# Procesar archivos en un directorio específico
python3 process_sessions.py /ruta/a/carpeta/con/sesiones/

# Especificar directorio de salida personalizado
python3 process_sessions.py . -o mi_carpeta_reportes
```

### Funcionalidades v2.0
```bash
# Extraer las últimas 30 conversaciones en archivo separado
python3 process_sessions.py . -o reportes --last 30

# Generar historial completo de modificaciones de un archivo específico
python3 process_sessions.py . -o reportes --file-history CLAUDE.md

# Combinar ambas funcionalidades
python3 process_sessions.py . -o reportes --last 20 --file-history process_sessions.py
```

### Funcionalidades v3.0 (Subagentes y Memoria)
```bash
# Procesamiento completo (por defecto incluye subagentes, tool-results y memoria)
python3 process_sessions.py . -o reportes

# Omitir procesamiento de subagentes (más rápido, solo JSONL principales)
python3 process_sessions.py . -o reportes --no-subagents
```

### Funcionalidades v4.0 (Integración Codex)
```bash
# Integrar delegaciones a Codex CLI (GPT-5.4)
python3 process_sessions.py . -o reportes --codex-dir ~/.codex/
```

### Funcionalidades v4.1 (Integración Qwen)
```bash
# Incluir actividad paralela de Qwen sobre el mismo proyecto
python3 process_sessions.py . -o reportes --qwen-dir ~/.qwen/

# Combinado completo: Claude + Codex + Qwen
python3 process_sessions.py . -o reportes --codex-dir ~/.codex/ --qwen-dir ~/.qwen/
```

### Funcionalidades v5.0 (Integración Pencil)
```bash
# Incluir sesiones de diseño del agente Pencil, adjudicadas al proyecto Claude
python3 process_sessions.py . -o reportes --pencil-dir ~/.pencil/
```

### Funcionalidades v5.1 (Integración OpenCode)
```bash
# Incluir sesiones paralelas de OpenCode CLI (opencode.db), adjudicadas al proyecto Claude
python3 process_sessions.py . -o reportes --opencode-dir ~/.local/share/opencode/
```

### Funcionalidades v5.2 (Integración Antigravity CLI)
```bash
# Incluir conversaciones de Antigravity CLI (Google, agy), adjudicadas al proyecto Claude
python3 process_sessions.py . -o reportes --antigravity-dir ~/.gemini/antigravity-cli/
```

### Combinado completo (todos los agentes)
```bash
python3 process_sessions.py . -o reportes \
  --codex-dir ~/.codex/ --qwen-dir ~/.qwen/ --pencil-dir ~/.pencil/ \
  --opencode-dir ~/.local/share/opencode/ --antigravity-dir ~/.gemini/antigravity-cli/
```

### Ver todas las opciones
```bash
python3 process_sessions.py --help
```

### Estructura de Archivos de Entrada
```
tu-proyecto/
├── process_sessions.py              # El script
├── sesion1.jsonl                    # Archivos de sesiones Claude
├── sesion2.jsonl
├── {uuid-sesión}/                   # Directorio de sesión (v3.0)
│   ├── subagents/                   # Subagentes de la sesión
│   │   ├── agent-aa22126.jsonl
│   │   ├── agent-acompact-d70276.jsonl
│   │   └── ...
│   └── tool-results/                # Resultados de tools externos
│       ├── b06525d.txt
│       ├── mcp-playwright-snapshot-*.txt
│       └── ...
├── memory/                          # Memoria del proyecto (v3.0)
│   ├── MEMORY.md
│   └── technical-notes.md
└── reports/                         # Carpeta generada automáticamente
    ├── 00_resumen_sesiones.md
    ├── 01_historico_mensajes_usuario.md
    ├── 02_respuestas_sistema.md
    ├── 03_preguntas_respuestas.md
    ├── 04_operaciones_archivos.md
    ├── 05_qa_mejorado_con_operaciones.md
    ├── 06_subagentes_detalle.md          # v3.0
    ├── 07_memoria_proyecto.md            # v3.0
    ├── 08_tool_results_externos.md       # v3.0
    ├── 09_eficiencia_tokens.md           # v3.1
    ├── 10_codex_integrado.md             # v4.0 (con --codex-dir)
    ├── 11_qwen_paralelo.md               # v4.1 (con --qwen-dir)
    ├── 12_pencil_sesiones_diseno.md      # v5.0 (con --pencil-dir)
    ├── 13_pencil_modelos_uso.md          # v5.0 (con --pencil-dir)
    ├── 14_opencode_sesiones.md           # v5.1 (con --opencode-dir)
    ├── 15_opencode_modelos_uso.md        # v5.1 (con --opencode-dir)
    ├── 16_antigravity_sesiones.md        # v5.2 (con --antigravity-dir)
    ├── 17_antigravity_modelos_uso.md     # v5.2 (con --antigravity-dir)
    ├── log_operaciones_archivos.md
    ├── ultimas_N_conversaciones.md       (opcional con --last)
    └── historial_ARCHIVO.md              (opcional con --file-history)
```

### Datos de Codex (fuente externa, v4.0)
```
~/.codex/                            # Directorio de Codex CLI (--codex-dir)
├── state_5.sqlite                   # Índice de threads y metadata
├── session_index.jsonl              # Nombres de companion tasks
└── sessions/                        # Rollouts completos
    └── YYYY/MM/DD/
        └── rollout-{ts}-{thread_id}.jsonl
```
Ver `CODEX_DATA_GUIDE.md` para documentación detallada del formato.

### Datos de Qwen (fuente externa, v4.1)
```
~/.qwen/                             # Directorio de Qwen CLI (--qwen-dir)
└── projects/
    └── {path-encoded}/              # Mismo encoding que Claude
        └── chats/
            └── {uuid}.jsonl         # Sesiones (formato similar a Claude)
```

### Datos de Pencil (fuente externa, v5.0)
```
~/.pencil/                           # Directorio de Pencil (--pencil-dir)
├── pi-sessions/
│   └── {ts}_{uuid}.jsonl            # Log del agente: cabecera con CWD + mensajes con usage
└── sessions/
    └── {uuid}.json                  # Desktop: título + vínculo sessionId -> .jsonl
```
Ver `PENCIL_DATA_GUIDE.md` para el formato y el algoritmo de adjudicación.

### Datos de OpenCode (fuente externa, v5.1)
```
~/.local/share/opencode/             # Directorio de datos de OpenCode (--opencode-dir)
└── opencode.db                      # SQLite (WAL): session -> message -> part
```

| Tabla | Contenido |
|-------|-----------|
| `session` | `directory` (cwd), `title`, `parent_id` (sub-agentes), rollup de `cost`/`tokens_*` |
| `message` | `data` JSON: role user/assistant con `modelID`, `providerID`, `cost`, `tokens` |
| `part` | `data` JSON: `text` (con flag `synthetic` a filtrar), `tool`, `patch`, `file` |
| `project` | `worktree` (raiz del repo) por `project_id` |

Se abre **read-only** y todo se extrae con `json_extract` + `substr` server-side:
los `data` crudos pueden medir decenas de MB (`summary.diffs`, `tool.state.output`)
y nunca se cargan. Ver `OPENCODE_DATA_GUIDE.md` para el detalle.

### Datos de Antigravity CLI (fuente externa, v5.2)
```
~/.gemini/antigravity-cli/           # Directorio de datos de Antigravity CLI (--antigravity-dir)
├── conversations/{uuid}.db          # UNA base SQLite por conversación (fuente de verdad)
└── cache/conversation_metadata.json # titulos/workspace (metadata liviana)
```

| Tabla | Contenido |
|-------|-----------|
| `steps` | `step_payload` **protobuf**: type 14 (prompt user + workspace), 15 (respuesta/tools del agente), 132 (tool results) |
| `gen_metadata` | una fila por generación LLM: modelo (`gemini-3.8-flash`, `claude-sonnet-4-6`, …) + usage |
| `trajectory_metadata_blob` | workspace `file:///...` de la conversación (clave del matching) |

Los BLOBs se decodifican con un lector wire-format genérico (sin schema, stdlib):
nunca se regexean los binarios completos y los tool-results (~100 KB) se descartan.
Ver `ANTIGRAVITY_DATA_GUIDE.md` para el detalle.

## Reportes Generados

### 1. Resumen de Sesiones (`00_resumen_sesiones.md`)
- Estadisticas generales (mensajes, operaciones, Q&A)
- v4.x: Estadisticas de Codex y Qwen
- v5.x: Bloque "Agentes externos" — sesiones/turnos/tokens/costo de Pencil, OpenCode y Antigravity con cuantas quedaron adjudicadas a un proyecto Claude
- v3.1: Tokens por sesión (input, output, cache creation, cache read)
- v3.1: Modelo principal por sesión
- v3.0: Conteo de subagentes por sesión
- v3.0: Herramientas usadas por subagentes
- v3.0: Modelos de subagentes y uso de tokens
- v3.0: Directorios de sesión detectados
- Herramientas más utilizadas
- Timeframes de las sesiones

### 2. Histórico de Mensajes (`01_historico_mensajes_usuario.md`)
- Todos los prompts del usuario
- Organizados cronológicamente
- Con timestamps y contexto

### 3. Respuestas del Sistema (`02_respuestas_sistema.md`)
- Respuestas cuando se completaron tareas
- Información técnica y confirmaciones
- Modelos utilizados

### 4. Pares Q&A Básicos (`03_preguntas_respuestas.md`)
- Conversaciones completas estructuradas
- Formato pregunta-respuesta

### 5. Operaciones de Archivos (`04_operaciones_archivos.md`)
- Lista de todas las operaciones realizadas
- v3.0: Incluye operaciones de subagentes en sección separada
- Formato: Operación | Archivo | Herramienta | Linea

### 6. Q&A Mejorado con Operaciones (`05_qa_mejorado_con_operaciones.md`)
**El reporte más valioso!**

Para cada pregunta-respuesta incluye:
- Operaciones de archivos ejecutadas durante esa interacción
- Resumen: Herramientas utilizadas, archivos tocados, total de operaciones
- Detalle por herramienta: Ejemplos específicos de cada operación
- **v3.0: Subagentes invocados** - Para cada subagente muestra:
  - Modelo utilizado y duración
  - Tarea asignada (prompt)
  - Herramientas y archivos que tocó
  - Uso de tokens

### 7. Detalle de Subagentes (`06_subagentes_detalle.md`) - v3.0
**Nuevo en v3.0!**

Reporte completo de todos los subagentes:
- Estadisticas globales (total, por tipo, tokens, herramientas top)
- Detalle por sesión con todos los subagentes
- Para cada subagente: tarea asignada, herramientas usadas, archivos tocados, resultado
- Detección de sesiones compactadas (context window management)

### 8. Memoria del Proyecto (`07_memoria_proyecto.md`) - v3.0
**Nuevo en v3.0!**

Contenido de la carpeta `memory/`:
- Índice de memoria (MEMORY.md)
- Archivos de memoria con sus metadatos (frontmatter)
- Decisiones de proyecto, lecciones técnicas, preferencias del usuario

### 9. Tool-Results Externos (`08_tool_results_externos.md`) - v3.0
**Nuevo en v3.0!**

Inventario de resultados de tools externalizados:
- Categorizados por tipo (Playwright/Browser, MCP Tools, Otros)
- Tamaño de cada archivo
- Preview del contenido

### 10. Eficiencia y Consumo de Tokens (`09_eficiencia_tokens.md`) - v3.1/v4.0
**Nuevo en v3.1!**

Reporte completo de consumo y eficiencia por sesión:
- **Consumo global:** Tabla comparativa sesiones principales vs subagentes (input, output, cache creation, cache read)
- **Cache hit rate:** Porcentaje de reutilización de contexto
- **Consumo por sesión:** Tabla con duración, Q&A, operaciones, tokens main/sub, tokens/Q&A, tokens/operación
- **Detalle por sesión:** Desglose de tokens, modelos usados, output ratio, cache efficiency
- **Ranking de eficiencia:** Sesiones ordenadas por tokens/Q&A (menor = más eficiente)
- **Uso de modelos global:** Que modelos se usaron, cuantas veces, tipo (principal/subagent/compaction)
- **v5.x:** Secciones "Consumo Pencil", "Consumo OpenCode" y "Consumo Antigravity" (tokens/costo por agente; Antigravity solo tokens, su fuente no publica USD)

Ideal para:
- Evaluar qué sesiones fueron más costosas y por qué
- Comparar eficiencia entre sesiones de desarrollo
- Entender la proporción de gasto en subagentes vs agente principal
- Medir la efectividad del cache de contexto

### 11. Codex Integrado (`10_codex_integrado.md`) - v4.0
**Nuevo en v4.0! Requiere `--codex-dir`**

Reporte completo de delegaciones Claude → Codex (GPT-5.4):
- **Timeline** de todas las invocaciones a Codex detectadas
- **Detalle por delegación matcheada:**
  - Tarea completa enviada a Codex (prompt integro)
  - Razonamiento del modelo GPT-5.4 (pasos de pensamiento)
  - Comandos ejecutados con sus outputs
  - Respuestas completas de Codex (no el resumen truncado que Claude recibió)
- **Match scoring:** timestamp + proyecto/CWD + overlap de prompt

### 12. Qwen Paralelo (`11_qwen_paralelo.md`) - v4.1
**Nuevo en v4.1! Requiere `--qwen-dir`**

Reporte de actividad paralela de Qwen CLI sobre el mismo proyecto:
- **Resumen:** Sesiones, mensajes, comandos ejecutados
- **Correlación temporal:** Días con actividad simultánea Claude+Qwen
- **Índice de sesiones:** Tabla con fecha, mensajes, comandos, branch
- **Detalle por sesión:**
  - Inputs del usuario
  - Respuestas del modelo (completas)
  - Comandos ejecutados (run_shell_command)
  - Todo intercalado cronológicamente

Útil para:
- Ver qué investigaba Qwen mientras Claude trabajaba en el mismo proyecto
- Comparar enfoques entre agentes para el mismo problema
- Recuperar análisis o datos que Qwen generó independientemente

### 13. Sesiones de Diseño Pencil (`12_pencil_sesiones_diseno.md`) - v5.0
**Nuevo en v5.0! Requiere `--pencil-dir`**

Sesiones del agente de diseño Pencil, agrupadas por el proyecto Claude al que pertenecen:
- **Adjudicación inteligente** en 3 reglas auditables (cada sesión reporta cuál la ganó):
  1. `cwd` — prefijo común más largo entre el directorio de la sesión Pencil y los proyectos Claude (funciona con subcarpetas del proyecto)
  2. `paths` — votación por rutas de archivos `.pen` cuando el cwd es un documento gestionado o raiz
  3. `tiempo` — desempate por solapamiento con actividad Claude
- **Q&A recuperado:** prompt real del usuario (sin el contexto inyectado por la app) + respuesta final del agente, por turno, con timestamp
- **Metadata por sesión:** título, cronología, modelo(s), tokens, costo USD, tools usadas, documentos `.pen` tocados
- Sección final "Sin proyecto identificable" para auditoria de sesiones sueltas

Útil para:
- Retomar trabajo de diseño sin reconstruir el contexto de la conversación anterior
- Saber qué se pidió y qué se acordó en cada sesión de maquetación

### 14. Uso de Modelos Pencil (`13_pencil_modelos_uso.md`) - v5.0
**Nuevo en v5.0! Requiere `--pencil-dir`**

Estadisticas de uso por modelo en las sesiones de diseño:
- Tokens (input/output/reasoning), requests API y **costo real en USD** por modelo
- **$/turno** de conversación y **tasa de turnos con respuesta de texto**
- Desglose por sesión con título, proyecto adjudicado y modelo dominante

Útil para:
- Validar con qué modelo rinde mejor el trabajo de diseño y con cuál continuar
- Comparar costo/eficiencia entre modelos en el mismo flujo

### 15. Sesiones OpenCode (`14_opencode_sesiones.md`) - v5.1
**Nuevo en v5.1! Requiere `--opencode-dir`**

Sesiones de OpenCode CLI agrupadas por el proyecto Claude al que pertenecen:
- **Adjudicación inteligente** en 3 reglas auditables (cada sesión reporta cuál la ganó):
  1. `cwd` — prefijo común con contención real sobre `session.directory` (funciona con subcarpetas)
  2. `paths` — votación por rutas de archivos reales (patches, tool inputs, adjuntos)
  3. `tiempo` — desempate por solapamiento con actividad Claude
- **Q&A recuperado:** prompt del usuario (descartando parts `synthetic`) + textos del
  agente por turno, con timestamp
- **Metadata por sesión:** título, agente, modelo+variant, tokens (in/out/reasoning/cache),
  costo USD, tools usadas, errores (p.ej. abortos)
- Las sesiones de **sub-agentes** (hijas de un `task`) se marcan y resumen sin Q&A completo
- Sección final "Sin proyecto identificable" para auditoria de sesiones sueltas

Útil para:
- Reconstruir qué se hizo con OpenCode en el mismo repo mientras Claude trabajaba
- Auditar costo/tokens reales por sesión (rollup de la propia base de OpenCode)

### 16. Uso de Modelos OpenCode (`15_opencode_modelos_uso.md`) - v5.1
**Nuevo en v5.1! Requiere `--opencode-dir`**

Estadisticas de uso por modelo (`provider/model (variant)`) en las sesiones OpenCode:
- Tokens (input/output/reasoning), requests assistant y **costo real en USD** por modelo
- **$/turno** de conversación y **tasa de turnos con respuesta de texto**
- Top 30 de herramientas usadas (incluye `invalid` = tool-calls erroneos del modelo)
- Desglose por sesión con título, proyecto adjudicado, agente y modelo dominante

Útil para:
- Comparar qué modelo/variant rinde mejor (costo por turno y respuestas de texto)
- Detectar sesiones abortadas o con errores por modelo

### 17. Sesiones Antigravity (`16_antigravity_sesiones.md`) - v5.2
**Nuevo en v5.2! Requiere `--antigravity-dir`**

Conversaciones de Antigravity CLI (una por `.db`) agrupadas por el proyecto Claude al que pertenecen:
- **Adjudicación inteligente** en 3 reglas auditables (cada conversación reporta cuál la ganó):
  1. `cwd` — workspace de la trajectory con prefijo común + contención real
  2. `paths` — votación por rutas de tool calls (AbsolutePath/DirectoryPath) y prompts
  3. `tiempo` — desempate por solapamiento con actividad Claude
- **Q&A recuperado:** prompt del usuario + textos de respuesta del agente por turno, con timestamp
- **Metadata por conversación:** título, workspace, steps, tokens (contexto/output/reasoning), tools usadas
- Sección final "Sin proyecto identificable" para auditoria de conversaciones sueltas

Útil para:
- Reconstruir qué se hizo con `agy` en el mismo repo mientras Claude trabajaba
- Auditar el consumo real por conversación (el workspace de Antigravity suele ser el mismo repo)

### 18. Uso de Modelos Antigravity (`17_antigravity_modelos_uso.md`) - v5.2
**Nuevo en v5.2! Requiere `--antigravity-dir`**

Estadisticas por modelo desde `gen_metadata` (fuente oficial de cada generación):
- Generaciones, tokens (contexto acumulado, output, reasoning) y tasa de turnos con respuesta
- Antigravity **no publica costo en dinero** en sus datos locales: el reporte es en tokens
- Top 30 de herramientas (`view_file`, `run_command`, `replace_file_content`, MCP…)
- Desglose por conversación con título, proyecto, workspace y modelos

Útil para:
- Comparar Gemini vs Claude (la CLI alterna modelos según tarea) en consumo real
- Detectar a qué proyecto fue cada conversación y con qué modelo se resolvió

### 19. Log de Operaciones CSV (`log_operaciones_archivos.md`)
Log simple compatible con Excel/Google Sheets:
- **Formato**: `Operación;Ruta;Herramienta;Sesión;Timestamp;Origen`
- v3.0: Columna `Origen` indica si es sesión principal o subagente
- Importable: Usar `;` como separador en hojas de calculo

### 20. Últimas N Conversaciones (`ultimas_N_conversaciones.md`)
**Generado con `--last N`**
- Extrae las últimas N conversaciones más recientes
- v3.0: Incluye subagentes vinculados a cada interacción

### 21. Historial de Archivo (`historial_ARCHIVO.md`)
**Generado con `--file-history FILENAME`**
- Timeline completo de modificaciones de un archivo específico
- v3.0: Incluye modificaciones hechas por subagentes

## Que Son los Subagentes

Claude Code utiliza **subagentes** para delegar trabajo en paralelo. Cuando el agente principal invoca la herramienta `Agent`, se crea un subagente que:

- Tiene su propio archivo JSONL en `{session-id}/subagents/`
- Usa su propio modelo (frecuentemente `claude-haiku` para tareas rápidas)
- Ejecuta herramientas independientemente (Read, Write, Bash, Grep, etc.)
- Puede usar MCP tools (Playwright, Shopify, etc.)
- Devuelve resultados al agente principal

**Tipos de subagentes:**
- `Explore` - Investigación y busqueda en el codebase
- `general-purpose` - Tareas generales
- `technical-writer` - Documentación
- `codex:codex-rescue` - Delegación a Codex CLI (GPT-5.4) vía OpenAI
- Sesiones `compact` - Subagentes cuyo contexto fue compactado

Sin el procesamiento de subagentes, se pierde entre el **30-60%** de las operaciones reales de una sesión.

## Integración con Codex (v4.0)

Claude Code puede delegar tareas a **Codex CLI** (OpenAI, modelo GPT-5.4). Cuando esto ocurre:
- Claude registra un `Agent` tool_use con `subagent_type: "codex:codex-rescue"`
- Claude recibe un resumen breve como tool_result (~2-5KB)
- La conversación completa de Codex (comandos, razonamiento, respuestas) vive en `~/.codex/sessions/`

Con `--codex-dir`, el script:
1. **Detecta** invocaciones a Codex en las sesiones de Claude (Agent, Skill, Bash)
2. **Matchea** cada invocación a la sesión de Codex correspondiente usando 3 criterios:
   - Proximidad temporal (±120s)
   - Mismo proyecto/CWD
   - Overlap de texto en el prompt
3. **Enriquece** los reportes con el detalle completo de lo que hizo Codex

Ver `CODEX_DATA_GUIDE.md` para documentación del formato de datos de Codex.

## Integración con Qwen (v4.1)

Qwen CLI es otro agente de IA que puede trabajar sobre los mismos proyectos que Claude. A diferencia de Codex (que es delegado por Claude), Qwen trabaja de forma **independiente** — no hay handoff automático.

Con `--qwen-dir`, el script:
1. **Detecta el CWD** del proyecto Claude actual
2. **Busca sesiones de Qwen** del mismo proyecto (usando el mismo encoding de paths)
3. **Parsea las sesiones** extrayendo inputs, respuestas y comandos
4. **Correlaciona temporalmente** — identifica días con actividad simultánea Claude+Qwen
5. **Genera reporte** `11_qwen_paralelo.md` con el detalle completo

### Formato de datos de Qwen

Qwen usa JSONL similar a Claude pero con diferencias:
- `message.parts` en vez de `message.content`
- `functionCall` / `functionResponse` en vez de `tool_use` / `tool_result`
- `role: "model"` en vez de `role: "assistant"`
- Herramienta principal: `run_shell_command`
- Eventos `type: "system"` con telemetria (se ignoran)

## Integración con Pencil (v5.0)

Pencil (pen.dev) es una herramienta de diseño con agente de IA. Sus sesiones no son delegadas por Claude sino que ocurren **en paralelo**, sobre subcarpetas del mismo proyecto (ej. `.../Video-06/03-storyboard`).

Con `--pencil-dir`, el script:
1. **Parsea en streaming** `~/.pencil/pi-sessions/*.jsonl` (log real del agente; archivos de +45 MB)
2. **Indexa** `~/.pencil/sessions/*.json` (desktop) para títulos y vínculo 1:1 con cada `.jsonl`
3. **Adjudica cada sesión** al proyecto Claude por prefijo de cwd → votación por rutas `.pen` → solapamiento temporal
4. **Recupera el Q&A** limpio de contexto inyectado, con tokens y costo USD por turno
5. **Genera** `12_pencil_sesiones_diseno.md`, `13_pencil_modelos_uso.md` y sección Pencil en `09_eficiencia_tokens.md`

### Formato de datos de Pencil

- Cabecera `{"type":"session", "cwd": ...}` con el directorio de trabajo
- Eventos `model_change` (provider/modelId vigente hasta el próximo cambio)
- Mensajes con `usage` por request: input/output/reasoning/cache + `cost.total` (USD real)
- `toolCall.arguments.filePath` referencia los `.pen` trabajados (nunca se leen: estan cifrados)

Ver `PENCIL_DATA_GUIDE.md` para documentación detallada del formato y el algoritmo de matching.

## Integración con OpenCode (v5.1)

OpenCode es una CLI de agentes de código abierto. Al igual que Pencil, sus sesiones ocurren **en paralelo** a las de Claude sobre los mismos repos, pero su fuente de datos es una **base SQLite** (`~/.local/share/opencode/opencode.db`) con estructura `session → message → part`.

Con `--opencode-dir`, el script:
1. **Abre la base read-only** y extrae sesiones, mensajes y parts con `json_extract` + caps `substr` server-side (los `data` crudos llegan a medir 31 MB; nunca se cargan enteros)
2. **Reconstruye el Q&A** por turno (parts `synthetic` = contexto inyectado, se descartan) y el **usage por modelo** desde los mensajes assistant; el total de tokens/costo sale del rollup de la propia tabla `session` (verificado: coincide exacto con la suma)
3. **Adjudica cada sesión** al proyecto Claude por prefijo de cwd con contención real → votación por rutas de patches/tools/adjuntos → solapamiento temporal (reutiliza el matching de Pencil; cada sesión reporta la regla usada)
4. **Distingue sub-agentes** (sesiones con `parent_id`, hijas de un `task`): se listan compactas, sin Q&A
5. **Genera** `14_opencode_sesiones.md`, `15_opencode_modelos_uso.md` y sección OpenCode en `09_eficiencia_tokens.md`

### Formato de datos de OpenCode

- `session.directory` = cwd de la sesión (clave del matching); `project.worktree` como refuerzo
- `message.data` JSON según rol: `user` (`summary.diffs` enorme — jamas seleccionar) / `assistant` (`modelID`, `providerID`, `cost`, `tokens`, `error` opcional)
- `part.data` JSON: `text`/`tool`/`patch`/`file`; `state.output` de tools nunca se extrae
- Relojes en epoch **milisegundos** → convertidos a ISO-UTC comparable con timestamps Claude

Ver `OPENCODE_DATA_GUIDE.md` para documentación detallada del esquema y el algoritmo de matching.

## Integración con Antigravity CLI (v5.2)

Antigravity CLI (`agy`, Google) es una CLI de agentes que alterna modelos Gemini y Claude.
Sus sesiones ocurren **en paralelo** a las de Claude sobre los mismos repos y su fuente de
datos es una **base SQLite por conversación** (`~/.gemini/antigravity-cli/conversations/{uuid}.db`)
con payloads **Protocol Buffers** sin schema pública.

Con `--antigravity-dir`, el script:
1. **Abre cada `.db` read-only** (`mode=ro&immutable=1`: nunca escribe al lado de la app) y recorre `steps` fila por fila
2. **Decodifica el wire-format protobuf** con un lector genérico mínimo: solo los números de campo documentados en `ANTIGRAVITY_DATA_GUIDE.md` (14=user, 15=agente, 132=tool result); los outputs de tools (decenas de KB) se descartan
3. **Reconstruye el Q&A** por turno y el **usage por modelo** desde `gen_metadata` (modelo + tokens de cada generación LLM)
4. **Adjudica cada conversación** al proyecto Claude: workspace (regla cwd) → votación por rutas de tool calls → solapamiento temporal (reutiliza el motor de Pencil; cada conversación reporta la regla usada)
5. **Genera** `16_antigravity_sesiones.md`, `17_antigravity_modelos_uso.md` y sección "Consumo Antigravity" en `09_eficiencia_tokens.md`

### Guías de integración

| Guía | Contenido |
|------|-----------|
| `CODEX_DATA_GUIDE.md` | Formato de datos de Codex CLI |
| `PENCIL_DATA_GUIDE.md` | Formato de datos de Pencil + algoritmo de adjudicación |
| `OPENCODE_DATA_GUIDE.md` | Formato del SQLite de OpenCode (opencode.db) + reglas de adjudicación |
| `ANTIGRAVITY_DATA_GUIDE.md` | Formato del SQLite+protobuf de Antigravity CLI (conversations/*.db) + reglas de adjudicación |
| `HOW_TO_ADD_A_PROVIDER.md` | **Checklist de 6 pasos para integrar una herramienta nueva** (Antigravity CLI, etc.) con trampas de performance ya conocidas |

## Opciones de Linea de Comandos

```
usage: process_sessions.py [-h] [-v] [-o OUTPUT] [--last LAST]
                           [--file-history FILE_HISTORY] [--no-subagents]
                           [--codex-dir CODEX_DIR] [--qwen-dir QWEN_DIR]
                           [--pencil-dir PENCIL_DIR]
                           [--opencode-dir OPENCODE_DIR]
                           [--antigravity-dir ANTIGRAVITY_DIR]
                           [input_dir]

Argumentos:
  input_dir             Directorio con archivos .jsonl o archivo individual (por defecto: '.')
  -v, --versión         Muestra el número de versión y sale
  -o, --output          Directorio de salida para reportes
  --last N              Extraer las últimas N conversaciones
  --file-history FILE   Generar historial de un archivo específico
  --no-subagents        No procesar subagentes ni tool-results
  --codex-dir DIR       Directorio de Codex CLI (~/.codex/) para integrar delegaciones
  --qwen-dir DIR        Directorio de Qwen CLI (~/.qwen/) para incluir sesiones paralelas
  --pencil-dir DIR      Directorio de Pencil (~/.pencil/) para integrar sesiones de diseño
  --opencode-dir DIR    Directorio de OpenCode (~/.local/share/opencode/) para integrar sesiones paralelas
  --antigravity-dir DIR Directorio de Antigravity CLI (~/.gemini/antigravity-cli/) para integrar sus conversaciones
```

## Características Técnicas

### Detección Automática
- Encuentra todos los archivos `.jsonl` automáticamente
- v3.0: Descubre carpetas de sesión con subagentes y tool-results
- v3.0: Detecta carpeta `memory/` si existe
- v4.0: Detecta invocaciones a Codex por patrones en tool_use
- v4.1: Matchea proyecto Claude con proyecto Qwen por CWD
- v5.0: Adjudica sesiones Pencil al proyecto Claude por prefijo de cwd, votación por rutas .pen o solapamiento temporal
- v5.1: Adjudica sesiones OpenCode (SQLite) al proyecto Claude por prefijo de cwd con contención real, votación por rutas de patches/tools o solapamiento temporal
- v5.2: Adjudica conversaciones Antigravity CLI (SQLite+protobuf) al proyecto Claude por workspace de la trajectory, votación por rutas de tool calls o solapamiento temporal
- Procesa múltiples sesiones

### Extracción Inteligente
- Nombres de archivos limpios (sin rutas largas)
- Detección de archivos del proyecto vs. sistema
- Agrupación por herramientas utilizadas
- v3.0: Vinculación de subagentes a interacciones Q&A por timestamp
- v3.0: Tracking de token usage por subagente

### Formatos de Salida
- Markdown bien estructurado
- Timestamps precisos
- v3.0: Log CSV con columna de origen (main/subagent)
- División automática de archivos >2MB

### División Automática de Archivos
- Detección automática de archivos >2MB
- Partes numeradas: `archivo_parte_1.md`, `archivo_parte_2.md`, etc.
- Índice navegable: `archivo_indice.md` con enlaces a todas las partes

### Detección de Operaciones
- Git: commit, push, pull, branch, clone, add
- Package Managers: npm, yarn, pip, poetry, conda
- File System: mkdir, cp, mv, rm, touch
- Build & Test: npm/yarn build, pytest, jest, cargo, maven
- Search: grep, find, ripgrep, locate
- v3.0: MCP tools (Playwright, Shopify, Cloudflare, etc.)
- v3.0: Agent invocations (subagent spawning)

## Actualizaciones

### Versión 5.2 (Actual)
- Integración con Antigravity CLI (Google, `agy`) vía `--antigravity-dir`
  (fuente: `~/.gemini/antigravity-cli/conversations/*.db`, una base SQLite por conversación)
- **Decoder wire-format protobuf genérico** (stdlib, sin schema): extrae prompts (step 14),
  respuestas/tool calls del agente (step 15) y modelos/usage desde `gen_metadata`;
  los tool-results (step 132, ~100 KB) se decodifican y descartan — parseo fila por fila
- Bases abiertas **read-only** con `mode=ro&immutable=1`: no interfiere con `agy` en ejecución
  y no deja archivos `-wal`/`-shm` en el directorio de la herramienta
- Adjudicación al proyecto Claude reutilizando el motor de Pencil/OpenCode con 3 reglas
  auditables: workspace (cwd) → votación por rutas de tool calls → solapamiento temporal
- Titulo/workspace reforzados con `cache/conversation_metadata.json` cuando el `.db` no aporta
- Nuevo reporte: `16_antigravity_sesiones.md` — conversaciones agrupadas por proyecto con Q&A
- Nuevo reporte: `17_antigravity_modelos_uso.md` — generaciones/tokens por modelo + top de tools
- Sección "Consumo Antigravity" agregada a `09_eficiencia_tokens.md` (la fuente no publica costo en USD)
- Documentación de formato en `ANTIGRAVITY_DATA_GUIDE.md`

### Versión 5.1
- Integración con OpenCode CLI vía `--opencode-dir` (fuente: `~/.local/share/opencode/opencode.db`)
- Lectura SQLite **read-only** con extracción `json_extract` + caps `substr` server-side:
  filas de `message`/`part` de hasta 31 MB nunca se cargan enteras (DB completa: <2 s)
- Tokens/costo desde el rollup de la tabla `session` (verificado contra la suma de mensajes)
  y usage por modelo (`provider/model (variant)`) desde los mensajes assistant
- Adjudicación al proyecto Claude reutilizando el motor de Pencil con 3 reglas auditables:
  cwd (prefijo con **contención real**) -> votación por rutas de patches/tools/adjuntos ->
  solapamiento temporal. Cada sesión reporta la regla usada y su score
- Sub-agentes (sesiones con `parent_id`) detectados, resumidos sin Q&A y marcados en la cronología
- Nuevo reporte: `14_opencode_sesiones.md` — sesiones agrupadas por proyecto con Q&A
- Nuevo reporte: `15_opencode_modelos_uso.md` — tokens, costo USD, $/turno, tasa de respuesta
  por modelo + top de herramientas
- Sección "Consumo OpenCode" agregada a `09_eficiencia_tokens.md`
- Documentación de formato en `OPENCODE_DATA_GUIDE.md`

### Versión 5.0
- Integración con Pencil / pen.dev (agente de diseño) vía `--pencil-dir`
- Parser streaming de `pi-sessions/*.jsonl` (archivos de hasta +45 MB)
- Adjudicación inteligente al proyecto Claude en 3 reglas auditables: prefijo de cwd ->
  votación por rutas `.pen` -> solapamiento temporal (cada sesión reporta la regla usada)
- Recuperación de Q&A de diseño: prompt del usuario (limpio de contexto inyectado por la app)
  + respuesta final del agente — para retomar trabajo sin reconstruir contexto
- Nuevo reporte: `12_pencil_sesiones_diseno.md` — sesiones agrupadas por proyecto con cronología
- Nuevo reporte: `13_pencil_modelos_uso.md` — tokens, costo real USD, $/turno y tasa de
  respuesta por modelo (validar con qué modelo conviene seguir diseñando)
- Sección "Consumo Pencil" agregada a `09_eficiencia_tokens.md`
- Documentación de formato en `PENCIL_DATA_GUIDE.md`

### Versión 4.1
- Integración con Qwen CLI vía `--qwen-dir`
- Detección automática de sesiones Qwen del mismo proyecto (por CWD)
- Parser de formato Qwen (parts, functionCall/functionResponse, model role)
- Nuevo reporte: `11_qwen_paralelo.md` — actividad paralela con detalle cronologico
- Correlación temporal: identifica días con actividad simultánea Claude+Qwen
- Resumen de sesiones enriquecido con estadisticas de Qwen

### Versión 4.0
- Integración con Codex CLI (OpenAI GPT-5.4) vía `--codex-dir`
- Detección automática de delegaciones a Codex (Agent, Skill, Bash)
- Matching de sesiones Codex por 3 criterios: timestamp + proyecto/CWD + prompt overlap
- Nuevo reporte: `10_codex_integrado.md` — tareas, comandos, razonamiento y respuestas completas
- Reporte de eficiencia ampliado con columna y tokens de Codex
- Resumen de sesiones enriquecido con estadisticas de Codex
- Q&A mejorado muestra delegaciones a Codex inline
- `CODEX_DATA_GUIDE.md` — documentación completa del formato de datos de Codex
- `extract_codex_full.py` — script standalone para análisis de Codex puro

### Versión 3.1
- Token tracking completo en sesiones principales (input, output, cache creation, cache read)
- Tracking de modelos usados por sesión
- Nuevo reporte: `09_eficiencia_tokens.md` - consumo global, por sesión, ranking de eficiencia
- Métricas de eficiencia: tokens/Q&A, tokens/operación, cache hit rate, output ratio
- Ranking de sesiones por eficiencia (menor tokens/Q&A = mejor)
- Tabla comparativa sesiones principales vs subagentes
- Uso de modelos global con clasificación (principal/subagent/compaction)

### Versión 3.0
- Procesamiento completo de subagentes (`{session}/subagents/agent-*.jsonl`)
- Lectura de tool-results externos (`{session}/tool-results/*.txt`)
- Análisis de memoria del proyecto (`memory/*.md`)
- Nuevo reporte: `06_subagentes_detalle.md` - estadisticas y detalle por subagente
- Nuevo reporte: `07_memoria_proyecto.md` - decisiones y lecciones técnicas
- Nuevo reporte: `08_tool_results_externos.md` - inventario de resultados externos
- Subagentes integrados en reportes 05 Q&A mejorado y últimas N conversaciones
- Resumen de sesiones enriquecido con stats de subagentes, modelos y tokens
- Log CSV con columna de origen (main vs subagent)
- File history incluye modificaciones de subagentes
- Flag `--no-subagents` para procesamiento rápido sin subagentes
- Fix: código inalcanzable en `_generate_file_history_report`
- Detección de rutas de proyecto más genérica (no hardcodeada)

### Versión 2.0
- División automática de archivos >2MB con índices navegables
- Log CSV exportable compatible con Excel/Google Sheets
- Detección ampliada de operaciones (Git, npm, pip, builds, tests)
- Filtros temporales con `--last N` para últimas conversaciones
- Historial por archivo con `--file-history` para auditorias
- Timestamps numericos para fácil ordenamiento

### Versión 1.0 (Base)
- Extracción mejorada de nombres de archivos
- Reporte Q&A con operaciones de archivos
- Detección automática de herramientas
- Formato Markdown optimizado

## Tests y Calidad

El proyecto incluye una suite completa de pruebas unitarias basadas en `unittest` (sin dependencias adicionales):

```bash
# Ejecutar todas las pruebas unitarias
python3 -m unittest discover tests

# O con pytest (si está instalado en tu entorno dev)
pytest
```

La suite cubre el nucleo (Q&A, duraciones, split de archivos) y cada integración con su propia clase
(`TestPencilIntegration`, `TestOpenCodeIntegration`, `TestAntigravityIntegration`): parseo con fixtures
sinteticos (JSONL, SQLite `session→message→part` y SQLite+protobuf según el caso), las 3 reglas de
adjudicación (cwd/paths/tiempo), los reportes generados y la degradación silenciosa ante fuentes faltantes.

CI (GitHub Actions) corre la suite en la matriz **Python 3.8 → 3.13 x ubuntu/macos**: el código debe
mantenerse compatible con 3.8 (sin walrus, `match` ni genéricos `list[...]`/`dict[...]` en anotaciones).
El procedimiento para sumar un agente nuevo está documentado en `HOW_TO_ADD_A_PROVIDER.md`.

## Desarrollado para

Desarrolladores, Project Managers y equipos que:
- Trabajan con múltiples agentes de IA (Claude, Codex, Qwen, Pencil, OpenCode, Antigravity CLI) en los mismos proyectos
- Necesitan documentar procesos de desarrollo asistidos por IA
- Quieren visibilidad completa de lo que hizo cada agente
- Buscan generar reportes técnicos automaticos
- Necesitan auditar qué hicieron los subagentes y agentes externos en cada sesión

---

**Pro Tip**: El reporte `05_qa_mejorado_con_operaciones.md` es el más valioso — muestra no solo qué archivos se tocaron en cada interacción, sino también qué hicieron los subagentes invocados y las delegaciones a Codex con sus respuestas completas.

**Pro Tip v4.0**: Con `--codex-dir ~/.codex/`, el reporte `10_codex_integrado.md` muestra TODO lo que hizo Codex: los 35+ comandos que ejecutó, su razonamiento, y la respuesta completa — no solo el resumen de 5KB que Claude recibió de vuelta.

**Pro Tip v4.1**: Con `--qwen-dir ~/.qwen/`, el reporte `11_qwen_paralelo.md` muestra la actividad de Qwen en el mismo proyecto, con correlación temporal para ver qué días ambos agentes estaban trabajando en paralelo.

**Pro Tip v5.x**: Pasando `--pencil-dir`/`--opencode-dir`/`--antigravity-dir` a la vez, los reportes `12_` a `17_` agrupan cada sesión externa **bajo su proyecto Claude** y muestran la regla de adjudicación usada (`cwd`/`paths`/`tiempo`). Si una sesión cae en "Sin proyecto identificable", la regla `tiempo` habra fallado por ambiguedad: revisa su workspace y sus rutas reales antes de desconfiar del matching.
