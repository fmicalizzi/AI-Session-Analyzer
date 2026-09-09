# Guía de Datos e Integración de Pencil (pen.dev)

Esta guía documenta la estructura de datos que genera **Pencil** (herramienta de diseño con
agentes, pen.dev) y el mecanismo usado por **AI Session Analyzer v5.0** para parsear sus
sesiones y adjudicarlas al proyecto Claude correspondiente.

---

## 1. Estructura de Directorios de Pencil (`~/.pencil/`)

```
~/.pencil/
├── sessions/                       # Sesiones del editor desktop (JSON grande por sesión)
│   └── {uuid}.json
└── pi-sessions/                    # Log real del agente (JSONL, formato "pi" v3)
    └── {timestamp}_{uuid}.jsonl    # ej: 2026-09-08T15-13-22-768Z_01a08194-....jsonl
```

**Fuente de verdad para el análisis:** los `.jsonl` de `pi-sessions/`. Los `.json` de
`sessions/` solo aportan metadatos (título, vínculo).

---

## 2. `pi-sessions/*.jsonl` (agente)

Línea 1 = cabecera de sesión con el **cwd del proyecto** (clave para el matching):

```json
{"type":"session","version":3,"id":"01a08194-...","timestamp":"2026-09-08T15:13:22.768Z","cwd":"/Users/.../03-storyboard"}
```

Eventos relevantes:

| `type` | Contenido usado |
|--------|-----------------|
| `session` | `id`, `timestamp`, `cwd` |
| `model_change` | `provider`, `modelId` (modelo vigente hasta el próximo cambio) |
| `message` role=`user` | texto del usuario + bloques inyectados por la app (a limpiar) |
| `message` role=`assistant` | `model`, `usage` (input/output/reasoning/cacheRead/cacheWrite/totalTokens/cost.total), `content[]` con `thinking`, `toolCall` (`name`, `arguments.filePath`), `text` |
| `message` role=`toolResult` | solo se escanea para extraer rutas absolutas |

**Limpieza del mensaje de usuario:** se recorta desde el primer marcador de inyección
(`The result of \`get_app_state\` tool call:`, `This app state was fetched`, adjuntos
`@{"type":"nodes",...}`), dejando el prompt real.

**Emparejamiento Q&A:** mensaje user limpio → primer texto assistant posterior (se
concatenan los bloques `text` del turno). Los turnos sin respuesta de texto se marcan.

---

## 3. `sessions/*.json` (desktop)

```json
{"version":1,
 "conversation":{"id":"9c0fce06-...","title":"...","modelID":"pi;opencode-go;qwen3.8-max",
                 "sessionId":"/Users/.../.pencil/pi-sessions/....jsonl",
                 "messages":[{"role":"user","text":"..."}]},
 "bindings":{...}}
```

- `conversation.sessionId` es la **ruta absoluta al .jsonl** → vínculo 1:1 exacto con
  `pi-sessions` (indexado por nombre de archivo).
- `title` se usa como encabezado de la sesión en los reportes.
- Los `messages[].text` se escanean con regex para extraer rutas `/Users|/home/...`
  (señal para el matching por paths cuando el cwd no pertenece a ningún proyecto).

---

## 4. Algoritmo de Adjudicación de Proyecto (v5.0)

Input: set de `cwd`s de los mensajes Claude procesados (`_collect_claude_project_cwds`).

1. **Regla `cwd`** — mayor prefijo de segmentos de ruta entre el `cwd` de la sesión
   Pencil y cada proyecto Claude. Coincide tanto si Pencil está en una **subcarpeta**
   del proyecto como en su raíz. Mínimo 4 segmentos compartidos; empate entre dos
   proyectos ⇒ pasa a la regla 2. Desde v5.1 además exige **contención real**: el
   `cwd` debe estar en la raíz del proyecto o por debajo (elimina falsos positivos
   entre hermanos de `~/Claude` que solo comparten la raíz común).
2. **Regla `paths`** — votación: las rutas externas (.pen, documentos) extraídas de
   `toolCall.arguments.filePath` y del texto desktop buscan proyecto con el mismo
   criterio de prefijo común; gana la puntuación más alta (sin empate).
3. **Regla `tiempo`** — último recurso: la ventana temporal de la sesión Pencil se
   solapa con timestamps de mensajes Claude; se toma el `cwd` más frecuente en la
   ventana.
4. Sin match ⇒ sección "Sin proyecto identificable" (auditable en el reporte).

Cada sesión reporta **qué regla** la adjudicó, para poder validar falsos positivos.

---

## 5. Uso

```bash
python3 process_sessions.py <dir-sesiones-claude> -o reportes --pencil-dir ~/.pencil/
```

Reportes generados:

- `12_pencil_sesiones_diseno.md` — sesiones agrupadas por proyecto Claude, cronología,
  y Q&A completo (prompt usuario + respuesta agente) con tokens/costo por sesión.
- `13_pencil_modelos_uso.md` — ranking por modelo: requests, tokens, costo, $/turno y
  tasa de turnos con respuesta de texto.
- Sección "Consumo Pencil" dentro de `09_eficiencia_tokens.md`.

## 6. Notas de rendimiento

- Archivos de hasta ~46 MB: el parseo es streaming línea a línea (sin cargar el JSON
  completo), texto truncado en el reporte (8 KB usuario / 12 KB agente por turno).
- Los `.pen` son cifrados: nunca se leen, solo se referencian sus rutas.
