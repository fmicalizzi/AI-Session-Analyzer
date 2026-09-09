# Cómo agregar una nueva herramienta de agentes (checklist v5.2)

Guía de integración probada con **Codex (v4.0)**, **Qwen (v4.1)**, **Pencil (v5.0)**,
**OpenCode (v5.1)** y **Antigravity CLI (v5.2)**.
Cada herramienta nueva sigue los mismos 6 pasos de código + documentación + tests.
Tiempo típico: 1 sesión de trabajo.

---

## Fase 0 — Explorar el formato ANTES de codificar

```bash
ls -la ~/.<herramienta>/            # encontrar el directorio de datos
ls -lat ~/.<herramienta>/sessions/  # ver archivos recientes y TAMAÑOS
```

Preguntas a responder (con un `python3 - <<'EOF'` interactivo, no con el editor):

1. **¿Dónde vive cada sesión?** ¿JSONL línea a línea, un JSON grande, SQLite?
2. **¿Hay referencia al proyecto?** Buscar campos `cwd`, `workdir`, `project`, o rutas absolutas dentro de los mensajes. **Esto decide si se puede adjudicar al proyecto Claude.**
3. **¿Cómo se vinculan archivos entre sí?** (ej. Pencil: `conversation.sessionId` apunta al `.jsonl` real; Qwen: encoding del CWD como nombre de carpeta igual que Claude)
4. **¿Qué eventos/mensajes importan?** roles, tool calls, usage de tokens, costo.
5. **¿Qué tan grandes son los archivos?** Si hay +10 MB → parseo streaming obligatorio.

> **Escribí primero `<HERRAMIENTA>_DATA_GUIDE.md`** (plantilla: copiar `PENCIL_DATA_GUIDE.md`).
> Es el contrato que la próxima sesión va a releer en vez de re-descubrir todo.

## Fase 1 — Elegir el modo de integración

| Modo | Cuándo | Modelo a copiar |
|------|--------|-----------------|
| **Delegación** | Claude invoca la herramienta (handoff explícito) | `_detect_codex_invocations` + match por `tool_use_id` |
| **Paralelo simple** | La herramienta usa el MISMO path-encoded de proyectos | `_load_qwen_sessions` |
| **Paralelo con adjudicación** | cwd suelto/subcarpetas/documentos gestionados | `_load_pencil_sessions` + reglas cwd/paths/tiempo |

## Fase 2 — Los 6 hooks de código en `process_sessions.py`

Buscar los anclajes con:
```bash
grep -n "qwen\|pencil\|PENCIL" process_sessions.py
```

1. **`__init__`**: bloque de atributos nuevo:
   ```python
   # vNEXT: <Tool> integration
   self.<tool>_dir = None
   self.<tool>_sessions = []
   ```
2. **Parser**: `_load_<tool>_sessions(dir)` (descubrimiento + loop) y `_parse_<tool>_session(path)` (streaming, un dict por sesión). Reglas:
   - `for line in f: json.loads(line)` — nunca `json.load()` de archivos grandes.
   - Guardar SOLO lo necesario (textos con cap, no dumps de tool results).
   - Acumular `usage`/costo por sesión y por modelo si existen.
3. **`process_all_files()`**: agregar parámetro `<tool>_dir=None` + hook **en las dos ramas** (la de "sin jsonl" y la principal), copiando el bloque de `pencil_dir`.
4. **`main()`**: flag `--<tool>-dir`, pasarlo al processor, bump de `-v/--version` y `description`.
5. **`generate_reports()`**: hook condicional `if self.<tool>_sessions: self._generate_<tool>_report()`.
6. **Reportes**: métodos `_generate_<tool>_report()`. Numeración de archivos: seguir `12_/13_` (Pencil). Cada reporte termina en
   `self._split_large_file(output_file, full_content)` — nunca escribir directo sin ese guard.

**Reutilizar del matching de Pencil** (válido para cualquier herramienta nueva):
`_collect_claude_project_cwds()` → `_best_project_match(path)` (prefijo de segmentos, `min_common=4`, detección de ambigüedad) → `_match_pencil_project` como plantilla de las 3 reglas (cwd → votación por paths de archivos reales → solapamiento temporal). Cada sesión debe reportar **qué regla** la adjudicó o "sin proyecto" (sección aparte para auditoría).

## Fase 3 — Trampas de performance (todas nos mordieron)

