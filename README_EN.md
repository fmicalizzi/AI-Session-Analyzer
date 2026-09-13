# AI Session Analyzer

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![dependencies: 0 (stdlib only)](https://img.shields.io/badge/dependencies-0%20(stdlib%20only)-brightgreen.svg)]()
[![CI: passing](https://img.shields.io/badge/CI-passing-brightgreen.svg)]()

A Python script and toolkit to process, audit, and analyze sessions from multiple AI coding agents — **Claude Code**, **OpenAI Codex**, **Qwen CLI**, **Pencil/pen.dev**, **OpenCode CLI**, **Antigravity CLI (Google)**, and **pi** — extracting key information, token metrics, file operations, and generating structured reports.

## Overview

This tool processes Claude Code sessions as the primary source, integrating delegations to Codex (GPT-5.4) and parallel activity from other agents working on the same projects. External agent sessions are automatically attributed to the corresponding Claude project using 3 auditable rules: `cwd → paths → time overlap`.

### Key Features

- **Multi-agent support**: Claude Code, Codex, Qwen, Pencil, OpenCode, Antigravity CLI, pi
- **20+ structured reports**: From basic Q&A to detailed token efficiency analysis
- **Zero dependencies**: Uses only Python's standard library
- **Subagent tracking**: Captures 30-60% of operations that would otherwise be invisible
- **Smart project attribution**: 3-rule auditable matching (cwd → paths → time overlap)
- **Streaming parser**: Handles 45MB+ session files without loading them into memory
- **CI tested**: Python 3.8–3.13 on Ubuntu and macOS

## Installation

### Requirements

- Python 3.8 or higher
- Zero external dependencies (uses only stdlib: `json`, `sqlite3`, `pathlib`, `datetime`, `argparse`, `re`, `os`, `sys`)

### Quick Start

```bash
# Option 1: Direct usage (no installation)
git clone https://github.com/fmicalizzi/AI-Session-Analyzer.git
cd AI-Session-Analyzer
python3 process_sessions.py --help

# Option 2: Install as CLI command
pip install -e .
ai-session-analyzer --help
```

## Usage

### Basic

```bash
# Process JSONL files in the current directory
python3 process_sessions.py .

# Process files in a specific directory
python3 process_sessions.py /path/to/sessions/

# Custom output directory
python3 process_sessions.py . -o my_reports
```

### Agent Integrations

```bash
# Codex CLI (GPT-5.4) delegations
python3 process_sessions.py . -o reports --codex-dir ~/.codex/

# Qwen CLI parallel activity
python3 process_sessions.py . -o reports --qwen-dir ~/.qwen/

# Pencil (pen.dev) design sessions
python3 process_sessions.py . -o reports --pencil-dir ~/.pencil/

# OpenCode CLI parallel sessions
python3 process_sessions.py . -o reports --opencode-dir ~/.local/share/opencode/

# Antigravity CLI (Google) conversations
python3 process_sessions.py . -o reports --antigravity-dir ~/.gemini/antigravity-cli/

# pi coding agent sessions
python3 process_sessions.py . -o reports --pi-dir ~/.pi/agent/sessions/

# All agents combined
python3 process_sessions.py . -o reports \
  --codex-dir ~/.codex/ --qwen-dir ~/.qwen/ --pencil-dir ~/.pencil/ \
  --opencode-dir ~/.local/share/opencode/ --antigravity-dir ~/.gemini/antigravity-cli/ \
  --pi-dir ~/.pi/agent/sessions/
```

### Additional Options

```bash
# Extract the last 30 conversations
python3 process_sessions.py . -o reports --last 30

# Generate file modification history
python3 process_sessions.py . -o reports --file-history CLAUDE.md

# Skip subagent processing (faster)
python3 process_sessions.py . -o reports --no-subagents
```

## Generated Reports

| Report | Description |
|--------|-------------|
| `00_resumen_sesiones.md` | Session summary with global stats |
| `01_historico_mensajes_usuario.md` | Chronological user message history |
| `02_respuestas_sistema.md` | System responses and confirmations |
| `03_preguntas_respuestas.md` | Structured Q&A pairs |
| `04_operaciones_archivos.md` | All file operations performed |
| `05_qa_mejorado_con_operaciones.md` | **Most valuable** — Q&A with file operations and subagent details |
| `06_subagentes_detalle.md` | Subagent statistics and detail |
| `07_memoria_proyecto.md` | Project memory (decisions, technical lessons) |
| `08_tool_results_externos.md` | External tool results inventory |
| `09_eficiencia_tokens.md` | Token efficiency and consumption analysis |
| `10_codex_integrado.md` | Codex delegations with full detail |
| `11_qwen_paralelo.md` | Qwen parallel activity |
| `12–13` | Pencil design sessions and model usage |
| `14–15` | OpenCode sessions and model usage |
| `16–17` | Antigravity CLI conversations and model usage |
| `18–19` | pi coding agent sessions and model usage |

## Project Attribution

When integrating external agents, each session is attributed to the corresponding Claude project using 3 auditable rules (each session reports which rule matched):

1. **cwd** — Longest common prefix between the agent's working directory and Claude projects
2. **paths** — Voting by file paths referenced in tool calls
3. **time** — Temporal overlap with Claude activity as tiebreaker

## Integration Guides

| Guide | Content |
|-------|---------|
| `CODEX_DATA_GUIDE.md` | Codex CLI data format |
| `PENCIL_DATA_GUIDE.md` | Pencil data format + attribution algorithm |
| `OPENCODE_DATA_GUIDE.md` | OpenCode SQLite format + attribution rules |
| `ANTIGRAVITY_DATA_GUIDE.md` | Antigravity SQLite+protobuf format + attribution rules |
| `PI_DATA_GUIDE.md` | pi JSONL v3 format + attribution rules |
| `HOW_TO_ADD_A_PROVIDER.md` | 6-step checklist to integrate a new tool |

## Tests

```bash
# Run all unit tests
python3 -m unittest discover tests

# Or with pytest
pytest
```

The test suite covers core functionality (Q&A, durations, file splitting) and each integration with its own test class. CI runs on Python 3.8–3.13 × Ubuntu/macOS.

## Built For

Developers, project managers, and teams who:

- Work with multiple AI agents on the same projects
- Need to document AI-assisted development processes
- Want full visibility into what each agent did
- Need automated technical reports
- Want to audit subagent and external agent activity per session

## Version History

- **v5.3** (Current) — pi coding agent integration
- **v5.2** — Antigravity CLI (Google) integration
- **v5.1** — OpenCode CLI integration
- **v5.0** — Pencil (pen.dev) integration
- **v4.1** — Qwen CLI integration
- **v4.0** — Codex CLI (GPT-5.4) integration
- **v3.1** — Token efficiency reporting
- **v3.0** — Subagent processing, project memory, tool-results
- **v2.0** — Auto-split large files, CSV log, temporal filters
- **v1.0** — Base: file extraction, Q&A reports, tool detection

## License

[MIT](LICENSE)
