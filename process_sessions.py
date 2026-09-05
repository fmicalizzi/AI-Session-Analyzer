#!/usr/bin/env python3
"""
Script para procesar archivos JSONL de sesiones de Claude y extraer información clave.
Genera reportes organizados de mensajes, respuestas, operaciones de archivos,
actividad de subagentes y memoria del proyecto.

v4.1 - Integración con Qwen CLI para visibilidad de actividad paralela.
v4.0 - Integración con Codex CLI (GPT-5.4) para enriquecer delegaciones.
v3.0 - Soporte para subagentes, tool-results externos y memoria del proyecto.
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Set, Tuple
import argparse
import re


class SessionProcessor:
    def __init__(self, input_dir: str, output_dir: str = None):
        target = Path(input_dir).expanduser().resolve()
        if target.is_file():
            self.input_file = target
            self.input_dir = target.parent
        else:
            self.input_file = None
            self.input_dir = target

        self.output_dir = Path(output_dir).expanduser().resolve() if output_dir else self.input_dir / "reports"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Almacenamiento de datos procesados (sesiones principales)
        self.user_messages = []
        self.assistant_responses = []
        self.file_operations = []
        self.qa_pairs = []
        self.sessions_summary = []

        # v3.0: Datos de subagentes
        self.subagent_data = []           # Lista de subagentes procesados
        self.subagent_operations = []     # Operaciones de archivos desde subagentes
        self.agent_invocations = []       # Llamadas a Agent tool desde sesiones principales

        # v3.0: Tool results externos
        self.tool_results_data = {}       # {session_id: {filename: content_preview}}

        # v3.0: Memoria del proyecto
        self.memory_data = {}             # {filename: content}

        # v3.0: Mapeo de directorios de sesión
        self.session_dirs = {}            # {session_id: Path}

        # v3.1: Token usage por sesion principal
        self.session_token_usage = {}     # {session_file: {input, output, cache_create, cache_read}}

        # v4.0: Codex integration
        self.codex_dir = None
        self.codex_invocations = []      # Detected codex calls from Claude sessions
        self.codex_matched = {}          # {tool_use_id: parsed_codex_session}

        # v4.1: Qwen integration
        self.qwen_dir = None
        self.qwen_sessions = []  # Parsed Qwen sessions for the same project

    # ========================================================================
    # PROCESAMIENTO PRINCIPAL - Sesiones principales
    # ========================================================================

    def process_jsonl_file(self, file_path: Path) -> Dict[str, Any]:
        """Procesa un archivo JSONL individual"""
        session_data = {
            "file": file_path.name,
            "messages": [],
            "operations": [],
            "start_time": None,
            "end_time": None,
            "total_messages": 0,
            "token_usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation": 0,
                "cache_read": 0
            },
            "models_used": {},       # {model_name: count}
            "_token_by_msg": {},     # {msg_id: usage_dict} dedup por mensaje API
            "_models_by_msg": set()  # msg_ids ya contados para modelos
        }

        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                for line_num, line in enumerate(f, 1):
                    try:
                        data = json.loads(line.strip())
                        if data:
                            self._process_message(data, session_data, line_num)
                    except json.JSONDecodeError as e:
                        print(f"Error parsing line {line_num} in {file_path}: {e}")
                        continue

        except Exception as e:
            print(f"Error processing file {file_path}: {e}")

        # Consolidar token usage desde el dict deduplicado
        for msg_id, usage in session_data['_token_by_msg'].items():
            session_data['token_usage']['input_tokens'] += usage.get('input_tokens', 0)
            session_data['token_usage']['output_tokens'] += usage.get('output_tokens', 0)
            session_data['token_usage']['cache_creation'] += usage.get('cache_creation_input_tokens', 0)
            session_data['token_usage']['cache_read'] += usage.get('cache_read_input_tokens', 0)

        # Limpiar campos internos
        del session_data['_token_by_msg']
        del session_data['_models_by_msg']

        return session_data

    def _process_message(self, data: Dict[str, Any], session_data: Dict[str, Any], line_num: int):
        """Procesa un mensaje individual del JSON"""
        timestamp = data.get('timestamp', '')
        message_type = data.get('type', '')

        # Actualizar tiempos de sesion
        if timestamp:
            if not session_data['start_time'] or timestamp < session_data['start_time']:
                session_data['start_time'] = timestamp
            if not session_data['end_time'] or timestamp > session_data['end_time']:
                session_data['end_time'] = timestamp

        session_data['total_messages'] += 1

        # Procesar segun el tipo de mensaje
        if message_type == 'user':
            self._process_user_message(data, session_data, line_num)
        elif message_type == 'assistant':
            self._process_assistant_message(data, session_data, line_num)

        # Buscar operaciones de archivos en tool results
        self._extract_file_operations(data, session_data, line_num)

    def _process_user_message(self, data: Dict[str, Any], session_data: Dict[str, Any], line_num: int):
        """Procesa mensajes del usuario"""
        message_content = data.get('message', {})
        content = message_content.get('content', '')

        # Si es string directo
        if isinstance(content, str) and content.strip():
            user_msg = {
                'session_file': session_data['file'],
                'session_id': data.get('sessionId', ''),
                'timestamp': data.get('timestamp', ''),
                'line_number': line_num,
                'content': content.strip(),
                'uuid': data.get('uuid', ''),
                'cwd': data.get('cwd', '')
            }
            self.user_messages.append(user_msg)
            session_data['messages'].append(('user', content.strip()[:200] + '...' if len(content) > 200 else content.strip()))

        # Si es lista con objetos (tool_result, etc.)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    if item.get('type') == 'text' and 'text' in item:
                        text_content = item['text'].strip()
                        if text_content and not text_content.startswith('[Request interrupted'):
                            user_msg = {
                                'session_file': session_data['file'],
                                'session_id': data.get('sessionId', ''),
                                'timestamp': data.get('timestamp', ''),
                                'line_number': line_num,
                                'content': text_content,
                                'uuid': data.get('uuid', ''),
                                'cwd': data.get('cwd', '')
                            }
                            self.user_messages.append(user_msg)
                            session_data['messages'].append(('user', text_content[:200] + '...' if len(text_content) > 200 else text_content))

    def _process_assistant_message(self, data: Dict[str, Any], session_data: Dict[str, Any], line_num: int):
        """Procesa mensajes del asistente, incluyendo deteccion de invocaciones Agent"""
        message_content = data.get('message', {})
        content = message_content.get('content', [])

        if not isinstance(content, list):
            return

        text_responses = []
        tool_uses = []

        for item in content:
            if isinstance(item, dict):
                if item.get('type') == 'text':
                    text_content = item.get('text', '').strip()
                    if text_content:
                        text_responses.append(text_content)
                elif item.get('type') == 'tool_use':
                    tool_name = item.get('name', '')
                    tool_input = item.get('input', {})
                    tool_uses.append({
                        'tool': tool_name,
                        'input': tool_input,
                        'id': item.get('id', '')
                    })

                    # v3.0: Registrar invocaciones de Agent tool
                    if tool_name == 'Agent':
                        self.agent_invocations.append({
                            'session_file': session_data['file'],
                            'session_id': data.get('sessionId', ''),
                            'timestamp': data.get('timestamp', ''),
                            'tool_use_id': item.get('id', ''),
                            'prompt': tool_input.get('prompt', '')[:500],
                            'subagent_type': tool_input.get('subagent_type', ''),
                            'description': tool_input.get('description', '')[:200],
                            'run_in_background': tool_input.get('run_in_background', False),
                            'line_number': line_num
                        })

        # v3.1: Registrar token usage deduplicado por message.id
        # Cada API call genera multiples lineas JSONL (una por content block),
        # todas con el mismo message.id pero el output_tokens se actualiza (streaming).
        # Guardamos la ultima ocurrencia de cada msg_id para tener el valor final.
        msg_id = message_content.get('id', '')
        usage = message_content.get('usage', {})
        if msg_id and usage:
            session_data['_token_by_msg'][msg_id] = usage  # overwrite = keep latest

        model = message_content.get('model', '')
        if model and msg_id:
            # Solo contar el modelo una vez por msg_id
            if msg_id not in session_data['_models_by_msg']:
                session_data['_models_by_msg'].add(msg_id)
                session_data['models_used'][model] = session_data['models_used'].get(model, 0) + 1

        # Guardar respuestas de texto
        if text_responses:
            for response in text_responses:
                assistant_resp = {
                    'session_file': session_data['file'],
                    'session_id': data.get('sessionId', ''),
                    'timestamp': data.get('timestamp', ''),
                    'line_number': line_num,
                    'content': response,
                    'uuid': data.get('uuid', ''),
                    'model': message_content.get('model', ''),
                    'stop_reason': message_content.get('stop_reason', '')
                }
                self.assistant_responses.append(assistant_resp)
                session_data['messages'].append(('assistant', response[:200] + '...' if len(response) > 200 else response))

        # Guardar usos de herramientas
        if tool_uses:
            for tool in tool_uses:
                operation = {
                    'session_file': session_data['file'],
                    'session_id': data.get('sessionId', ''),
                    'timestamp': data.get('timestamp', ''),
                    'line_number': line_num,
                    'operation_type': 'tool_use',
                    'tool_name': tool['tool'],
                    'tool_use_id': tool.get('id', ''),
                    'details': self._extract_file_operation_details(tool['tool'], tool['input']),
                    'raw_input': tool['input']
                }
                self.file_operations.append(operation)
                session_data['operations'].append(f"Tool: {tool['tool']}")

    def _extract_file_operations(self, data: Dict[str, Any], session_data: Dict[str, Any], line_num: int):
        """Extrae operaciones de archivos de tool results"""
        tool_use_result = data.get('toolUseResult')
        if tool_use_result:
            if isinstance(tool_use_result, dict):
                # Operaciones de lectura de archivos
                if 'filePath' in tool_use_result or 'file' in tool_use_result:
                    operation = {
                        'session_file': session_data['file'],
                        'session_id': data.get('sessionId', ''),
                        'timestamp': data.get('timestamp', ''),
                        'line_number': line_num,
                        'operation_type': 'file_result',
                        'tool_name': 'file_operation',
                        'details': str(tool_use_result),
                        'raw_input': tool_use_result
                    }
                    self.file_operations.append(operation)

                # Operaciones de terminal/bash
                if 'stdout' in tool_use_result or 'stderr' in tool_use_result:
                    stdout_content = tool_use_result.get('stdout', '')
                    stderr_content = tool_use_result.get('stderr', '')

                    operation_details = self._analyze_bash_operation(stdout_content, stderr_content)

                    operation = {
                        'session_file': session_data['file'],
                        'session_id': data.get('sessionId', ''),
                        'timestamp': data.get('timestamp', ''),
                        'line_number': line_num,
                        'operation_type': operation_details['type'],
                        'tool_name': operation_details['tool'],
                        'details': operation_details['details'],
                        'raw_input': tool_use_result
                    }
                    self.file_operations.append(operation)

    def _analyze_bash_operation(self, stdout: str, stderr: str) -> Dict[str, str]:
        """Analiza operaciones bash para detectar tipos especificos"""
        combined_output = f"{stdout} {stderr}".lower()

        # Detectar operaciones Git
        if any(keyword in combined_output for keyword in ['git commit', 'git add', 'git push', 'git pull', 'git clone', 'git branch']):
            if 'git commit' in combined_output:
                return {'type': 'git_commit', 'tool': 'Git', 'details': 'Git commit operation'}
            elif 'git add' in combined_output:
                return {'type': 'git_add', 'tool': 'Git', 'details': 'Git add operation'}
            elif 'git push' in combined_output:
                return {'type': 'git_push', 'tool': 'Git', 'details': 'Git push operation'}
            elif 'git pull' in combined_output:
                return {'type': 'git_pull', 'tool': 'Git', 'details': 'Git pull operation'}
            elif 'git clone' in combined_output:
                return {'type': 'git_clone', 'tool': 'Git', 'details': 'Git clone operation'}
            elif 'git branch' in combined_output:
                return {'type': 'git_branch', 'tool': 'Git', 'details': 'Git branch operation'}

        # Detectar instalaciones de paquetes
        if any(keyword in combined_output for keyword in ['npm install', 'npm i ', 'yarn install', 'yarn add']):
            if 'npm install' in combined_output or 'npm i ' in combined_output:
                return {'type': 'npm_install', 'tool': 'NPM', 'details': 'NPM package installation'}
            elif 'yarn install' in combined_output or 'yarn add' in combined_output:
                return {'type': 'yarn_install', 'tool': 'Yarn', 'details': 'Yarn package installation'}

        if any(keyword in combined_output for keyword in ['pip install', 'pip3 install', 'poetry install', 'conda install']):
            if 'pip install' in combined_output or 'pip3 install' in combined_output:
                return {'type': 'pip_install', 'tool': 'PIP', 'details': 'Python package installation'}
            elif 'poetry install' in combined_output:
                return {'type': 'poetry_install', 'tool': 'Poetry', 'details': 'Poetry package installation'}
            elif 'conda install' in combined_output:
                return {'type': 'conda_install', 'tool': 'Conda', 'details': 'Conda package installation'}

        # Detectar operaciones de archivos del sistema
        if any(keyword in combined_output for keyword in ['mkdir', 'rmdir', 'rm -rf', 'cp ', 'mv ', 'touch ']):
            if 'mkdir' in combined_output:
                return {'type': 'mkdir', 'tool': 'FileSystem', 'details': 'Directory creation'}
            elif 'rmdir' in combined_output or 'rm -rf' in combined_output:
                return {'type': 'remove_dir', 'tool': 'FileSystem', 'details': 'Directory removal'}
            elif 'cp ' in combined_output:
                return {'type': 'copy_file', 'tool': 'FileSystem', 'details': 'File copy operation'}
            elif 'mv ' in combined_output:
                return {'type': 'move_file', 'tool': 'FileSystem', 'details': 'File move operation'}
            elif 'touch ' in combined_output:
                return {'type': 'create_file', 'tool': 'FileSystem', 'details': 'File creation'}

        # Detectar operaciones de busqueda
        if any(keyword in combined_output for keyword in ['grep ', 'find ', 'locate ', 'rg ']):
            if 'grep ' in combined_output or 'rg ' in combined_output:
                return {'type': 'search_content', 'tool': 'Search', 'details': 'Content search operation'}
            elif 'find ' in combined_output or 'locate ' in combined_output:
                return {'type': 'search_files', 'tool': 'Search', 'details': 'File search operation'}

        # Detectar builds y compilaciones
        if any(keyword in combined_output for keyword in ['npm run build', 'yarn build', 'make ', 'cmake', 'cargo build', 'mvn compile']):
            return {'type': 'build', 'tool': 'Build', 'details': 'Build/compilation operation'}

        # Detectar tests
        if any(keyword in combined_output for keyword in ['npm test', 'yarn test', 'pytest', 'jest', 'mocha', 'cargo test']):
            return {'type': 'test', 'tool': 'Test', 'details': 'Test execution'}

        # Operacion bash generica
        return {'type': 'terminal_result', 'tool': 'Bash', 'details': f"Terminal output: {stdout[:100]}..."}

    def _extract_file_operation_details(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """Extrae detalles legibles de operaciones de archivos"""
        details = []

        tool_mappings = {
            'Read': 'Leer archivo',
            'Edit': 'Editar archivo',
            'Write': 'Escribir archivo',
            'Bash': 'Comando terminal',
            'Glob': 'Buscar archivos',
            'Grep': 'Buscar contenido',
            'Agent': 'Invocar subagente',
            'WebSearch': 'Busqueda web',
            'WebFetch': 'Obtener web',
            'NotebookEdit': 'Editar notebook',
            'mcp__filesystem__read_file': 'Leer archivo',
            'mcp__filesystem__write_file': 'Escribir archivo',
            'mcp__filesystem__edit_file': 'Editar archivo',
            'mcp__filesystem__list_directory': 'Listar directorio',
            'mcp__filesystem__create_directory': 'Crear directorio',
            'mcp__filesystem__move_file': 'Mover archivo'
        }

        operation_name = tool_mappings.get(tool_name, tool_name)
        details.append(f"Operacion: {operation_name}")

        # Extraer archivo/ruta con mejor parsing
        file_path = self._extract_file_path_from_input(tool_input)
        if file_path:
            file_name = self._get_clean_filename(file_path)
            details.append(f"Archivo: {file_name}")

        # Extraer comando si es bash
        if tool_name in ['Bash', 'bash'] and 'command' in tool_input:
            cmd = tool_input['command'][:50] + '...' if len(tool_input['command']) > 50 else tool_input['command']
            details.append(f"Comando: {cmd}")

        # Extraer prompt si es Agent
        if tool_name == 'Agent' and 'prompt' in tool_input:
            prompt_preview = tool_input['prompt'][:80] + '...' if len(tool_input['prompt']) > 80 else tool_input['prompt']
            details.append(f"Tarea: {prompt_preview}")

        # Extraer descripcion si existe
        if 'description' in tool_input:
            desc = tool_input['description'][:50] + '...' if len(tool_input['description']) > 50 else tool_input['description']
            details.append(f"Descripcion: {desc}")

        return ' | '.join(details) if details else str(tool_input)

    def _extract_file_path_from_input(self, tool_input: Dict[str, Any]) -> str:
        """Extrae la ruta del archivo de diversas estructuras de entrada"""
        possible_keys = ['file_path', 'filePath', 'path', 'inputFilePath', 'outputFilePath']

        for key in possible_keys:
            if key in tool_input and tool_input[key]:
                return tool_input[key]

        # Buscar en estructuras anidadas
        if 'file' in tool_input and isinstance(tool_input['file'], dict):
            file_obj = tool_input['file']
            for key in possible_keys:
                if key in file_obj and file_obj[key]:
                    return file_obj[key]

        # Buscar en el texto completo si contiene rutas tipicas
        input_str = str(tool_input)
        path_patterns = [
            r'/[^\'"\s]+\.(?:js|html|css|json|md|py|ts|jsx|tsx|vue|php|txt|svg|png|jpg|jpeg|gif|liquid|rb|yaml|yml|toml|sh)',
            r'[^\'"\s/]+\.(?:js|html|css|json|md|py|ts|jsx|tsx|vue|php|txt|svg|png|jpg|jpeg|gif|liquid|rb|yaml|yml|toml|sh)'
        ]

        for pattern in path_patterns:
            matches = re.findall(pattern, input_str)
            if matches:
                return matches[0]

        return None

    def _get_clean_filename(self, file_path: str) -> str:
        """Extrae un nombre de archivo limpio y legible"""
        if not file_path:
            return "archivo desconocido"

        filename = os.path.basename(file_path)

        # Detectar rutas de proyecto y mostrar ruta relativa corta
        # Buscar patrones comunes de directorio de proyecto
        project_markers = ['theme/', 'src/', 'app/', 'components/', 'pages/', 'sections/',
                           'templates/', 'snippets/', 'assets/', 'config/', 'docs/',
                           'scripts/', 'tests/', 'lib/', 'utils/', 'public/']

        for marker in project_markers:
            if marker in file_path:
                idx = file_path.find(marker)
                relative_path = file_path[idx:]
                path_parts = relative_path.split('/')
                if len(path_parts) > 3:
                    return '.../' + '/'.join(path_parts[-2:])
                return relative_path

        return filename

    def _create_qa_pairs(self):
        """Crea pares de preguntas y respuestas agrupados por sesion"""
        messages_by_session = {}
        for msg in self.user_messages:
            messages_by_session.setdefault(msg['session_file'], []).append(('user', msg))
        for msg in self.assistant_responses:
            messages_by_session.setdefault(msg['session_file'], []).append(('assistant', msg))

        for session_file, s_messages in messages_by_session.items():
            # Ordenar por timestamp de forma segura
            s_messages.sort(key=lambda x: x[1].get('timestamp') or '')

            # Crear pares Q&A para la sesion actual
            current_question = None
            for msg_type, msg in s_messages:
                if msg_type == 'user' and msg['content'].strip():
                    if current_question:
                        self.qa_pairs.append({
                            'session_file': current_question['session_file'],
                            'question_timestamp': current_question['timestamp'],
                            'question': current_question['content'],
                            'answer': 'Sin respuesta registrada',
                            'answer_timestamp': '',
                            'question_line': current_question['line_number'],
                            'answer_line': ''
                        })
                    current_question = msg

                elif msg_type == 'assistant' and current_question and msg['content'].strip():
                    self.qa_pairs.append({
                        'session_file': current_question['session_file'],
                        'question_timestamp': current_question['timestamp'],
                        'question': current_question['content'],
                        'answer': msg['content'],
                        'answer_timestamp': msg['timestamp'],
                        'question_line': current_question['line_number'],
                        'answer_line': msg['line_number']
                    })
                    current_question = None

            if current_question:
                self.qa_pairs.append({
                    'session_file': current_question['session_file'],
                    'question_timestamp': current_question['timestamp'],
                    'question': current_question['content'],
                    'answer': 'Sin respuesta registrada',
                    'answer_timestamp': '',
                    'question_line': current_question['line_number'],
                    'answer_line': ''
                })

        # Ordenar todos los pares Q&A de forma global por timestamp
        self.qa_pairs.sort(key=lambda x: x.get('question_timestamp') or '')

    # ========================================================================
    # v3.0: PROCESAMIENTO DE SUBAGENTES
    # ========================================================================

    def _discover_session_directories(self):
        """Descubre directorios de sesion que contienen subagentes y/o tool-results"""
        for entry in self.input_dir.iterdir():
            if entry.is_dir() and not entry.name.startswith('.') and entry.name not in ('reports', 'memory', 'reportes'):
                # Verificar si parece un UUID de sesion
                if len(entry.name) > 8 and '-' in entry.name:
                    self.session_dirs[entry.name] = entry
                    subagents_dir = entry / 'subagents'
                    tool_results_dir = entry / 'tool-results'
                    if subagents_dir.exists():
                        print(f"  Subagentes encontrados en: {entry.name}")
                    if tool_results_dir.exists():
                        print(f"  Tool-results encontrados en: {entry.name}")

    def _process_all_subagents(self):
        """Procesa todos los subagentes de todas las sesiones"""
        total_subagents = 0

        for session_id, session_dir in self.session_dirs.items():
            subagents_dir = session_dir / 'subagents'
            if not subagents_dir.exists():
                continue

            subagent_files = sorted(subagents_dir.glob('agent-*.jsonl'))
            if not subagent_files:
                continue

            print(f"  Procesando {len(subagent_files)} subagentes de sesion {session_id[:12]}...")

            for sa_file in subagent_files:
                sa_data = self._process_subagent_file(sa_file, session_id)
                if sa_data:
                    self.subagent_data.append(sa_data)
                    total_subagents += 1

        print(f"  Total subagentes procesados: {total_subagents}")

    def _process_subagent_file(self, file_path: Path, session_id: str) -> Optional[Dict[str, Any]]:
        """Procesa un archivo JSONL de subagente individual"""
        filename = file_path.name
        is_compact = 'compact' in filename

        # Extraer agent_id del nombre de archivo
        # Formatos: agent-aa22126.jsonl, agent-acompact-d70276.jsonl
        agent_id_match = re.search(r'agent-a(?:compact-)?([a-f0-9]+)\.jsonl', filename)
        agent_id = agent_id_match.group(1) if agent_id_match else filename.replace('.jsonl', '')

        sa_data = {
            'agent_id': agent_id,
            'filename': filename,
            'session_id': session_id,
            'slug': '',
            'model': '',
            'is_compact': is_compact,
            'start_time': None,
            'end_time': None,
            'total_messages': 0,
            'prompt': '',          # La tarea asignada (primer mensaje user)
            'final_response': '',  # Ultima respuesta de texto
            'tool_uses': [],       # Herramientas usadas por el subagente
            'files_touched': set(),
            'tools_used_counts': {},  # {tool_name: count}
            'token_usage': {
                'input_tokens': 0,
                'output_tokens': 0,
                'cache_creation': 0,
                'cache_read': 0
            },
            '_token_by_msg': {},     # dedup por message.id
            '_seen_msg_ids': set()   # para contar mensajes/modelo una sola vez
        }

        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                first_user_seen = False
                last_text_response = ''

                for line_num, line in enumerate(f, 1):
                    try:
                        data = json.loads(line.strip())
                    except json.JSONDecodeError:
                        continue

                    if not data:
                        continue

                    msg_type = data.get('type', '')
                    timestamp = data.get('timestamp', '')

                    # Extraer metadata del subagente
                    if not sa_data['slug'] and data.get('slug'):
                        sa_data['slug'] = data['slug']
                    if data.get('agentId') and not sa_data['agent_id']:
                        sa_data['agent_id'] = data['agentId']

                    # Actualizar tiempos
                    if timestamp:
                        if not sa_data['start_time'] or timestamp < sa_data['start_time']:
                            sa_data['start_time'] = timestamp
                        if not sa_data['end_time'] or timestamp > sa_data['end_time']:
                            sa_data['end_time'] = timestamp

                    if msg_type == 'user':
                        sa_data['total_messages'] += 1
                        # Capturar el primer mensaje de usuario (la tarea asignada)
                        if not first_user_seen:
                            first_user_seen = True
                            msg_content = data.get('message', {}).get('content', '')
                            if isinstance(msg_content, str):
                                sa_data['prompt'] = msg_content[:1000]
                            elif isinstance(msg_content, list):
                                # Buscar texto en la lista de contenido
                                for item in msg_content:
                                    if isinstance(item, dict) and item.get('type') == 'text':
                                        sa_data['prompt'] = item.get('text', '')[:1000]
                                        break

                    elif msg_type == 'assistant':
                        message = data.get('message', {})
                        msg_id = message.get('id', '')

                        # Contar mensaje y modelo solo una vez por msg_id
                        if msg_id and msg_id not in sa_data['_seen_msg_ids']:
                            sa_data['_seen_msg_ids'].add(msg_id)
                            sa_data['total_messages'] += 1
                            model = message.get('model', '')
                            if model and not sa_data['model']:
                                sa_data['model'] = model
                        elif not msg_id:
                            sa_data['total_messages'] += 1

                        # Registrar token usage deduplicado (overwrite = keep latest por streaming)
                        usage = message.get('usage', {})
                        if msg_id and usage:
                            sa_data['_token_by_msg'][msg_id] = usage

                        # Extraer tool_uses y texto
                        content = message.get('content', [])
                        if isinstance(content, list):
                            for item in content:
                                if isinstance(item, dict):
                                    if item.get('type') == 'text':
                                        text = item.get('text', '').strip()
                                        if text:
                                            last_text_response = text

                                    elif item.get('type') == 'tool_use':
                                        tool_name = item.get('name', '')
                                        tool_input = item.get('input', {})

                                        # Contabilizar herramienta
                                        sa_data['tools_used_counts'][tool_name] = \
                                            sa_data['tools_used_counts'].get(tool_name, 0) + 1

                                        # Registrar la operacion
                                        sa_data['tool_uses'].append({
                                            'tool': tool_name,
                                            'timestamp': timestamp,
                                            'input_preview': str(tool_input)[:200]
                                        })

                                        # Extraer archivos tocados
                                        file_path_found = self._extract_file_path_from_input(tool_input)
                                        if file_path_found:
                                            clean_name = self._get_clean_filename(file_path_found)
                                            sa_data['files_touched'].add(clean_name)

                                        # Registrar como operacion de subagente
                                        self.subagent_operations.append({
                                            'agent_id': agent_id,
                                            'session_id': session_id,
                                            'timestamp': timestamp,
                                            'operation_type': 'tool_use',
                                            'tool_name': tool_name,
                                            'details': self._extract_file_operation_details(tool_name, tool_input),
                                            'raw_input': tool_input
                                        })

                    elif msg_type == 'progress':
                        # Los mensajes de progreso no cuentan como mensajes de conversacion
                        pass

                sa_data['final_response'] = last_text_response[:500]

        except Exception as e:
            print(f"    Error procesando subagente {file_path.name}: {e}")
            return None

        # Consolidar token usage desde el dict deduplicado
        for msg_id, usage in sa_data['_token_by_msg'].items():
            sa_data['token_usage']['input_tokens'] += usage.get('input_tokens', 0)
            sa_data['token_usage']['output_tokens'] += usage.get('output_tokens', 0)
            sa_data['token_usage']['cache_creation'] += usage.get('cache_creation_input_tokens', 0)
            sa_data['token_usage']['cache_read'] += usage.get('cache_read_input_tokens', 0)

        # Limpiar campos internos
        del sa_data['_token_by_msg']
        del sa_data['_seen_msg_ids']

        # Convertir set a list para serializacion
        sa_data['files_touched'] = sorted(sa_data['files_touched'])

        return sa_data if sa_data['total_messages'] > 0 else None

    def _get_subagents_for_qa(self, qa_pair) -> List[Dict[str, Any]]:
        """Encuentra subagentes invocados durante una interaccion Q&A"""
        session_id = qa_pair['session_file'].replace('.jsonl', '')
        q_time = qa_pair['question_timestamp']
        a_time = qa_pair['answer_timestamp'] or q_time

        if not q_time:
            return []

        matched = []
        for sa in self.subagent_data:
            if sa['session_id'] != session_id:
                continue
            if sa['start_time'] and q_time <= sa['start_time'] <= a_time:
                matched.append(sa)

        # Ordenar por start_time
        matched.sort(key=lambda x: x['start_time'] or '')
        return matched

    def _get_subagent_operations_for_qa(self, qa_pair) -> List[Dict[str, Any]]:
        """Obtiene operaciones de subagentes ejecutadas durante un Q&A"""
        session_id = qa_pair['session_file'].replace('.jsonl', '')
        q_time = qa_pair['question_timestamp']
        a_time = qa_pair['answer_timestamp'] or q_time

        if not q_time:
            return []

        return [
            op for op in self.subagent_operations
            if op['session_id'] == session_id
            and op['timestamp']
            and q_time <= op['timestamp'] <= a_time
        ]

    # ========================================================================
    # v3.0: PROCESAMIENTO DE TOOL-RESULTS
    # ========================================================================

    def _process_all_tool_results(self):
        """Lee archivos de tool-results de todas las sesiones"""
        total_files = 0

        for session_id, session_dir in self.session_dirs.items():
            tool_results_dir = session_dir / 'tool-results'
            if not tool_results_dir.exists():
                continue

            self.tool_results_data[session_id] = {}

            for result_file in tool_results_dir.iterdir():
                if result_file.is_file():
                    try:
                        # Leer solo un preview (primeros 2KB) para no saturar memoria
                        with open(result_file, 'r', encoding='utf-8', errors='replace') as f:
                            content = f.read(2048)
                        self.tool_results_data[session_id][result_file.name] = {
                            'content_preview': content,
                            'size_bytes': result_file.stat().st_size,
                            'filename': result_file.name
                        }
                        total_files += 1
                    except Exception:
                        continue

        if total_files > 0:
            print(f"  Tool-results procesados: {total_files} archivos")

    # ========================================================================
    # v3.0: PROCESAMIENTO DE MEMORIA DEL PROYECTO
    # ========================================================================

    def _process_memory(self):
        """Lee la carpeta memory/ del proyecto"""
        memory_dir = self.input_dir / 'memory'
        if not memory_dir.exists():
            return

        print("  Procesando carpeta memory/...")

        for md_file in sorted(memory_dir.glob('*.md')):
            try:
                with open(md_file, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                self.memory_data[md_file.name] = content
            except Exception as e:
                print(f"    Error leyendo {md_file.name}: {e}")

        if self.memory_data:
            print(f"  Archivos de memoria procesados: {len(self.memory_data)}")

    # ========================================================================
    # v4.0: CODEX INTEGRATION
    # ========================================================================

    def _detect_codex_invocations(self):
        """Detect all Codex delegations from Claude session data."""
        # Scan agent_invocations for codex:* subagent_type
        for inv in self.agent_invocations:
            if 'codex' in inv.get('subagent_type', '').lower():
                self.codex_invocations.append({
                    'source': 'agent',
                    'session_file': inv['session_file'],
                    'timestamp': inv['timestamp'],
                    'tool_use_id': inv['tool_use_id'],
                    'prompt': inv['prompt'],
                    'description': inv['description'],
                    'line_number': inv['line_number'],
                })

        # Scan file_operations for Skill codex:* and Bash codex-companion
        for op in self.file_operations:
            if op.get('operation_type') != 'tool_use':
                continue
            raw = op.get('raw_input', {})
            tool_name = op.get('tool_name', '')

            if tool_name == 'Skill' and 'codex' in str(raw.get('skill', '')).lower():
                self.codex_invocations.append({
                    'source': 'skill',
                    'session_file': op['session_file'],
                    'timestamp': op['timestamp'],
                    'tool_use_id': op.get('tool_use_id') or raw.get('id', ''),
                    'prompt': str(raw.get('args', '')),
                    'description': f"Skill: {raw.get('skill', '')}",
                    'line_number': op['line_number'],
                })
            elif tool_name in ('Bash', 'bash') and 'codex-companion' in str(raw.get('command', '')).lower():
                self.codex_invocations.append({
                    'source': 'bash',
                    'session_file': op['session_file'],
                    'timestamp': op['timestamp'],
                    'tool_use_id': op.get('tool_use_id') or raw.get('id', ''),
                    'prompt': str(raw.get('command', ''))[:300],
                    'description': 'Bash: codex-companion.mjs',
                    'line_number': op['line_number'],
                })

        if self.codex_invocations:
            print(f"  Invocaciones a Codex detectadas: {len(self.codex_invocations)}")

    def _load_and_match_codex(self, codex_dir: str):
        """Load Codex session data and match to detected invocations."""
        import sqlite3
        codex_path = Path(codex_dir).expanduser().resolve()

        if not self.codex_invocations:
            print("  No hay invocaciones a Codex para matchear.")
            return

        # Load threads from state_5.sqlite
        state_db = codex_path / "state_5.sqlite"
        if not state_db.exists():
            print(f"  WARN: {state_db} no encontrado")
            return

        conn = sqlite3.connect(str(state_db))
        conn.row_factory = sqlite3.Row
        threads = conn.execute("""
            SELECT id, title, first_user_message, cwd, tokens_used,
                   created_at, updated_at, model, cli_version
            FROM threads
            WHERE source = 'vscode' OR tokens_used > 1000
            ORDER BY created_at
        """).fetchall()
        threads = [dict(r) for r in threads]
        conn.close()

        # Load session_index for thread names
        session_index = {}
        idx_file = codex_path / "session_index.jsonl"
        if idx_file.exists():
            with open(idx_file, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        session_index[data['id']] = data.get('thread_name', '')
                    except:
                        pass

        # Enrich threads with names
        for t in threads:
            t['thread_name'] = session_index.get(t['id'], '')

        print(f"  Threads de Codex cargados: {len(threads)}")

        # Build CWD map for Claude sessions (for project matching)
        session_cwds = {}
        for jsonl_file in self.input_dir.glob("*.jsonl"):
            try:
                with open(jsonl_file, 'r', encoding='utf-8', errors='replace') as f:
                    for line in f:
                        try:
                            data = json.loads(line.strip())
                            cwd = data.get('cwd', '')
                            if cwd:
                                session_cwds[jsonl_file.name] = cwd
                                break
                        except:
                            continue
            except:
                pass

        # Match each invocation to a Codex thread using 3 criteria:
        # 1. Timestamp proximity (±120s)
        # 2. Project/CWD overlap
        # 3. Prompt text overlap
        matched_count = 0
        for inv in self.codex_invocations:
            # Only match Agent calls (not Skill/Bash which are intermediate steps)
            if inv['source'] != 'agent':
                continue

            inv_ts = inv['timestamp']
            if not inv_ts:
                continue

            try:
                inv_dt = datetime.fromisoformat(inv_ts.replace('Z', '+00:00'))
            except:
                continue

            # Get CWD of the Claude session that made this invocation
            claude_cwd = session_cwds.get(inv['session_file'], '')
            claude_project = Path(claude_cwd).name if claude_cwd else ''

            # Find candidate threads within 120s
            candidates = []
            for t in threads:
                try:
                    from datetime import timezone as tz
                    t_dt = datetime.fromtimestamp(t['created_at'], tz=tz.utc)
                    diff = abs((t_dt - inv_dt).total_seconds())
                    if diff < 120:
                        candidates.append((diff, t))
                except:
                    continue

            if not candidates:
                continue

            # Score candidates: lower is better
            scored = []
            inv_prompt = inv.get('prompt', '').lower()
            for diff, t in candidates:
                score = diff  # base: temporal distance

                # Bonus: project/CWD match (-50 points)
                codex_project = Path(t.get('cwd', '')).name if t.get('cwd') else ''
                if claude_project and codex_project and claude_project == codex_project:
                    score -= 50
                elif claude_project and codex_project and claude_project != codex_project:
                    score += 200  # heavy penalty for project mismatch

                # Bonus: prompt text overlap (-30 points)
                codex_title = (t.get('title', '') or t.get('first_user_message', '')).lower()
                if inv_prompt and codex_title:
                    # Check if significant words from Claude prompt appear in Codex title
                    prompt_words = set(w for w in inv_prompt.split() if len(w) > 4)
                    title_words = set(w for w in codex_title.split() if len(w) > 4)
                    overlap = len(prompt_words & title_words)
                    if overlap >= 3:
                        score -= 30
                    elif overlap >= 1:
                        score -= 10

                scored.append((score, diff, t))

            scored.sort(key=lambda x: x[0])
            best_score, best_diff, best_thread = scored[0]

            # Reject if best candidate is from a different project (score > 150)
            codex_project = Path(best_thread.get('cwd', '')).name if best_thread.get('cwd') else ''
            if best_score > 150:
                print(f"    Skip: {inv['tool_use_id'][:15]} — best candidate is {codex_project} "
                      f"(Claude is {claude_project}, score={best_score:.0f})")
                continue

            # Find and parse rollout file
            sessions_dir = codex_path / "sessions"
            rollout = self._find_and_parse_codex_rollout(sessions_dir, best_thread['id'])

            if rollout:
                self.codex_matched[inv['tool_use_id']] = {
                    'thread_id': best_thread['id'],
                    'thread_name': best_thread.get('thread_name', ''),
                    'title': best_thread.get('title', ''),
                    'cwd': best_thread.get('cwd', ''),
                    'tokens_used': best_thread.get('tokens_used', 0),
                    'model': best_thread.get('model', 'gpt-5.4'),
                    'match_diff_seconds': best_diff,
                    'match_score': best_score,
                    'match_project': codex_project,
                    'claude_project': claude_project,
                    'rollout': rollout,
                    'invocation': inv,
                }
                matched_count += 1
                print(f"    Match: {inv['tool_use_id'][:15]} → Codex {best_thread['id'][:11]} "
                      f"({best_diff:.0f}s, {codex_project}, score={best_score:.0f}, "
                      f"{best_thread.get('tokens_used', 0):,} tokens)")

        print(f"  Sesiones de Codex matcheadas: {matched_count}/{len([i for i in self.codex_invocations if i['source'] == 'agent'])}")

    def _find_and_parse_codex_rollout(self, sessions_dir: Path, thread_id: str) -> Optional[Dict]:
        """Find and parse a Codex rollout JSONL file."""
        if not sessions_dir.exists():
            return None

        # Find the rollout file
        rollout_file = None
        for f in sessions_dir.rglob("rollout-*.jsonl"):
            if thread_id in f.name:
                rollout_file = f
                break

        if not rollout_file:
            return None

        return self._parse_codex_rollout(rollout_file)

    def _parse_codex_rollout(self, path: Path) -> Optional[Dict]:
        """Parse a Codex rollout JSONL into structured data."""
        result = {
            'file': str(path),
            'user_inputs': [],
            'reasoning': [],
            'function_calls': [],
            'assistant_messages': [],
            'first_ts': None,
            'last_ts': None,
            'duration_str': '',
        }

        call_id_map = {}

        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except:
                        continue

                    ts = data.get('timestamp', '')
                    etype = data.get('type', '')
                    payload = data.get('payload', {})

                    if ts:
                        if result['first_ts'] is None or ts < result['first_ts']:
                            result['first_ts'] = ts
                        if result['last_ts'] is None or ts > result['last_ts']:
                            result['last_ts'] = ts

                    if etype != 'response_item':
                        continue

                    ptype = payload.get('type', '')
                    role = payload.get('role', '')
                    content = payload.get('content')

                    if ptype == 'message' and role == 'user':
                        texts = []
                        if content and isinstance(content, list):
                            for c in content:
                                if c.get('type') == 'input_text':
                                    texts.append(c.get('text', ''))
                        if texts:
                            result['user_inputs'].append({'ts': ts, 'texts': texts})

                    elif ptype == 'message' and role == 'assistant':
                        texts = []
                        if content and isinstance(content, list):
                            for c in content:
                                if c.get('type') == 'output_text':
                                    texts.append(c.get('text', ''))
                        if texts:
                            result['assistant_messages'].append({'ts': ts, 'texts': texts})

                    elif ptype == 'reasoning':
                        summary = payload.get('summary', '')
                        if isinstance(summary, list):
                            summary = ' '.join(str(s) for s in summary if s)
                        if summary:
                            result['reasoning'].append({'ts': ts, 'summary': summary})

                    elif ptype == 'function_call':
                        name = payload.get('name', '')
                        args_raw = payload.get('arguments', '')
                        call_id = payload.get('call_id', '')
                        args = {}
                        try:
                            args = json.loads(args_raw) if args_raw else {}
                        except:
                            args = {'raw': args_raw}
                        entry = {
                            'ts': ts, 'name': name, 'call_id': call_id,
                            'args': args, 'output': None,
                        }
                        call_id_map[call_id] = len(result['function_calls'])
                        result['function_calls'].append(entry)

                    elif ptype == 'function_call_output':
                        call_id = payload.get('call_id', '')
                        output = payload.get('output', '')
                        if call_id in call_id_map:
                            result['function_calls'][call_id_map[call_id]]['output'] = output

        except Exception as e:
            print(f"    Error parseando rollout {path.name}: {e}")
            return None

        # Calculate duration
        if result['first_ts'] and result['last_ts']:
            try:
                t1 = datetime.fromisoformat(result['first_ts'].replace('Z', '+00:00'))
                t2 = datetime.fromisoformat(result['last_ts'].replace('Z', '+00:00'))
                diff = (t2 - t1).total_seconds()
                mins = int(diff) // 60
                secs = int(diff) % 60
                result['duration_str'] = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
            except:
                pass

        return result

    def _get_codex_for_qa(self, qa_pair) -> List[Dict]:
        """Find Codex sessions that were invoked during a Q&A interaction."""
        q_time = qa_pair['question_timestamp']
        a_time = qa_pair['answer_timestamp'] or q_time
        if not q_time:
            return []

        matched = []
        for tool_use_id, codex_session in self.codex_matched.items():
            inv = codex_session['invocation']
            inv_ts = inv['timestamp']
            if inv_ts and q_time <= inv_ts <= (a_time or q_time):
                matched.append(codex_session)
            # Also check if the invocation is in the same session and close in time
            elif inv_ts and inv['session_file'] == qa_pair['session_file']:
                try:
                    q_dt = datetime.fromisoformat(q_time.replace('Z', '+00:00'))
                    inv_dt = datetime.fromisoformat(inv_ts.replace('Z', '+00:00'))
                    if abs((inv_dt - q_dt).total_seconds()) < 300:  # within 5 min
                        matched.append(codex_session)
                except:
                    pass

        return matched

    # ========================================================================
    # v4.1: QWEN INTEGRATION
    # ========================================================================

    def _load_qwen_sessions(self, qwen_dir: str):
        """Load and parse Qwen sessions for the same project."""
        import ast
        qwen_path = Path(qwen_dir).expanduser().resolve()
        projects_dir = qwen_path / "projects"
        if not projects_dir.exists():
            print(f"  WARN: {projects_dir} no encontrado")
            return

        # Get CWD from Claude sessions to find matching Qwen project
        claude_cwd = None
        for jsonl_file in self.input_dir.glob("*.jsonl"):
            try:
                with open(jsonl_file, 'r', encoding='utf-8', errors='replace') as f:
                    for line in f:
                        try:
                            data = json.loads(line.strip())
                            cwd = data.get('cwd', '')
                            if cwd:
                                claude_cwd = cwd
                                break
                        except:
                            continue
                if claude_cwd:
                    break
            except:
                pass

        if not claude_cwd:
            print("  No se pudo determinar el CWD del proyecto Claude")
            return

        # Encode CWD to match Qwen's project folder naming
        encoded = claude_cwd.replace('\\', '-').replace('/', '-')
        if encoded.startswith('-'):
            pass  # Keep leading dash
        else:
            encoded = '-' + encoded

        qwen_project_dir = projects_dir / encoded / "chats"
        if not qwen_project_dir.exists():
            print(f"  No se encontraron sesiones de Qwen para este proyecto")
            print(f"    Buscado en: {qwen_project_dir}")
            return

        chat_files = sorted(qwen_project_dir.glob("*.jsonl"))
        if not chat_files:
            print(f"  Directorio de chats Qwen vacío")
            return

        print(f"  Sesiones de Qwen encontradas: {len(chat_files)}")

        for chat_file in chat_files:
            session = self._parse_qwen_session(chat_file)
            if session and session['user_messages']:
                self.qwen_sessions.append(session)
                print(f"    {chat_file.name[:12]}... | {session['start_time'][:10] if session['start_time'] else '?'} | "
                      f"{len(session['user_messages'])} msgs, {len(session['tool_calls'])} tools, "
                      f"{len(session['assistant_responses'])} responses")

        print(f"  Sesiones de Qwen con contenido: {len(self.qwen_sessions)}")

    def _parse_qwen_session(self, file_path: Path) -> Optional[Dict]:
        """Parse a single Qwen chat JSONL file."""
        import ast

        session = {
            'file': file_path.name,
            'session_id': file_path.stem,
            'start_time': None,
            'end_time': None,
            'cwd': '',
            'model': '',
            'git_branch': '',
            'user_messages': [],
            'assistant_responses': [],
            'tool_calls': [],
            'tool_results': [],
            'total_lines': 0,
        }

        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except:
                        continue

                    session['total_lines'] += 1
                    dtype = data.get('type', '')
                    timestamp = data.get('timestamp', '')

                    # Track times
                    if timestamp:
                        if not session['start_time'] or timestamp < session['start_time']:
                            session['start_time'] = timestamp
                        if not session['end_time'] or timestamp > session['end_time']:
                            session['end_time'] = timestamp

                    # Track metadata
                    if not session['cwd'] and data.get('cwd'):
                        session['cwd'] = data['cwd']
                    if not session['model'] and data.get('model'):
                        session['model'] = data['model']
                    if not session['git_branch'] and data.get('gitBranch'):
                        session['git_branch'] = data['gitBranch']

                    # Skip system/telemetry
                    if dtype == 'system':
                        continue

                    # Parse message (can be dict or string repr of dict)
                    msg = data.get('message', {})
                    if isinstance(msg, str):
                        try:
                            msg = ast.literal_eval(msg)
                        except:
                            continue

                    parts = msg.get('parts', [])
                    if not isinstance(parts, list):
                        continue

                    if dtype == 'user':
                        for part in parts:
                            if isinstance(part, dict) and 'text' in part:
                                text = part['text'].strip()
                                if text:
                                    session['user_messages'].append({
                                        'timestamp': timestamp,
                                        'content': text,
                                    })

                    elif dtype == 'assistant':
                        texts = []
                        calls = []
                        for part in parts:
                            if not isinstance(part, dict):
                                continue
                            if 'text' in part:
                                text = part['text'].strip()
                                if text:
                                    texts.append(text)
                            elif 'functionCall' in part:
                                fc = part['functionCall']
                                args = fc.get('args', {})
                                calls.append({
                                    'timestamp': timestamp,
                                    'id': fc.get('id', ''),
                                    'name': fc.get('name', ''),
                                    'command': args.get('command', ''),
                                    'description': args.get('description', ''),
                                })

                        if texts:
                            session['assistant_responses'].append({
                                'timestamp': timestamp,
                                'model': data.get('model', ''),
                                'texts': texts,
                            })
                        if calls:
                            session['tool_calls'].extend(calls)

                    elif dtype == 'tool_result':
                        for part in parts:
                            if isinstance(part, dict) and 'functionResponse' in part:
                                fr = part['functionResponse']
                                output = fr.get('response', {}).get('output', '')
                                session['tool_results'].append({
                                    'timestamp': timestamp,
                                    'id': fr.get('id', ''),
                                    'name': fr.get('name', ''),
                                    'output': output[:500] if output else '',
                                })

        except Exception as e:
            print(f"    Error parseando {file_path.name}: {e}")
            return None

        return session

    # ========================================================================
    # GENERACION DE REPORTES
    # ========================================================================

    def generate_reports(self):
        """Genera todos los reportes"""
        print(f"Generando reportes en: {self.output_dir}")

        # Reportes existentes
        self._generate_sessions_summary()
        self._generate_user_messages_report()
        self._generate_system_responses_report()
        self._generate_qa_report()
        self._generate_file_operations_report()
        self._generate_enhanced_qa_report()
        self._generate_operations_log()

        # v3.0: Nuevos reportes
        if self.subagent_data:
            self._generate_subagents_report()
        if self.memory_data:
            self._generate_memory_report()
        if self.tool_results_data:
            self._generate_tool_results_report()

        # v3.1: Reporte de eficiencia y consumo de tokens
        self._generate_efficiency_report()

        # v4.0: Reporte integrado de Codex
        if self.codex_matched:
            self._generate_codex_integrated_report()

        # v4.1: Reporte paralelo de Qwen
        if self.qwen_sessions:
            self._generate_qwen_parallel_report()

        print(f"Reportes generados exitosamente en {self.output_dir}")
        print(f"{len(os.listdir(self.output_dir))} archivos creados")

    def _generate_sessions_summary(self):
        """Genera resumen de todas las sesiones, incluyendo estadisticas de subagentes"""
        output_file = self.output_dir / "00_resumen_sesiones.md"

        content = []
        content.append("# Resumen de Sesiones Procesadas\n\n")
        content.append(f"**Fecha de procesamiento:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        content.append("## Estadisticas Generales\n\n")
        content.append(f"- **Total de mensajes de usuario:** {len(self.user_messages)}\n")
        content.append(f"- **Total de respuestas del sistema:** {len(self.assistant_responses)}\n")
        content.append(f"- **Total de pares Q&A:** {len(self.qa_pairs)}\n")
        content.append(f"- **Total de operaciones de archivos:** {len(self.file_operations)}\n")
        content.append(f"- **Total de sesiones:** {len(self.sessions_summary)}\n")

        # v3.0: Estadisticas de subagentes
        if self.subagent_data:
            content.append(f"- **Total de subagentes:** {len(self.subagent_data)}\n")
            content.append(f"- **Operaciones de subagentes:** {len(self.subagent_operations)}\n")
            content.append(f"- **Invocaciones Agent en sesiones principales:** {len(self.agent_invocations)}\n")

        # v3.0: Estadisticas de tool-results
        total_tr = sum(len(files) for files in self.tool_results_data.values())
        if total_tr > 0:
            content.append(f"- **Archivos tool-results:** {total_tr}\n")

        if self.memory_data:
            content.append(f"- **Archivos de memoria:** {len(self.memory_data)}\n")

        # v4.0: Codex stats
        if self.codex_invocations:
            content.append(f"\n### Codex (GPT-5.4)\n\n")
            content.append(f"- **Invocaciones a Codex:** {len(self.codex_invocations)}\n")
            content.append(f"- **Sesiones matcheadas:** {len(self.codex_matched)}\n")
            total_codex_tokens = sum(cs['tokens_used'] for cs in self.codex_matched.values())
            total_codex_cmds = sum(len(cs['rollout']['function_calls']) for cs in self.codex_matched.values())
            content.append(f"- **Tokens Codex:** {total_codex_tokens:,}\n")
            content.append(f"- **Comandos Codex:** {total_codex_cmds}\n")

        # v4.1: Qwen stats
        if self.qwen_sessions:
            content.append(f"\n### Qwen CLI\n\n")
            content.append(f"- **Sesiones de Qwen:** {len(self.qwen_sessions)}\n")
            total_qwen_msgs = sum(len(s['user_messages']) for s in self.qwen_sessions)
            total_qwen_tools = sum(len(s['tool_calls']) for s in self.qwen_sessions)
            content.append(f"- **Mensajes Qwen:** {total_qwen_msgs}\n")
            content.append(f"- **Comandos Qwen:** {total_qwen_tools}\n")

        content.append("\n")

        content.append("## Archivos Procesados\n\n")
        for session in self.sessions_summary:
            content.append(f"### {session['file']}\n")
            content.append(f"- **Inicio:** {session['start_time']}\n")
            content.append(f"- **Fin:** {session['end_time']}\n")
            content.append(f"- **Total mensajes:** {session['total_messages']}\n")
            content.append(f"- **Operaciones:** {len(session['operations'])}\n")

            # v3.0: Contar subagentes de esta sesion
            session_id = session['file'].replace('.jsonl', '')
            session_subagents = [sa for sa in self.subagent_data if sa['session_id'] == session_id]
            if session_subagents:
                content.append(f"- **Subagentes:** {len(session_subagents)}\n")

            # v3.1: Token usage de la sesion
            tu = session.get('token_usage', {})
            total_tokens = tu.get('input_tokens', 0) + tu.get('output_tokens', 0)
            if total_tokens > 0:
                content.append(f"- **Tokens:** input: {tu['input_tokens']:,} | output: {tu['output_tokens']:,} | cache_create: {tu['cache_creation']:,} | cache_read: {tu['cache_read']:,}\n")
                # Modelo principal
                models = session.get('models_used', {})
                if models:
                    top_model = max(models.items(), key=lambda x: x[1])
                    content.append(f"- **Modelo principal:** {top_model[0]} ({top_model[1]} respuestas)\n")

            content.append("\n")

        content.append("## Herramientas Mas Utilizadas\n\n")
        tool_counts = {}
        for op in self.file_operations:
            tool = op['tool_name']
            tool_counts[tool] = tool_counts.get(tool, 0) + 1

        for tool, count in sorted(tool_counts.items(), key=lambda x: x[1], reverse=True):
            content.append(f"- **{tool}:** {count} usos\n")

        # v3.0: Herramientas de subagentes
        if self.subagent_data:
            content.append("\n## Herramientas de Subagentes\n\n")
            sa_tool_counts = {}
            for sa in self.subagent_data:
                for tool, count in sa['tools_used_counts'].items():
                    sa_tool_counts[tool] = sa_tool_counts.get(tool, 0) + count

            for tool, count in sorted(sa_tool_counts.items(), key=lambda x: x[1], reverse=True):
                content.append(f"- **{tool}:** {count} usos\n")

            # Modelos de subagentes
            content.append("\n## Modelos de Subagentes\n\n")
            model_counts = {}
            for sa in self.subagent_data:
                model = sa['model'] or 'desconocido'
                model_counts[model] = model_counts.get(model, 0) + 1
            for model, count in sorted(model_counts.items(), key=lambda x: x[1], reverse=True):
                content.append(f"- **{model}:** {count} subagentes\n")

            # Token usage totales
            content.append("\n## Uso de Tokens (Subagentes)\n\n")
            total_input = sum(sa['token_usage']['input_tokens'] for sa in self.subagent_data)
            total_output = sum(sa['token_usage']['output_tokens'] for sa in self.subagent_data)
            total_cache_create = sum(sa['token_usage']['cache_creation'] for sa in self.subagent_data)
            total_cache_read = sum(sa['token_usage']['cache_read'] for sa in self.subagent_data)
            content.append(f"- **Input tokens:** {total_input:,}\n")
            content.append(f"- **Output tokens:** {total_output:,}\n")
            content.append(f"- **Cache creation tokens:** {total_cache_create:,}\n")
            content.append(f"- **Cache read tokens:** {total_cache_read:,}\n")

        # v3.0: Resumen de sesiones con subagentes
        if self.session_dirs:
            content.append("\n## Directorios de Sesion Detectados\n\n")
            for sid, sdir in sorted(self.session_dirs.items()):
                has_subs = (sdir / 'subagents').exists()
                has_tr = (sdir / 'tool-results').exists()
                has_jsonl = (self.input_dir / f"{sid}.jsonl").exists()
                flags = []
                if has_jsonl:
                    flags.append("JSONL")
                if has_subs:
                    n = len([sa for sa in self.subagent_data if sa['session_id'] == sid])
                    flags.append(f"subagentes:{n}")
                if has_tr:
                    n = len(self.tool_results_data.get(sid, {}))
                    flags.append(f"tool-results:{n}")
                content.append(f"- `{sid[:12]}...` [{', '.join(flags)}]\n")

        full_content = ''.join(content)
        self._split_large_file(output_file, full_content)

    def _generate_user_messages_report(self):
        """Genera reporte de mensajes del usuario"""
        output_file = self.output_dir / "01_historico_mensajes_usuario.md"

        content = []
        content.append("# Historico de Mensajes del Usuario\n\n")
        content.append(f"Total de mensajes: {len(self.user_messages)}\n\n")
        content.append("---\n\n")

        for i, msg in enumerate(self.user_messages, 1):
            content.append(f"## Mensaje #{i}\n\n")
            content.append(f"**Archivo de sesion:** {msg['session_file']}\n")
            content.append(f"**Timestamp:** {msg['timestamp']}\n")
            content.append(f"**Linea:** {msg['line_number']}\n")
            content.append(f"**Directorio:** {msg['cwd']}\n\n")
            content.append("**Contenido:**\n")
            content.append(f"```\n{msg['content']}\n```\n\n")
            content.append("---\n\n")

        full_content = ''.join(content)
        self._split_large_file(output_file, full_content)

    def _generate_system_responses_report(self):
        """Genera reporte de respuestas del sistema"""
        output_file = self.output_dir / "02_respuestas_sistema.md"

        content = []
        content.append("# Respuestas del Sistema\n\n")
        content.append(f"Total de respuestas: {len(self.assistant_responses)}\n\n")
        content.append("---\n\n")

        for i, resp in enumerate(self.assistant_responses, 1):
            content.append(f"## Respuesta #{i}\n\n")
            content.append(f"**Archivo de sesion:** {resp['session_file']}\n")
            content.append(f"**Timestamp:** {resp['timestamp']}\n")
            content.append(f"**Linea:** {resp['line_number']}\n")
            content.append(f"**Modelo:** {resp['model']}\n")
            content.append(f"**Razon de parada:** {resp['stop_reason']}\n\n")
            content.append("**Contenido:**\n")
            content.append(f"```\n{resp['content']}\n```\n\n")
            content.append("---\n\n")

        full_content = ''.join(content)
        self._split_large_file(output_file, full_content)

    def _generate_qa_report(self):
        """Genera reporte de pares pregunta-respuesta"""
        output_file = self.output_dir / "03_preguntas_respuestas.md"

        content = []
        content.append("# Pares de Preguntas y Respuestas\n\n")
        content.append(f"Total de pares Q&A: {len(self.qa_pairs)}\n\n")
        content.append("---\n\n")

        for i, qa in enumerate(self.qa_pairs, 1):
            content.append(f"## Q&A #{i}\n\n")
            content.append(f"**Archivo de sesion:** {qa['session_file']}\n")
            content.append(f"**Timestamp pregunta:** {qa['question_timestamp']}\n")
            content.append(f"**Timestamp respuesta:** {qa['answer_timestamp']}\n\n")

            content.append("### Pregunta:\n")
            content.append(f"```\n{qa['question']}\n```\n\n")

            content.append("### Respuesta:\n")
            content.append(f"```\n{qa['answer']}\n```\n\n")
            content.append("---\n\n")

        full_content = ''.join(content)
        self._split_large_file(output_file, full_content)

    def _generate_file_operations_report(self):
        """Genera reporte simple de operaciones de archivos"""
        output_file = self.output_dir / "04_operaciones_archivos.md"

        content = []
        content.append("# Operaciones de Archivos\n\n")
        content.append(f"Total de operaciones (sesion principal): {len(self.file_operations)}\n")
        if self.subagent_operations:
            content.append(f"Total de operaciones (subagentes): {len(self.subagent_operations)}\n")
        content.append("\nFormato: Operacion | Archivo | Herramienta\n\n")
        content.append("---\n\n")

        content.append("## Operaciones de Sesiones Principales\n\n")
        for i, op in enumerate(self.file_operations, 1):
            content.append(f"{i}. {op['details']} | {op['tool_name']} | {op['session_file']} | Linea {op['line_number']}\n")

        if self.subagent_operations:
            content.append(f"\n## Operaciones de Subagentes ({len(self.subagent_operations)} total)\n\n")
            for i, op in enumerate(self.subagent_operations, 1):
                content.append(f"{i}. [{op['agent_id'][:8]}] {op['details']} | {op['tool_name']}\n")

        full_content = ''.join(content)
        self._split_large_file(output_file, full_content)

    def _render_qa_operations_section(self, qa, content):
        """Renderiza la seccion de operaciones de archivos para un Q&A (usado por reportes 05 y ultimas N)"""
        operations_in_timeframe = self._get_operations_between_qa(qa)

        if operations_in_timeframe:
            content.append("### Operaciones de Archivos Ejecutadas:\n")
            content.append(f"*Se ejecutaron {len(operations_in_timeframe)} operaciones durante esta interaccion:*\n\n")

            operation_summary = {}
            files_touched = set()
            tools_used = set()

            for op in operations_in_timeframe:
                tool = op['tool_name']
                tools_used.add(tool)
                if tool not in operation_summary:
                    operation_summary[tool] = []
                operation_summary[tool].append(op)

                file_path = self._extract_file_path_from_input(op.get('raw_input', {}))
                if file_path:
                    clean_filename = self._get_clean_filename(file_path)
                    files_touched.add(clean_filename)

                details = op.get('details', '')
                if 'Archivo:' in details:
                    filename_part = details.split('Archivo:')[1].split('|')[0].strip()
                    if filename_part and filename_part != 'archivo desconocido':
                        files_touched.add(filename_part)

            content.append("**Resumen:**\n")
            content.append(f"- **Herramientas utilizadas:** {', '.join(sorted(tools_used))}\n")
            if files_touched:
                clean_files = [f for f in files_touched if f and f != 'archivo desconocido' and len(f) > 1]
                if clean_files:
                    content.append(f"- **Archivos tocados:** {', '.join(sorted(clean_files))}\n")
            content.append(f"- **Total de operaciones:** {len(operations_in_timeframe)}\n\n")

            content.append("**Detalle por herramienta:**\n")
            for tool, ops in operation_summary.items():
                content.append(f"- **{tool}** ({len(ops)} operaciones)\n")
                for j, op in enumerate(ops[:3]):
                    detail = op['details']
                    if len(detail) > 100:
                        detail = detail[:100] + '...'
                    if any(marker in detail for marker in ('/Users/', '/home/', ':\\', ':/', '/root/')) and len(detail) > 80:
                        file_path = self._extract_file_path_from_input(op.get('raw_input', {}))
                        if file_path:
                            clean_name = self._get_clean_filename(file_path)
                            operation_type = detail.split('|')[0] if '|' in detail else detail.split(':')[0]
                            detail = f"{operation_type} | Archivo: {clean_name}"
                    content.append(f"  - {detail}\n")
                if len(ops) > 3:
                    content.append(f"  - *(y {len(ops) - 3} operaciones mas...)*\n")
            content.append("\n")
        else:
            content.append("### Operaciones de Archivos:\n")
            content.append("*No se registraron operaciones de archivos especificas durante esta interaccion.*\n\n")

    def _render_qa_subagents_section(self, qa, content):
        """Renderiza la seccion de subagentes para un Q&A"""
        subagents = self._get_subagents_for_qa(qa)
        if not subagents:
            return

        content.append(f"### Subagentes Invocados ({len(subagents)}):\n\n")

        for sa in subagents:
            slug_display = sa['slug'] or sa['agent_id'][:12]
            model_short = sa['model'].split('-20')[0] if '-20' in sa['model'] else sa['model']
            duration = self._calculate_interaction_duration(sa['start_time'], sa['end_time'])

            content.append(f"#### Subagente: {slug_display}\n")
            content.append(f"- **Modelo:** {model_short}")
            if duration:
                content.append(f" | **Duracion:** {duration}")
            content.append(f" | **Mensajes:** {sa['total_messages']}\n")

            if sa.get('is_compact'):
                content.append("- *(sesion compactada)*\n")

            # Tarea asignada
            if sa['prompt']:
                prompt_preview = sa['prompt'][:300] + '...' if len(sa['prompt']) > 300 else sa['prompt']
                content.append(f"- **Tarea:** {prompt_preview}\n")

            # Herramientas usadas
            if sa['tools_used_counts']:
                tools_str = ', '.join(f"{t} ({c})" for t, c in
                    sorted(sa['tools_used_counts'].items(), key=lambda x: x[1], reverse=True))
                content.append(f"- **Herramientas:** {tools_str}\n")

            # Archivos tocados
            if sa['files_touched']:
                files_display = sa['files_touched'][:10]
                files_str = ', '.join(f"`{f}`" for f in files_display)
                if len(sa['files_touched']) > 10:
                    files_str += f" *(y {len(sa['files_touched']) - 10} mas)*"
                content.append(f"- **Archivos:** {files_str}\n")

            # Token usage
            inp_tok = sa['token_usage']['input_tokens']
            out_tok = sa['token_usage']['output_tokens']
            if inp_tok > 0 or out_tok > 0:
                content.append(f"- **Tokens:** input: {inp_tok:,} | output: {out_tok:,}\n")

            content.append("\n")

    def _generate_enhanced_qa_report(self):
        """Genera reporte mejorado de Q&A con operaciones y subagentes"""
        output_file = self.output_dir / "05_qa_mejorado_con_operaciones.md"

        content = []
        content.append("# Pares de Preguntas y Respuestas con Operaciones de Archivos\n\n")
        content.append(f"Total de pares Q&A: {len(self.qa_pairs)}\n\n")
        content.append("*Este reporte muestra cada pregunta-respuesta con un resumen de las operaciones de archivos ejecutadas durante esa interaccion.*\n")
        if self.subagent_data:
            content.append("*v3.0: Incluye actividad de subagentes vinculada a cada interaccion.*\n")
        content.append("\n---\n\n")

        for i, qa in enumerate(self.qa_pairs, 1):
            content.append(f"## Q&A #{i}\n\n")
            content.append(f"**Archivo de sesion:** {qa['session_file']}\n\n")

            question_time = self._format_timestamp(qa['question_timestamp'])
            answer_time = self._format_timestamp(qa['answer_timestamp'])
            duration = self._calculate_interaction_duration(qa['question_timestamp'], qa['answer_timestamp'])

            content.append("**Cronologia de la interaccion:**\n")
            content.append(f"- **Inicio (Usuario envia):** {question_time}\n")
            if qa['answer_timestamp']:
                content.append(f"- **Fin (Sistema responde):** {answer_time}\n")
                if duration:
                    content.append(f"- **Duracion:** {duration}\n")
            else:
                content.append("- **Fin:** Sin respuesta registrada\n")
            content.append("\n")

            # Pregunta
            content.append("### Usuario dice:\n\n")
            content.append(qa['question'])
            content.append("\n\n")

            # Operaciones de archivos (sesion principal)
            self._render_qa_operations_section(qa, content)

            # v3.0: Subagentes invocados
            self._render_qa_subagents_section(qa, content)

            # v4.0: Codex sessions for this Q&A
            codex_sessions = self._get_codex_for_qa(qa)
            if codex_sessions:
                content.append(f"\n**Delegaciones a Codex ({len(codex_sessions)}):**\n\n")
                for cs in codex_sessions:
                    rollout = cs['rollout']
                    content.append(f"- **Codex** `{cs['thread_id'][:11]}` ({cs.get('model', 'gpt-5.4')}) — "
                                   f"{cs.get('tokens_used', 0):,} tokens, {rollout.get('duration_str', '?')}, "
                                   f"{len(rollout.get('function_calls', []))} comandos\n")
                    # Show first response preview
                    for am in rollout.get('assistant_messages', [])[-1:]:
                        for t in am.get('texts', []):
                            preview = t[:300] + '...' if len(t) > 300 else t
                            content.append(f"\n  > {preview}\n")
                content.append("\n")

            # Respuesta del sistema
            content.append("### Sistema responde:\n\n")
            content.append(qa['answer'])
            content.append("\n\n")
            content.append("---\n\n")

        full_content = ''.join(content)
        self._split_large_file(output_file, full_content)

    def _generate_operations_log(self):
        """Genera log simple de operaciones en formato CSV"""
        output_file = self.output_dir / "log_operaciones_archivos.md"

        content = []
        content.append("# Log de Operaciones de Archivos\n\n")
        content.append("Formato CSV separado por ';' para importacion:\n\n")
        content.append("```\n")
        content.append("Operacion;Ruta;Herramienta;Sesion;Timestamp;Origen\n")

        # Combinar operaciones principales y de subagentes
        all_ops = []

        for op in self.file_operations:
            file_path = self._extract_file_path_from_input(op.get('raw_input', {}))
            if not file_path:
                file_path = self._extract_path_from_details(op.get('details', ''))
            if not file_path:
                file_path = "N/A"

            all_ops.append({
                'operation': self._extract_operation_name(op),
                'file_path': file_path,
                'tool': op['tool_name'],
                'session': op['session_file'],
                'timestamp': op['timestamp'],
                'origin': 'main'
            })

        for op in self.subagent_operations:
            file_path = self._extract_file_path_from_input(op.get('raw_input', {}))
            if not file_path:
                file_path = "N/A"

            all_ops.append({
                'operation': self._extract_operation_name(op),
                'file_path': file_path,
                'tool': op['tool_name'],
                'session': op['session_id'][:12],
                'timestamp': op['timestamp'],
                'origin': f"subagent:{op['agent_id'][:8]}"
            })

        # Ordenar por timestamp
        all_ops.sort(key=lambda x: x.get('timestamp') or '')

        for op_data in all_ops:
            ts = self._convert_timestamp_to_numbers(op_data['timestamp'])
            content.append(f"{op_data['operation']};{op_data['file_path']};{op_data['tool']};{op_data['session']};{ts};{op_data['origin']}\n")

        content.append("```\n\n")
        content.append(f"**Total de operaciones registradas:** {len(all_ops)}\n")
        content.append(f"  - Sesion principal: {len(self.file_operations)}\n")
        content.append(f"  - Subagentes: {len(self.subagent_operations)}\n\n")
        content.append("**Nota:** Este archivo puede importarse como CSV usando ';' como separador.\n")

        full_content = ''.join(content)
        self._split_large_file(output_file, full_content)

        print(f"  Log de operaciones generado: {output_file.name}")

    # ========================================================================
    # v3.0: NUEVOS REPORTES
    # ========================================================================

    def _generate_subagents_report(self):
        """Genera reporte detallado de todos los subagentes"""
        output_file = self.output_dir / "06_subagentes_detalle.md"

        content = []
        content.append("# Reporte de Subagentes\n\n")
        content.append(f"**Total de subagentes procesados:** {len(self.subagent_data)}\n")

        # Sesiones con subagentes
        sessions_with_sa = set(sa['session_id'] for sa in self.subagent_data)
        content.append(f"**Sesiones con subagentes:** {len(sessions_with_sa)}\n")

        # Modelo mas utilizado
        model_counts = {}
        for sa in self.subagent_data:
            m = sa['model'] or 'desconocido'
            model_counts[m] = model_counts.get(m, 0) + 1
        if model_counts:
            top_model = max(model_counts.items(), key=lambda x: x[1])
            content.append(f"**Modelo mas utilizado:** {top_model[0]} ({top_model[1]})\n")

        content.append("\n---\n\n")

        # Estadisticas globales
        content.append("## Estadisticas Globales\n\n")
        content.append("| Metrica | Valor |\n")
        content.append("|---------|-------|\n")
        content.append(f"| Total subagentes | {len(self.subagent_data)} |\n")

        # Por tipo (basado en invocaciones)
        type_counts = {}
        for inv in self.agent_invocations:
            t = inv['subagent_type'] or 'default'
            type_counts[t] = type_counts.get(t, 0) + 1
        for t, c in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
            content.append(f"| Tipo {t} | {c} |\n")

        content.append(f"| Total tools ejecutadas | {len(self.subagent_operations)} |\n")

        all_files = set()
        for sa in self.subagent_data:
            all_files.update(sa['files_touched'])
        content.append(f"| Total archivos tocados | {len(all_files)} |\n")

        compact_count = sum(1 for sa in self.subagent_data if sa['is_compact'])
        content.append(f"| Sesiones compactadas | {compact_count} |\n")

        total_input = sum(sa['token_usage']['input_tokens'] for sa in self.subagent_data)
        total_output = sum(sa['token_usage']['output_tokens'] for sa in self.subagent_data)
        content.append(f"| Tokens input totales | {total_input:,} |\n")
        content.append(f"| Tokens output totales | {total_output:,} |\n")

        content.append("\n---\n\n")

        # Herramientas mas usadas por subagentes
        content.append("## Top Herramientas de Subagentes\n\n")
        sa_tool_totals = {}
        for sa in self.subagent_data:
            for tool, count in sa['tools_used_counts'].items():
                sa_tool_totals[tool] = sa_tool_totals.get(tool, 0) + count

        for tool, count in sorted(sa_tool_totals.items(), key=lambda x: x[1], reverse=True)[:20]:
            content.append(f"- **{tool}:** {count} usos\n")

        content.append("\n---\n\n")

        # Detalle por sesion
        content.append("## Detalle por Sesion\n\n")

        for session_id in sorted(sessions_with_sa):
            session_subagents = [sa for sa in self.subagent_data if sa['session_id'] == session_id]
            session_subagents.sort(key=lambda x: x['start_time'] or '')

            content.append(f"### Sesion: {session_id[:16]}...\n\n")
            content.append(f"**Subagentes:** {len(session_subagents)}")

            times = [sa['start_time'] for sa in session_subagents if sa['start_time']]
            if times:
                content.append(f" | **Periodo:** {self._format_timestamp(min(times))} a {self._format_timestamp(max(times))}")
            content.append("\n\n")

            for idx, sa in enumerate(session_subagents, 1):
                slug_display = sa['slug'] or sa['agent_id'][:12]
                model_short = sa['model'].split('-20')[0] if '-20' in sa['model'] else (sa['model'] or 'N/A')
                duration = self._calculate_interaction_duration(sa['start_time'], sa['end_time'])

                content.append(f"#### Subagente #{idx}: {slug_display} (`{sa['agent_id'][:10]}`)\n\n")

                content.append(f"- **Modelo:** {model_short}\n")
                content.append(f"- **Inicio:** {self._format_timestamp(sa['start_time'])}\n")
                if duration:
                    content.append(f"- **Duracion:** {duration}\n")
                content.append(f"- **Mensajes:** {sa['total_messages']}\n")
                if sa['is_compact']:
                    content.append("- *(sesion compactada)*\n")

                # Tokens
                inp = sa['token_usage']['input_tokens']
                out = sa['token_usage']['output_tokens']
                if inp > 0 or out > 0:
                    content.append(f"- **Tokens:** input: {inp:,} | output: {out:,}\n")

                content.append("\n")

                # Tarea asignada
                if sa['prompt']:
                    prompt_display = sa['prompt'][:500] + '...' if len(sa['prompt']) > 500 else sa['prompt']
                    content.append("**Tarea asignada:**\n")
                    content.append(f"```\n{prompt_display}\n```\n\n")

                # Herramientas
                if sa['tools_used_counts']:
                    content.append("**Herramientas utilizadas:**\n")
                    for tool, count in sorted(sa['tools_used_counts'].items(), key=lambda x: x[1], reverse=True):
                        content.append(f"- {tool}: {count}\n")
                    content.append("\n")

                # Archivos tocados
                if sa['files_touched']:
                    content.append("**Archivos tocados:**\n")
                    for f_name in sa['files_touched'][:15]:
                        content.append(f"- `{f_name}`\n")
                    if len(sa['files_touched']) > 15:
                        content.append(f"- *(y {len(sa['files_touched']) - 15} mas...)*\n")
                    content.append("\n")

                # Respuesta final
                if sa['final_response']:
                    resp_display = sa['final_response'][:300] + '...' if len(sa['final_response']) > 300 else sa['final_response']
                    content.append("**Resultado:**\n")
                    content.append(f"```\n{resp_display}\n```\n\n")

                content.append("---\n\n")

        full_content = ''.join(content)
        self._split_large_file(output_file, full_content)
        print(f"  Reporte de subagentes generado: {output_file.name}")

    def _generate_memory_report(self):
        """Genera reporte de la memoria del proyecto"""
        output_file = self.output_dir / "07_memoria_proyecto.md"

        content = []
        content.append("# Memoria del Proyecto\n\n")
        content.append(f"**Archivos de memoria encontrados:** {len(self.memory_data)}\n\n")
        content.append("*La memoria del proyecto contiene decisiones, lecciones tecnicas y preferencias persistentes entre sesiones de Claude Code.*\n\n")
        content.append("---\n\n")

        # Primero mostrar el indice si existe
        if 'MEMORY.md' in self.memory_data:
            content.append("## Indice de Memoria (MEMORY.md)\n\n")
            content.append(self.memory_data['MEMORY.md'])
            content.append("\n\n---\n\n")

        # Luego los demas archivos
        for filename, file_content in sorted(self.memory_data.items()):
            if filename == 'MEMORY.md':
                continue

            content.append(f"## {filename}\n\n")

            # Intentar parsear frontmatter
            if file_content.startswith('---'):
                parts = file_content.split('---', 2)
                if len(parts) >= 3:
                    frontmatter = parts[1].strip()
                    body = parts[2].strip()

                    content.append("**Metadata:**\n")
                    for line in frontmatter.split('\n'):
                        line = line.strip()
                        if line:
                            content.append(f"- {line}\n")
                    content.append("\n**Contenido:**\n\n")
                    content.append(body)
                else:
                    content.append(file_content)
            else:
                content.append(file_content)

            content.append("\n\n---\n\n")

        full_content = ''.join(content)
        self._split_large_file(output_file, full_content)
        print(f"  Reporte de memoria generado: {output_file.name}")

    def _generate_efficiency_report(self):
        """Genera reporte de eficiencia y consumo de tokens por sesion"""
        output_file = self.output_dir / "09_eficiencia_tokens.md"

        content = []
        content.append("# Reporte de Eficiencia y Consumo de Tokens\n\n")
        content.append(f"**Fecha de procesamiento:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        # ---- Totales globales ----
        total_main = {'input': 0, 'output': 0, 'cache_create': 0, 'cache_read': 0}
        total_sub = {'input': 0, 'output': 0, 'cache_create': 0, 'cache_read': 0}

        for session in self.sessions_summary:
            tu = session.get('token_usage', {})
            total_main['input'] += tu.get('input_tokens', 0)
            total_main['output'] += tu.get('output_tokens', 0)
            total_main['cache_create'] += tu.get('cache_creation', 0)
            total_main['cache_read'] += tu.get('cache_read', 0)

        for sa in self.subagent_data:
            tu = sa.get('token_usage', {})
            total_sub['input'] += tu.get('input_tokens', 0)
            total_sub['output'] += tu.get('output_tokens', 0)
            total_sub['cache_create'] += tu.get('cache_creation', 0)
            total_sub['cache_read'] += tu.get('cache_read', 0)

        # v4.0: Codex tokens
        total_codex = sum(cs.get('tokens_used', 0) for cs in self.codex_matched.values())
        has_codex = total_codex > 0

        grand_input = total_main['input'] + total_sub['input']
        grand_output = total_main['output'] + total_sub['output']
        grand_cache_create = total_main['cache_create'] + total_sub['cache_create']
        grand_cache_read = total_main['cache_read'] + total_sub['cache_read']
        grand_total = grand_input + grand_output + grand_cache_create + grand_cache_read + total_codex

        content.append("## Consumo Global\n\n")
        if has_codex:
            content.append("| Concepto | Sesiones Principales | Subagentes | Codex (GPT-5.4) | Total |\n")
            content.append("|----------|--------------------:|----------:|----------------:|-----------:|\n")
            content.append(f"| Input tokens | {total_main['input']:,} | {total_sub['input']:,} | — | {grand_input:,} |\n")
            content.append(f"| Output tokens | {total_main['output']:,} | {total_sub['output']:,} | — | {grand_output:,} |\n")
            content.append(f"| Cache creation | {total_main['cache_create']:,} | {total_sub['cache_create']:,} | — | {grand_cache_create:,} |\n")
            content.append(f"| Cache read | {total_main['cache_read']:,} | {total_sub['cache_read']:,} | — | {grand_cache_read:,} |\n")
            content.append(f"| Codex tokens | — | — | {total_codex:,} | {total_codex:,} |\n")
            main_subtotal = total_main['input']+total_main['output']+total_main['cache_create']+total_main['cache_read']
            sub_subtotal = total_sub['input']+total_sub['output']+total_sub['cache_create']+total_sub['cache_read']
            content.append(f"| **Total** | **{main_subtotal:,}** | **{sub_subtotal:,}** | **{total_codex:,}** | **{grand_total:,}** |\n")
        else:
            content.append("| Concepto | Sesiones Principales | Subagentes | Total |\n")
            content.append("|----------|--------------------:|----------:|-----------:|\n")
            content.append(f"| Input tokens | {total_main['input']:,} | {total_sub['input']:,} | {grand_input:,} |\n")
            content.append(f"| Output tokens | {total_main['output']:,} | {total_sub['output']:,} | {grand_output:,} |\n")
            content.append(f"| Cache creation | {total_main['cache_create']:,} | {total_sub['cache_create']:,} | {grand_cache_create:,} |\n")
            content.append(f"| Cache read | {total_main['cache_read']:,} | {total_sub['cache_read']:,} | {grand_cache_read:,} |\n")
            main_subtotal = total_main['input']+total_main['output']+total_main['cache_create']+total_main['cache_read']
            sub_subtotal = total_sub['input']+total_sub['output']+total_sub['cache_create']+total_sub['cache_read']
            content.append(f"| **Total** | **{main_subtotal:,}** | **{sub_subtotal:,}** | **{grand_total:,}** |\n")

        # Porcentaje por tipo
        if grand_total > 0:
            content.append(f"\n- Sesiones principales: **{main_subtotal/grand_total*100:.1f}%** del consumo total\n")
            content.append(f"- Subagentes: **{sub_subtotal/grand_total*100:.1f}%** del consumo total\n")
            if has_codex:
                content.append(f"- Codex (GPT-5.4): **{total_codex/grand_total*100:.1f}%** del consumo total ({len(self.codex_matched)} sesiones)\n")

        # Cache hit rate
        total_cache = grand_cache_create + grand_cache_read
        if total_cache > 0:
            cache_hit_rate = grand_cache_read / total_cache * 100
            content.append(f"- Cache hit rate: **{cache_hit_rate:.1f}%** ({grand_cache_read:,} reads / {total_cache:,} total cache tokens)\n")

        content.append("\n---\n\n")

        # ---- Detalle por sesion ----
        content.append("## Consumo por Sesion\n\n")

        # Preparar datos de sesion para ordenar
        session_rows = []
        for session in self.sessions_summary:
            tu = session.get('token_usage', {})
            inp = tu.get('input_tokens', 0)
            out = tu.get('output_tokens', 0)
            cc = tu.get('cache_creation', 0)
            cr = tu.get('cache_read', 0)
            session_total = inp + out + cc + cr

            # Tokens de subagentes de esta sesion
            sid = session['file'].replace('.jsonl', '')
            sa_list = [sa for sa in self.subagent_data if sa['session_id'] == sid]
            sa_inp = sum(sa['token_usage']['input_tokens'] for sa in sa_list)
            sa_out = sum(sa['token_usage']['output_tokens'] for sa in sa_list)
            sa_cc = sum(sa['token_usage']['cache_creation'] for sa in sa_list)
            sa_cr = sum(sa['token_usage']['cache_read'] for sa in sa_list)
            sa_total = sa_inp + sa_out + sa_cc + sa_cr

            combined_total = session_total + sa_total

            # Duracion de la sesion
            duration = self._calculate_interaction_duration(session.get('start_time', ''), session.get('end_time', ''))

            # Q&A count
            qa_count = sum(1 for qa in self.qa_pairs if qa['session_file'] == session['file'])
            ops_count = len(session['operations'])

            # Metricas de eficiencia
            tokens_per_qa = combined_total / qa_count if qa_count > 0 else 0
            tokens_per_op = combined_total / ops_count if ops_count > 0 else 0

            session_rows.append({
                'file': session['file'],
                'session_id': sid,
                'main_input': inp,
                'main_output': out,
                'main_cache_create': cc,
                'main_cache_read': cr,
                'main_total': session_total,
                'sa_count': len(sa_list),
                'sa_input': sa_inp,
                'sa_output': sa_out,
                'sa_total': sa_total,
                'combined_total': combined_total,
                'duration': duration,
                'qa_count': qa_count,
                'ops_count': ops_count,
                'tokens_per_qa': tokens_per_qa,
                'tokens_per_op': tokens_per_op,
                'models': session.get('models_used', {}),
                'start_time': session.get('start_time', ''),
                'total_messages': session.get('total_messages', 0)
            })

        # Ordenar por consumo total descendente
        session_rows.sort(key=lambda x: x['combined_total'], reverse=True)

        # Tabla resumen
        content.append("| Sesion | Duracion | Q&A | Ops | Tokens Main | Tokens Sub | Total | Tok/Q&A | Tok/Op |\n")
        content.append("|--------|----------|----:|----:|------------:|-----------:|------:|--------:|-------:|\n")

        for row in session_rows:
            sid_short = row['session_id'][:12] + '...'
            dur = row['duration'] or 'N/A'
            content.append(
                f"| {sid_short} | {dur} | {row['qa_count']} | {row['ops_count']} "
                f"| {row['main_total']:,} | {row['sa_total']:,} | {row['combined_total']:,} "
                f"| {row['tokens_per_qa']:,.0f} | {row['tokens_per_op']:,.0f} |\n"
            )

        content.append("\n---\n\n")

        # ---- Detalle expandido por sesion ----
        content.append("## Detalle por Sesion\n\n")

        for row in session_rows:
            content.append(f"### {row['session_id'][:16]}...\n\n")
            content.append(f"- **Periodo:** {self._format_timestamp(row['start_time'])}\n")
            content.append(f"- **Duracion:** {row['duration'] or 'N/A'}\n")
            content.append(f"- **Mensajes totales:** {row['total_messages']}\n")
            content.append(f"- **Pares Q&A:** {row['qa_count']}\n")
            content.append(f"- **Operaciones:** {row['ops_count']}\n")
            content.append(f"- **Subagentes:** {row['sa_count']}\n\n")

            content.append("**Tokens sesion principal:**\n")
            content.append(f"- Input: {row['main_input']:,}\n")
            content.append(f"- Output: {row['main_output']:,}\n")
            content.append(f"- Cache creation: {row['main_cache_create']:,}\n")
            content.append(f"- Cache read: {row['main_cache_read']:,}\n")
            content.append(f"- **Subtotal:** {row['main_total']:,}\n\n")

            if row['sa_count'] > 0:
                content.append("**Tokens subagentes:**\n")
                content.append(f"- Input: {row['sa_input']:,}\n")
                content.append(f"- Output: {row['sa_output']:,}\n")
                content.append(f"- **Subtotal:** {row['sa_total']:,}\n\n")

            content.append(f"**Total combinado:** {row['combined_total']:,}\n\n")

            # Eficiencia
            content.append("**Metricas de eficiencia:**\n")
            content.append(f"- Tokens por Q&A: {row['tokens_per_qa']:,.0f}\n")
            content.append(f"- Tokens por operacion: {row['tokens_per_op']:,.0f}\n")

            # Cache efficiency
            main_cache_total = row['main_cache_create'] + row['main_cache_read']
            if main_cache_total > 0:
                hit_rate = row['main_cache_read'] / main_cache_total * 100
                content.append(f"- Cache hit rate: {hit_rate:.1f}%\n")

            # Output ratio (output / total - que porcentaje es output util vs input context)
            if row['combined_total'] > 0:
                output_ratio = (row['main_output'] + row['sa_output']) / row['combined_total'] * 100
                content.append(f"- Output ratio: {output_ratio:.1f}% (tokens de output / total)\n")

            # Modelos
            if row['models']:
                content.append("\n**Modelos utilizados:**\n")
                for model, count in sorted(row['models'].items(), key=lambda x: x[1], reverse=True):
                    content.append(f"- {model}: {count} respuestas\n")

            content.append("\n---\n\n")

        # ---- Ranking de eficiencia ----
        content.append("## Ranking de Eficiencia\n\n")
        content.append("*Sesiones ordenadas por tokens/Q&A (menor = mas eficiente):*\n\n")

        ranked = sorted([r for r in session_rows if r['qa_count'] > 0], key=lambda x: x['tokens_per_qa'])

        content.append("| # | Sesion | Tokens/Q&A | Q&A | Total Tokens | Duracion |\n")
        content.append("|---|--------|----------:|----:|-----------:|----------|\n")

        for i, row in enumerate(ranked, 1):
            sid_short = row['session_id'][:12] + '...'
            dur = row['duration'] or 'N/A'
            content.append(f"| {i} | {sid_short} | {row['tokens_per_qa']:,.0f} | {row['qa_count']} | {row['combined_total']:,} | {dur} |\n")

        content.append("\n---\n\n")

        # ---- Modelos globales ----
        content.append("## Uso de Modelos (Global)\n\n")
        all_models = {}
        for session in self.sessions_summary:
            for model, count in session.get('models_used', {}).items():
                all_models[model] = all_models.get(model, 0) + count

        for sa in self.subagent_data:
            model = sa.get('model', '')
            if model:
                all_models[model] = all_models.get(model, 0) + 1

        content.append("| Modelo | Usos | Tipo |\n")
        content.append("|--------|-----:|------|\n")

        for model, count in sorted(all_models.items(), key=lambda x: x[1], reverse=True):
            tipo = 'subagent' if 'haiku' in model.lower() else ('compaction' if 'synthetic' in model.lower() else 'principal')
            content.append(f"| {model} | {count} | {tipo} |\n")

        full_content = ''.join(content)
        self._split_large_file(output_file, full_content)
        print(f"  Reporte de eficiencia generado: {output_file.name}")

    def _generate_tool_results_report(self):
        """Genera reporte resumen de tool-results externos"""
        output_file = self.output_dir / "08_tool_results_externos.md"

        content = []
        content.append("# Tool-Results Externos\n\n")

        total = sum(len(files) for files in self.tool_results_data.values())
        content.append(f"**Total de archivos de resultados:** {total}\n\n")
        content.append("*Estos archivos contienen resultados de herramientas que fueron demasiado grandes para almacenar inline en los JSONL (snapshots de Playwright, outputs largos, etc.)*\n\n")
        content.append("---\n\n")

        for session_id in sorted(self.tool_results_data.keys()):
            files = self.tool_results_data[session_id]
            if not files:
                continue

            content.append(f"## Sesion: {session_id[:16]}...\n\n")
            content.append(f"**Archivos:** {len(files)}\n\n")

            # Categorizar archivos
            categories = {}
            for fname, fdata in files.items():
                if 'playwright' in fname.lower() or 'browser' in fname.lower():
                    cat = 'Playwright/Browser'
                elif 'mcp' in fname.lower():
                    cat = 'MCP Tools'
                else:
                    cat = 'Otros'

                if cat not in categories:
                    categories[cat] = []
                categories[cat].append((fname, fdata))

            for cat, cat_files in sorted(categories.items()):
                content.append(f"### {cat} ({len(cat_files)} archivos)\n\n")
                for fname, fdata in sorted(cat_files, key=lambda x: x[0]):
                    size_kb = fdata['size_bytes'] / 1024
                    content.append(f"- **`{fname}`** ({size_kb:.1f} KB)\n")

                    # Mostrar preview del contenido
                    preview = fdata['content_preview'][:200].strip()
                    if preview:
                        # Limpiar para markdown
                        preview = preview.replace('`', "'").replace('\n', ' ')[:150]
                        content.append(f"  - Preview: `{preview}...`\n")

                content.append("\n")

            content.append("---\n\n")

        full_content = ''.join(content)
        self._split_large_file(output_file, full_content)
        print(f"  Reporte de tool-results generado: {output_file.name}")

    def _generate_codex_integrated_report(self):
        """Genera reporte integrado de delegaciones a Codex."""
        output_file = self.output_dir / "10_codex_integrado.md"

        content = []
        content.append("# Reporte Integrado: Delegaciones Claude → Codex (GPT-5.4)\n\n")
        content.append(f"**Fecha de procesamiento:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        # Stats
        content.append("## Resumen\n\n")
        content.append(f"- **Invocaciones a Codex detectadas:** {len(self.codex_invocations)}\n")
        agent_invs = [i for i in self.codex_invocations if i['source'] == 'agent']
        content.append(f"  - Agent calls: {len(agent_invs)}\n")
        skill_invs = [i for i in self.codex_invocations if i['source'] == 'skill']
        content.append(f"  - Skill calls: {len(skill_invs)}\n")
        bash_invs = [i for i in self.codex_invocations if i['source'] == 'bash']
        content.append(f"  - Bash calls: {len(bash_invs)}\n")
        content.append(f"- **Sesiones de Codex matcheadas:** {len(self.codex_matched)}\n")

        total_codex_tokens = sum(cs['tokens_used'] for cs in self.codex_matched.values())
        total_codex_cmds = sum(len(cs['rollout']['function_calls']) for cs in self.codex_matched.values())
        content.append(f"- **Tokens Codex totales:** {total_codex_tokens:,}\n")
        content.append(f"- **Comandos ejecutados por Codex:** {total_codex_cmds}\n")

        content.append("\n---\n\n")

        # Timeline of all codex invocations
        content.append("## Timeline de Invocaciones\n\n")
        content.append("| # | Timestamp | Sesion Claude | Tipo | Descripcion | Match Codex | Tokens |\n")
        content.append("|---|-----------|---------------|------|-------------|-------------|--------|\n")

        sorted_invs = sorted(self.codex_invocations, key=lambda x: x['timestamp'] or '')
        for idx, inv in enumerate(sorted_invs, 1):
            ts = inv['timestamp'][:19] if inv['timestamp'] else '?'
            session = inv['session_file'][:12]
            source = inv['source']
            desc = inv['description'][:40]

            # Check if this invocation has a match
            match_info = ''
            tokens = ''
            if inv['tool_use_id'] in self.codex_matched:
                cs = self.codex_matched[inv['tool_use_id']]
                match_info = cs['thread_id'][:11]
                tokens = f"{cs['tokens_used']:,}"

            content.append(f"| {idx} | {ts} | {session} | {source} | {desc} | {match_info} | {tokens} |\n")

        content.append("\n---\n\n")

        # Detailed expansion of each matched Codex session
        content.append("# Detalle de Delegaciones Matcheadas\n\n")

        for idx, (tool_use_id, cs) in enumerate(sorted(self.codex_matched.items(),
                                                          key=lambda x: x[1]['invocation']['timestamp'] or ''), 1):
            inv = cs['invocation']
            rollout = cs['rollout']

            content.append(f"## Delegacion {idx}: {cs.get('title', cs.get('thread_name', ''))[:80]}\n\n")

            # Metadata
            content.append(f"- **Claude session:** `{inv['session_file']}` linea {inv['line_number']}\n")
            content.append(f"- **Codex thread:** `{cs['thread_id']}`\n")
            content.append(f"- **Modelo:** {cs.get('model', 'gpt-5.4')}\n")
            content.append(f"- **Tokens:** {cs.get('tokens_used', 0):,}\n")
            content.append(f"- **Duracion:** {rollout.get('duration_str', '?')}\n")
            content.append(f"- **Proyecto:** {cs.get('cwd', '?').split('/')[-1]}\n")
            content.append(f"- **Match temporal:** {cs['match_diff_seconds']:.0f}s de diferencia\n")
            content.append(f"- **Comandos ejecutados:** {len(rollout.get('function_calls', []))}\n")
            content.append(f"- **Bloques de razonamiento:** {len(rollout.get('reasoning', []))}\n")
            content.append("\n")

            # User input (what was sent to Codex)
            user_inputs = rollout.get('user_inputs', [])
            if user_inputs:
                content.append("### Tarea Enviada a Codex\n\n")
                for ui in user_inputs:
                    for t in ui.get('texts', []):
                        # Skip environment_context (developer prompt)
                        if t.strip().startswith('<environment_context>') or t.strip().startswith('<permissions'):
                            continue
                        if len(t.strip()) > 50:  # Skip very short system messages
                            content.append(f"{t}\n\n")

            # Reasoning
            reasoning = rollout.get('reasoning', [])
            if reasoning:
                non_empty = [r for r in reasoning if r.get('summary', '').strip()]
                if non_empty:
                    content.append("### Razonamiento del Modelo (GPT-5.4)\n\n")
                    for j, r in enumerate(non_empty, 1):
                        content.append(f"**Paso {j}:**\n> {r['summary']}\n\n")

            # Commands executed
            calls = rollout.get('function_calls', [])
            if calls:
                content.append(f"### Comandos Ejecutados ({len(calls)})\n\n")
                for j, fc in enumerate(calls, 1):
                    name = fc.get('name', '?')
                    args = fc.get('args', {})
                    cmd = args.get('cmd', '')
                    output = fc.get('output', '')

                    if cmd:
                        content.append(f"**[{j}]** `{cmd}`\n")
                    else:
                        args_str = json.dumps(args)
                        content.append(f"**[{j}]** {name}({args_str[:150]})\n")

                    if output:
                        # Truncate long outputs
                        if len(output) > 600:
                            output_display = output[:600] + f"\n... [{len(output)} chars total]"
                        else:
                            output_display = output
                        content.append(f"```\n{output_display}\n```\n\n")
                    else:
                        content.append("\n")

            # Assistant responses (full text from Codex)
            assistant_msgs = rollout.get('assistant_messages', [])
            if assistant_msgs:
                content.append("### Respuestas Completas de Codex\n\n")
                for j, am in enumerate(assistant_msgs, 1):
                    for t in am.get('texts', []):
                        if t.strip():
                            content.append(f"**Respuesta {j}:**\n\n{t}\n\n")

            content.append("---\n\n")

        # Write to file(s)
        full_content = ''.join(content)
        self._split_large_file(output_file, full_content)
        print(f"  Reporte Codex integrado generado: {output_file.name}")

    # ========================================================================
    # REPORTES OPCIONALES (--last, --file-history)
    # ========================================================================

    def _generate_last_conversations_report(self, last_n):
        """Genera reporte de las ultimas N conversaciones"""
        output_file = self.output_dir / f"ultimas_{last_n}_conversaciones.md"

        sorted_qa = sorted(self.qa_pairs, key=lambda x: x['question_timestamp'], reverse=True)
        last_conversations = sorted_qa[:last_n]

        content = []
        content.append(f"# Ultimas {last_n} Conversaciones con Operaciones de Archivos\n\n")
        content.append(f"Total de conversaciones mostradas: {len(last_conversations)}\n\n")
        content.append("*Este reporte muestra las ultimas conversaciones ordenadas cronologicamente (mas recientes primero).*\n")
        if self.subagent_data:
            content.append("*Incluye actividad de subagentes vinculada a cada interaccion.*\n")
        content.append("\n---\n\n")

        for i, qa in enumerate(last_conversations, 1):
            content.append(f"## Conversacion #{i} (de las mas recientes)\n\n")
            content.append(f"**Archivo de sesion:** {qa['session_file']}\n\n")

            question_time = self._format_timestamp(qa['question_timestamp'])
            answer_time = self._format_timestamp(qa['answer_timestamp'])
            duration = self._calculate_interaction_duration(qa['question_timestamp'], qa['answer_timestamp'])

            content.append("**Cronologia de la interaccion:**\n")
            content.append(f"- **Inicio (Usuario envia):** {question_time}\n")
            if qa['answer_timestamp']:
                content.append(f"- **Fin (Sistema responde):** {answer_time}\n")
                if duration:
                    content.append(f"- **Duracion:** {duration}\n")
            else:
                content.append("- **Fin:** Sin respuesta registrada\n")
            content.append("\n")

            content.append("### Usuario dice:\n\n")
            content.append(qa['question'])
            content.append("\n\n")

            # Operaciones
            self._render_qa_operations_section(qa, content)

            # v3.0: Subagentes
            self._render_qa_subagents_section(qa, content)

            # Respuesta
            content.append("### Sistema responde:\n\n")
            content.append(qa['answer'])
            content.append("\n\n")
            content.append("---\n\n")

        full_content = ''.join(content)
        self._split_large_file(output_file, full_content)
        print(f"  Reporte de las ultimas {last_n} conversaciones generado: {output_file.name}")

    def _generate_file_history_report(self, target_filename):
        """Genera reporte de historial completo de modificaciones para un archivo especifico"""
        output_file = self.output_dir / f"historial_{target_filename.replace('/', '_').replace('.', '_')}.md"

        # Buscar todas las operaciones relacionadas con el archivo
        file_operations = []

        # Buscar en operaciones principales
        for op in self.file_operations:
            file_path = self._extract_file_path_from_input(op.get('raw_input', {}))
            if file_path and (target_filename in file_path or file_path.endswith(target_filename)):
                file_operations.append({**op, 'origin': 'main'})
                continue
            details = op.get('details', '')
            if target_filename in details:
                file_operations.append({**op, 'origin': 'main'})
                continue
            raw_input_str = str(op.get('raw_input', ''))
            if target_filename in raw_input_str:
                file_operations.append({**op, 'origin': 'main'})

        # v3.0: Buscar tambien en operaciones de subagentes
        for op in self.subagent_operations:
            file_path = self._extract_file_path_from_input(op.get('raw_input', {}))
            if file_path and (target_filename in file_path or file_path.endswith(target_filename)):
                file_operations.append({**op, 'origin': f"subagent:{op['agent_id'][:8]}"})
                continue
            details = op.get('details', '')
            if target_filename in details:
                file_operations.append({**op, 'origin': f"subagent:{op['agent_id'][:8]}"})

        # Ordenar cronologicamente
        file_operations.sort(key=lambda x: x.get('timestamp') or '')

        # Agrupar por conversacion
        operations_by_qa = {}
        for op in file_operations:
            op_time = op.get('timestamp', '')
            session_file = op.get('session_file', '')
            # Para operaciones de subagentes, construir el session_file
            if not session_file and 'session_id' in op:
                session_file = op['session_id'] + '.jsonl'

            matching_qa = None
            for qa in self.qa_pairs:
                if (qa['session_file'] == session_file and
                    qa['question_timestamp'] <= op_time <= (qa['answer_timestamp'] or op_time)):
                    matching_qa = qa
                    break

            if not matching_qa:
                closest_qa = None
                min_diff = float('inf')
                for qa in self.qa_pairs:
                    if qa['session_file'] == session_file:
                        try:
                            diff = abs(float(qa['question_timestamp'].replace('T', '').replace('Z', '').replace('-', '').replace(':', '').replace('.', '')) -
                                     float(op_time.replace('T', '').replace('Z', '').replace('-', '').replace(':', '').replace('.', '')))
                            if diff < min_diff:
                                min_diff = diff
                                closest_qa = qa
                        except (ValueError, AttributeError):
                            pass
                matching_qa = closest_qa

            if matching_qa:
                qa_key = f"{matching_qa['question_timestamp']}_{matching_qa['session_file']}"
                if qa_key not in operations_by_qa:
                    operations_by_qa[qa_key] = {
                        'qa': matching_qa,
                        'operations': []
                    }
                operations_by_qa[qa_key]['operations'].append(op)

        # Generar contenido
        content = []
        content.append(f"# Historial Completo de Modificaciones: {target_filename}\n\n")
        content.append(f"**Archivo analizado:** `{target_filename}`\n")
        content.append(f"**Total de operaciones encontradas:** {len(file_operations)}\n")
        content.append(f"**Conversaciones que modificaron este archivo:** {len(operations_by_qa)}\n\n")
        content.append("*Este reporte muestra todas las modificaciones historicas realizadas al archivo especificado, organizadas por conversacion.*\n\n")
        content.append("---\n\n")

        if not file_operations:
            content.append("## No se encontraron operaciones\n\n")
            content.append(f"No se encontraron operaciones relacionadas con el archivo `{target_filename}` en las sesiones procesadas.\n\n")
            content.append("**Posibles causas:**\n")
            content.append("- El archivo no fue modificado en las sesiones analizadas\n")
            content.append("- El nombre del archivo no coincide exactamente\n")
            content.append("- Las operaciones no fueron registradas correctamente\n\n")

            full_content = ''.join(content)
            self._split_large_file(output_file, full_content)
            return

        # Estadisticas por tipo de operacion
        operation_types = {}
        for op in file_operations:
            op_type = op.get('tool_name', 'unknown')
            operation_types[op_type] = operation_types.get(op_type, 0) + 1

        content.append("## Resumen de Operaciones\n\n")
        for op_type, count in sorted(operation_types.items(), key=lambda x: x[1], reverse=True):
            content.append(f"- **{op_type}:** {count} operaciones\n")
        content.append("\n")

        # Separar por origen
        main_ops = [op for op in file_operations if op.get('origin') == 'main']
        sa_ops = [op for op in file_operations if op.get('origin', '').startswith('subagent')]
        if main_ops and sa_ops:
            content.append(f"- Operaciones desde sesion principal: {len(main_ops)}\n")
            content.append(f"- Operaciones desde subagentes: {len(sa_ops)}\n\n")

        # Timeline
        sorted_conversations = sorted(operations_by_qa.items(), key=lambda x: x[1]['qa']['question_timestamp'])

        content.append("## Timeline de Modificaciones\n\n")

        for i, (qa_key, data) in enumerate(sorted_conversations, 1):
            qa = data['qa']
            ops = data['operations']

            content.append(f"### Modificacion #{i}\n\n")

            question_time = self._format_timestamp(qa['question_timestamp'])
            duration = self._calculate_interaction_duration(qa['question_timestamp'], qa['answer_timestamp'])

            content.append(f"**Fecha:** {question_time}\n")
            content.append(f"**Sesion:** {qa['session_file']}\n")
            content.append(f"**Duracion:** {duration if duration else 'N/A'}\n")
            content.append(f"**Operaciones en esta conversacion:** {len(ops)}\n\n")

            # Contexto
            content.append("#### Contexto - Usuario pregunto:\n")
            question_preview = qa['question'][:200] + '...' if len(qa['question']) > 200 else qa['question']
            content.append(f"```\n{question_preview}\n```\n\n")

            # Operaciones
            content.append("#### Operaciones realizadas en este archivo:\n\n")

            ops_by_type = {}
            for op in ops:
                tool = op.get('tool_name', 'unknown')
                if tool not in ops_by_type:
                    ops_by_type[tool] = []
                ops_by_type[tool].append(op)

            for tool, tool_ops in ops_by_type.items():
                origin_tag = ""
                content.append(f"**{tool}** ({len(tool_ops)} operaciones):\n")
                for j, op in enumerate(tool_ops, 1):
                    op_time = self._format_timestamp(op.get('timestamp', ''))
                    origin = op.get('origin', 'main')
                    origin_tag = f" [subagente]" if origin.startswith('subagent') else ""

                    if tool in ['Edit', 'Write']:
                        raw_input = op.get('raw_input', {})
                        if isinstance(raw_input, dict):
                            if 'old_string' in raw_input and 'new_string' in raw_input:
                                old_preview = raw_input['old_string'][:100] + '...' if len(raw_input['old_string']) > 100 else raw_input['old_string']
                                new_preview = raw_input['new_string'][:100] + '...' if len(raw_input['new_string']) > 100 else raw_input['new_string']
                                content.append(f"  {j}. **Edicion** ({op_time}){origin_tag}\n")
                                content.append(f"     - **Reemplazo:** `{old_preview}`\n")
                                content.append(f"     - **Por:** `{new_preview}`\n")
                            elif 'content' in raw_input:
                                content_preview = raw_input['content'][:150] + '...' if len(raw_input['content']) > 150 else raw_input['content']
                                content.append(f"  {j}. **Escritura completa** ({op_time}){origin_tag}\n")
                                content.append(f"     - **Contenido:** `{content_preview}`\n")
                            else:
                                content.append(f"  {j}. **{tool}** ({op_time}){origin_tag} - {op.get('details', '')}\n")
                        else:
                            content.append(f"  {j}. **{tool}** ({op_time}){origin_tag} - {op.get('details', '')}\n")
                    elif tool == 'Read':
                        content.append(f"  {j}. **Lectura** ({op_time}){origin_tag} - Archivo leido para analisis\n")
                    else:
                        content.append(f"  {j}. **{tool}** ({op_time}){origin_tag} - {op.get('details', '')}\n")

            content.append("\n")

            # Respuesta
            content.append("#### Resultado de la conversacion:\n")
            answer_preview = qa['answer'][:300] + '...' if len(qa['answer']) > 300 else qa['answer']
            content.append(f"```\n{answer_preview}\n```\n\n")

            content.append("---\n\n")

        full_content = ''.join(content)
        self._split_large_file(output_file, full_content)
        print(f"  Reporte de historial del archivo '{target_filename}' generado: {output_file.name}")

    # ========================================================================
    # UTILIDADES
    # ========================================================================

    def _format_timestamp(self, timestamp: str) -> str:
        """Formatea un timestamp para mostrar de manera mas legible"""
        if not timestamp:
            return "N/A"

        try:
            if 'T' in timestamp:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                return timestamp
        except Exception:
            return timestamp

    def _calculate_interaction_duration(self, start_time: str, end_time: str) -> str:
        """Calcula la duracion de una interaccion entre dos timestamps"""
        if not start_time or not end_time:
            return None

        try:
            if 'T' in start_time and 'T' in end_time:
                start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))

                if start_dt.tzinfo is None and end_dt.tzinfo is not None:
                    start_dt = start_dt.replace(tzinfo=end_dt.tzinfo)
                elif end_dt.tzinfo is None and start_dt.tzinfo is not None:
                    end_dt = end_dt.replace(tzinfo=start_dt.tzinfo)

                duration = end_dt - start_dt
                total_seconds = int(duration.total_seconds())

                if total_seconds < 0:
                    return None
                elif total_seconds < 60:
                    return f"{total_seconds} segundos"
                elif total_seconds < 3600:
                    minutes = total_seconds // 60
                    seconds = total_seconds % 60
                    return f"{minutes}m {seconds}s"
                else:
                    hours = total_seconds // 3600
                    minutes = (total_seconds % 3600) // 60
                    return f"{hours}h {minutes}m"
            else:
                return None
        except Exception:
            return None

    def _get_operations_between_qa(self, qa_pair) -> List[Dict[str, Any]]:
        """Obtiene las operaciones de archivos ejecutadas entre una pregunta y respuesta"""
        question_time = qa_pair['question_timestamp']
        answer_time = qa_pair['answer_timestamp']
        session_file = qa_pair['session_file']

        operations_in_timeframe = []

        for op in self.file_operations:
            if op['session_file'] != session_file:
                continue

            op_time = op['timestamp']

            if question_time <= op_time <= answer_time:
                operations_in_timeframe.append(op)

        return operations_in_timeframe

    def _extract_operation_name(self, operation: Dict[str, Any]) -> str:
        """Extrae el nombre de la operacion de forma simplificada"""
        op_type = operation.get('operation_type', '')
        tool_name = operation.get('tool_name', '')

        operation_mapping = {
            'tool_use': 'Tool',
            'file_result': 'File',
            'terminal_result': 'Terminal',
            'git_commit': 'GitCommit',
            'git_add': 'GitAdd',
            'git_push': 'GitPush',
            'git_pull': 'GitPull',
            'git_clone': 'GitClone',
            'git_branch': 'GitBranch',
            'npm_install': 'NpmInstall',
            'yarn_install': 'YarnInstall',
            'pip_install': 'PipInstall',
            'poetry_install': 'PoetryInstall',
            'conda_install': 'CondaInstall',
            'mkdir': 'CreateDir',
            'remove_dir': 'RemoveDir',
            'copy_file': 'CopyFile',
            'move_file': 'MoveFile',
            'create_file': 'CreateFile',
            'search_content': 'SearchContent',
            'search_files': 'SearchFiles',
            'build': 'Build',
            'test': 'Test'
        }

        return operation_mapping.get(op_type, tool_name)

    def _extract_path_from_details(self, details: str) -> str:
        """Extrae ruta de archivo de los detalles de la operacion"""
        if 'Archivo:' in details:
            parts = details.split('Archivo:')
            if len(parts) > 1:
                file_part = parts[1].split('|')[0].strip()
                if file_part and file_part != 'archivo desconocido':
                    return file_part
        return None

    def _convert_timestamp_to_numbers(self, timestamp: str) -> str:
        """Convierte timestamp ISO a formato numerico YYYYMMDDHHMMSS"""
        if not timestamp:
            return "00000000000000"

        try:
            clean_ts = timestamp.replace('-', '').replace('T', '').replace(':', '').replace('Z', '').replace('.', '')
            return clean_ts[:14].ljust(14, '0')
        except Exception:
            return "00000000000000"

    def _generate_qwen_parallel_report(self):
        """Genera reporte de sesiones paralelas de Qwen."""
        output_file = self.output_dir / "11_qwen_paralelo.md"

        content = []
        content.append("# Reporte de Actividad Paralela: Qwen CLI\n\n")
        content.append(f"**Fecha de procesamiento:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        total_msgs = sum(len(s['user_messages']) for s in self.qwen_sessions)
        total_tools = sum(len(s['tool_calls']) for s in self.qwen_sessions)
        total_responses = sum(len(s['assistant_responses']) for s in self.qwen_sessions)

        content.append("## Resumen\n\n")
        content.append(f"- **Sesiones de Qwen:** {len(self.qwen_sessions)}\n")
        content.append(f"- **Mensajes del usuario:** {total_msgs}\n")
        content.append(f"- **Respuestas del modelo:** {total_responses}\n")
        content.append(f"- **Comandos ejecutados:** {total_tools}\n")

        # Get Claude date range for correlation
        claude_dates = set()
        for session in self.sessions_summary:
            st = session.get('start_time', '')
            if st:
                claude_dates.add(st[:10])
        qwen_dates = set()
        for s in self.qwen_sessions:
            if s.get('start_time'):
                qwen_dates.add(s['start_time'][:10])
        overlap_dates = claude_dates & qwen_dates
        if overlap_dates:
            content.append(f"- **Dias con actividad simultanea Claude+Qwen:** {len(overlap_dates)} ({', '.join(sorted(overlap_dates))})\n")

        content.append("\n---\n\n")

        # Index table
        content.append("## Sesiones\n\n")
        content.append("| # | Session ID | Fecha | Mensajes | Comandos | Respuestas | Branch |\n")
        content.append("|---|-----------|-------|----------|----------|------------|--------|\n")
        for i, s in enumerate(self.qwen_sessions, 1):
            sid = s['session_id'][:12]
            date = s['start_time'][:10] if s['start_time'] else '?'
            content.append(f"| {i} | `{sid}` | {date} | {len(s['user_messages'])} | {len(s['tool_calls'])} | {len(s['assistant_responses'])} | {s['git_branch']} |\n")

        content.append("\n---\n\n")

        # Detail per session
        content.append("# Detalle por Sesion\n\n")
        for i, s in enumerate(self.qwen_sessions, 1):
            # Calculate duration
            duration = ''
            if s['start_time'] and s['end_time']:
                try:
                    t1 = datetime.fromisoformat(s['start_time'].replace('Z', '+00:00'))
                    t2 = datetime.fromisoformat(s['end_time'].replace('Z', '+00:00'))
                    diff = int((t2 - t1).total_seconds())
                    if diff > 3600:
                        duration = f"{diff//3600}h {(diff%3600)//60}m"
                    elif diff > 60:
                        duration = f"{diff//60}m {diff%60}s"
                    else:
                        duration = f"{diff}s"
                except:
                    pass

            content.append(f"## Sesion {i}: {s['session_id'][:16]}\n\n")
            content.append(f"- **Fecha:** {s['start_time'][:19] if s['start_time'] else '?'}\n")
            if duration:
                content.append(f"- **Duracion:** {duration}\n")
            content.append(f"- **Modelo:** {s['model'] or '?'}\n")
            content.append(f"- **Branch:** {s['git_branch']}\n")
            content.append(f"- **CWD:** `{s['cwd']}`\n")
            content.append(f"- **Mensajes:** {len(s['user_messages'])} del usuario, {len(s['assistant_responses'])} del modelo\n")
            content.append(f"- **Comandos:** {len(s['tool_calls'])}\n")
            content.append("\n")

            # Interleave user messages and responses chronologically
            all_events = []
            for um in s['user_messages']:
                all_events.append(('user', um['timestamp'], um['content']))
            for ar in s['assistant_responses']:
                for t in ar['texts']:
                    all_events.append(('assistant', ar['timestamp'], t))
            for tc in s['tool_calls']:
                cmd = tc['command']
                if cmd:
                    all_events.append(('tool', tc['timestamp'], f"`{cmd}`"))

            all_events.sort(key=lambda x: x[1] or '')

            for etype, ts, text in all_events:
                ts_short = ts[11:19] if ts and len(ts) > 19 else (ts or '')
                if etype == 'user':
                    content.append(f"### Usuario ({ts_short}):\n\n{text}\n\n")
                elif etype == 'assistant':
                    if len(text) > 3000:
                        content.append(f"### Qwen responde ({ts_short}):\n\n{text[:3000]}\n\n_[... {len(text):,} caracteres totales ...]_\n\n")
                    else:
                        content.append(f"### Qwen responde ({ts_short}):\n\n{text}\n\n")
                elif etype == 'tool':
                    content.append(f"**Comando** ({ts_short}): {text}\n\n")

            content.append("---\n\n")

        full_content = ''.join(content)
        self._split_large_file(output_file, full_content)
        print(f"  Reporte Qwen paralelo generado: {output_file.name}")

    def _split_large_file(self, file_path: Path, content: str, max_size_mb: int = 2):
        """Divide archivos grandes en multiples partes si superan el tamano maximo"""
        max_size_bytes = max_size_mb * 1024 * 1024

        content_bytes = content.encode('utf-8')

        if len(content_bytes) <= max_size_bytes:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return

        print(f"  Archivo {file_path.name} excede {max_size_mb}MB, dividiendo en partes...")

        lines = content.split('\n')
        total_lines = len(lines)
        bytes_per_line = len(content_bytes) / total_lines if total_lines > 0 else 0

        part_num = 1
        current_lines = []
        current_size = 0

        base_name = file_path.stem
        index_file = file_path.parent / f"{base_name}_indice.md"

        index_content = f"# Indice de {base_name}\n\n"
        index_content += "Este archivo fue dividido en multiples partes debido a su tamano.\n\n"
        index_content += "## Partes disponibles:\n\n"

        for i, line in enumerate(lines):
            line_bytes = len(line.encode('utf-8'))

            if current_size + line_bytes > max_size_bytes and current_lines:
                part_file = file_path.parent / f"{base_name}_parte_{part_num}.md"
                part_content = '\n'.join(current_lines)

                with open(part_file, 'w', encoding='utf-8') as f:
                    f.write(part_content)

                index_content += f"- [{base_name}_parte_{part_num}.md](./{base_name}_parte_{part_num}.md)\n"

                print(f"    Creada parte {part_num}: {part_file.name}")

                part_num += 1
                current_lines = [line]
                current_size = line_bytes
            else:
                current_lines.append(line)
                current_size += line_bytes

        if current_lines:
            part_file = file_path.parent / f"{base_name}_parte_{part_num}.md"
            part_content = '\n'.join(current_lines)

            with open(part_file, 'w', encoding='utf-8') as f:
                f.write(part_content)

            index_content += f"- [{base_name}_parte_{part_num}.md](./{base_name}_parte_{part_num}.md)\n"
            print(f"    Creada parte {part_num}: {part_file.name}")

        index_content += f"\n**Total de partes:** {part_num}\n"
        index_content += f"**Tamano original:** ~{len(content_bytes) / (1024*1024):.1f}MB\n"

        with open(index_file, 'w', encoding='utf-8') as f:
            f.write(index_content)

        # Escribir el indice tambien en el archivo original para navegacion directa
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(index_content)

        print(f"    Creado indice: {index_file.name}")
        print(f"    Archivo dividido en {part_num} partes")

    # ========================================================================
    # ENTRADA PRINCIPAL
    # ========================================================================

    def process_all_files(self, last_n=None, file_history=None, no_subagents=False, codex_dir=None, qwen_dir=None):
        """Procesa todos los archivos JSONL en el directorio o el archivo indicado"""
        if self.input_file:
            jsonl_files = [self.input_file]
        else:
            jsonl_files = sorted(self.input_dir.glob("*.jsonl"))

        if not jsonl_files:
            print(f"No se encontraron archivos .jsonl en {self.input_dir}")
            # Aun asi procesar subagentes y memoria si existen directorios
            if not no_subagents:
                print("\nBuscando directorios de sesion...")
                self._discover_session_directories()
                if self.session_dirs:
                    print(f"\nProcesando subagentes...")
                    self._process_all_subagents()
                    print(f"\nProcesando tool-results...")
                    self._process_all_tool_results()

            self._process_memory()

            # v4.0: Detectar y matchear delegaciones a Codex
            if codex_dir:
                self.codex_dir = codex_dir
                print(f"\nDetectando invocaciones a Codex...")
                self._detect_codex_invocations()
                if self.codex_invocations:
                    print(f"\nCargando y matcheando sesiones de Codex desde {codex_dir}...")
                    self._load_and_match_codex(codex_dir)

            # v4.1: Cargar sesiones de Qwen
            if qwen_dir:
                self.qwen_dir = qwen_dir
                print(f"\nCargando sesiones de Qwen desde {qwen_dir}...")
                self._load_qwen_sessions(qwen_dir)

            if self.subagent_data or self.memory_data or self.codex_matched or self.qwen_sessions:
                self.generate_reports()
            else:
                print("No se encontraron datos para procesar.")
            return

        print(f"Procesando {len(jsonl_files)} archivos JSONL principales...")

        for file_path in jsonl_files:
            print(f"  Procesando: {file_path.name}")
            session_data = self.process_jsonl_file(file_path)
            self.sessions_summary.append(session_data)

        # Crear pares Q&A
        self._create_qa_pairs()

        # v3.0: Descubrir y procesar directorios de sesion
        if not no_subagents:
            print(f"\nDescubriendo directorios de sesion...")
            self._discover_session_directories()

            if self.session_dirs:
                print(f"\nProcesando subagentes ({len(self.session_dirs)} sesiones con directorios)...")
                self._process_all_subagents()

                print(f"\nProcesando tool-results...")
                self._process_all_tool_results()

        # v3.0: Procesar memoria
        self._process_memory()

        # v4.0: Detectar y matchear delegaciones a Codex
        if codex_dir:
            self.codex_dir = codex_dir
            print(f"\nDetectando invocaciones a Codex...")
            self._detect_codex_invocations()
            if self.codex_invocations:
                print(f"\nCargando y matcheando sesiones de Codex desde {codex_dir}...")
                self._load_and_match_codex(codex_dir)

        # v4.1: Cargar sesiones de Qwen
        if qwen_dir:
            self.qwen_dir = qwen_dir
            print(f"\nCargando sesiones de Qwen desde {qwen_dir}...")
            self._load_qwen_sessions(qwen_dir)

        # Generar reportes
        self.generate_reports()

        # Generar reportes especiales si se solicitaron
        if last_n:
            self._generate_last_conversations_report(last_n)

        if file_history:
            self._generate_file_history_report(file_history)


def main():
    parser = argparse.ArgumentParser(
        description='Procesar sesiones de Claude Code v4.1 (subagentes, memoria, integración Codex + Qwen)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python3 process_sessions.py .
  python3 process_sessions.py . -o reportes --last 30
  python3 process_sessions.py . -o reportes --codex-dir ~/.codex/
  python3 process_sessions.py . -o reportes --qwen-dir ~/.qwen/
  python3 process_sessions.py . -o reportes --codex-dir ~/.codex/ --qwen-dir ~/.qwen/
  python3 process_sessions.py . --file-history CLAUDE.md
  python3 process_sessions.py . --no-subagents
        """
    )
    parser.add_argument('input_dir', nargs='?', default='.',
                        help='Directorio con archivos .jsonl o archivo individual (por defecto: \'.\')')
    parser.add_argument('-v', '--version', action='version', version='AI Session Analyzer v4.1.0')
    parser.add_argument('-o', '--output', help='Directorio de salida para reportes')
    parser.add_argument('--last', type=int, help='Extraer las ultimas N conversaciones en un archivo separado')
    parser.add_argument('--file-history', help='Generar historial completo de modificaciones para un archivo especifico')
    parser.add_argument('--no-subagents', action='store_true',
                        help='No procesar subagentes ni tool-results (solo JSONL principales)')
    parser.add_argument('--codex-dir',
                        help='Directorio de Codex CLI (~/.codex/) para integrar delegaciones')
    parser.add_argument('--qwen-dir',
                        help='Directorio de Qwen CLI (~/.qwen/) para incluir sesiones paralelas')

    args = parser.parse_args()

    input_path = Path(args.input_dir).expanduser()
    if not input_path.exists():
        print(f"Error: La ruta {args.input_dir} no existe")
        sys.exit(1)

    processor = SessionProcessor(args.input_dir, args.output)
    processor.process_all_files(args.last, args.file_history, args.no_subagents, args.codex_dir, args.qwen_dir)


if __name__ == "__main__":
    main()