- **NUNCA `re.findall(pattern, str(tool_input))`** sobre strings potencialmente MB (dicts con contenido de archivos). Usar `pattern.search()` + escaneo limitado (`[:4000]`) + patrones `re.compile` a nivel de clase. Ver fix en `_extract_file_path_from_input` (v5.0).
- Reporte 05 (`_generate_enhanced_qa_report`) recorre TODAS las operaciones por cada Q&A → es O(Q&A × ops). Con +5k ops y +1k Q&A ya tardaba minutos: medir antes de agregar loops similares (`sample <pid>` o `faulthandler.dump_traceback_later(50, exit=True)` para ver dónde arde).
- Regex de limpieza sobre texto largo: compilar perezosamente a nivel de clase (ver `PENCIL_INJECT_RE`).

## Fase 4 — Tests

Copiar la clase `TestPencilIntegration` de `tests/test_session_processor.py`:
- Fixture sintético chico (nunca datos reales del usuario).
- Cubrir: parseo (roles, limpieza de inyectados, usage), matching por cwd, fallback por paths, y que los reportes se generan con el contenido esperado.
- **Ojo con el umbral `min_common=4`**: usar rutas de fixture tipo `/Users/tester/dev/proj-app`.

```bash
python3 -m unittest discover tests   # lo que corre en CI
```

CI matrices Python **3.8 → 3.13**: no usar walrus `:=`, `match`, ni genéricos `list[str]`/`dict[...]` en anotaciones (usar `typing`).

## Fase 5 — Docs y release

1. `<HERRAMIENTA>_DATA_GUIDE.md` (estructura, tabla de eventos, matching, uso, performance).
2. README: actualizar Descripcion + bullet de versioneo, ejemplo de uso (`### Funcionalidades vNEXT`), árbol de `reports/`, sección numerada de cada reporte nuevo (**renumerar las siguientes**), bloque "Datos de X (fuente externa)", `## Integracion con X`, opciones de CLI, "Deteccion Automatica", y "Actualizaciones" (mover "(Actual)").
3. `pyproject.toml`: `version`, `description`, keywords.
4. Validar end-to-end con un proyecto REAL del usuario:
   ```bash
   python3 -u process_sessions.py ~/.claude/projects/<proyecto> -o /tmp/prueba --<tool>-dir ~/.<tool>/
   ```
   y revisar que el matching no mienta (reglas reportadas por sesión).

## Fase 6 — Commit y push

Estilo del repo: `feat: ...` / `docs: ...` / `perf: ...` (inglés, conventional commits).
```bash
git add -A && git commit -m "feat: vNEXT <Tool> integration ..." && git push origin main
gh run watch <id> --exit-status   # verde en la matriz antes de dar por hecho
```

---

## Referencia rápida (líneas aproximadas, v5.1)

| Pieza | Buscar |
|-------|--------|
| Hook de carga | `_load_pencil_sessions`, `_load_qwen_sessions`, `_load_opencode_sessions`, `_load_antigravity_sessions` |
| Parser | `_parse_pencil_session` (streaming), `_query_opencode_*` (SQLite: `json_extract` + `substr` server-side, jamás `SELECT data` crudo), `_parse_antigravity_conversation` (SQLite+protobuf: `_pb_fields` decodifica fila por fila, tool-results se descartan) |
| Matching | `_best_project_match`, `_match_pencil_project`, `_match_opencode_project`, `_match_antigravity_project`, `_collect_claude_project_cwds` |
| Reportes | `_generate_pencil_report`, `_generate_pencil_models_report`, `_generate_opencode_report`, `_generate_opencode_models_report`, `_generate_antigravity_report`, `_generate_antigravity_models_report` |
| Split seguro | `_split_large_file` |
| CLI | `main()` → `--pencil-dir` / `--opencode-dir` / `--antigravity-dir` como plantilla de flag |

### Si la fuente es SQLite (OpenCode, Antigravity y futuros)
- Abrir **read-only**: `sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)`; degradar con WARN si no se puede.
- Extraer campos con `json_extract(data,'$.x')` y `substr(...,1,N)` **en el SELECT**: evita traer `data` crudos de 30 MB. Verificar antes que la build tenga JSON1 (`SELECT json_extract('{"a":1}','$.a')`).
- Si la tabla tiene rollups de costo/tokens (`session.cost`, `tokens_*`), validar contra la suma de mensajes y usarlos: son exactos y gratis.
- ids tipo `msg_...`/`prt_...` suelen ser cronológicamente ordenables; aprovechar los índices `(session_id,...)` existentes en vez de ordenar por columnas no indexadas.
- Si los blobs son **protobuf sin schema** (Antigravity): lector wire-format genérico (`_pb_varint`/`_pb_fields`, ~40 líneas stdlib) extrayendo solo los números de campo documentados en la guía; jamás `re` sobre el binario completo. Abrir con `mode=ro&immutable=1` para no dejar `-wal`/`-shm` en el directorio de la app. Verificar que la metadata de la app (`cache/*.json`, archivo chico) sirve para títulos/workspace pero nunca como fuente de verdad.
