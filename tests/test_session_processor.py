import unittest
import tempfile
import json
import shutil
from pathlib import Path
from process_sessions import SessionProcessor


class TestSessionProcessor(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.input_dir = Path(self.temp_dir) / "sessions"
        self.output_dir = Path(self.temp_dir) / "reports"
        self.input_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_duration_calculation(self):
        processor = SessionProcessor(str(self.input_dir), str(self.output_dir))
        
        # Less than 60s
        d1 = processor._calculate_interaction_duration("2026-09-05T10:00:00Z", "2026-09-05T10:00:45Z")
        self.assertEqual(d1, "45 segundos")

        # Minutes
        d2 = processor._calculate_interaction_duration("2026-09-05T10:00:00Z", "2026-09-05T10:05:30Z")
        self.assertEqual(d2, "5m 30s")

        # Hours
        d3 = processor._calculate_interaction_duration("2026-09-05T10:00:00Z", "2026-09-05T12:15:00Z")
        self.assertEqual(d3, "2h 15m")

        # Negative or invalid
        d4 = processor._calculate_interaction_duration("2026-09-05T10:00:00Z", "2026-09-05T09:00:00Z")
        self.assertIsNone(d4)

    def test_clean_filename(self):
        processor = SessionProcessor(str(self.input_dir), str(self.output_dir))
        
        self.assertEqual(processor._get_clean_filename(""), "archivo desconocido")
        self.assertEqual(processor._get_clean_filename("/var/tmp/app.py"), "app.py")
        self.assertEqual(processor._get_clean_filename("/project/src/components/Button.tsx"), "src/components/Button.tsx")

    def test_split_large_file(self):
        processor = SessionProcessor(str(self.input_dir), str(self.output_dir))
        test_file = self.output_dir / "large_report.md"

        # Content of ~200 bytes, split threshold 0.0001 MB (~100 bytes)
        lines = [f"Line {i}: This is a sample text line for testing splitting.\n" for i in range(20)]
        content = "".join(lines)

        processor._split_large_file(test_file, content, max_size_mb=0.00005)

        # Verify index file and parts created
        index_file = self.output_dir / "large_report_indice.md"
        part_1 = self.output_dir / "large_report_parte_1.md"
        
        self.assertTrue(index_file.exists())
        self.assertTrue(part_1.exists())
        self.assertTrue(test_file.exists())

    def test_process_single_session_and_qa(self):
        # Create a sample JSONL session file
        session_file = self.input_dir / "session_1.jsonl"
        lines = [
            {
                "type": "user",
                "timestamp": "2026-09-05T10:00:00.000Z",
                "sessionId": "s-1",
                "message": {"content": "Hola, crea un script en Python"}
            },
            {
                "type": "assistant",
                "timestamp": "2026-09-05T10:00:15.000Z",
                "sessionId": "s-1",
                "message": {
                    "id": "msg_001",
                    "model": "claude-3-7-sonnet-20250219",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_123",
                            "name": "Write",
                            "input": {"file_path": "src/hello.py", "content": "print('hello')"}
                        },
                        {
                            "type": "text",
                            "text": "He creado el script src/hello.py exitosamente."
                        }
                    ],
                    "usage": {
                        "input_tokens": 120,
                        "output_tokens": 55,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 500
                    }
                }
            }
        ]

        with open(session_file, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")

        processor = SessionProcessor(str(self.input_dir), str(self.output_dir))
        processor.process_all_files()

        self.assertEqual(len(processor.sessions_summary), 1)
        self.assertEqual(len(processor.qa_pairs), 1)
        qa = processor.qa_pairs[0]
        self.assertEqual(qa["question"], "Hola, crea un script en Python")
        self.assertIn("src/hello.py", qa["answer"])

        # Check token tracking
        summary = processor.sessions_summary[0]
        self.assertEqual(summary["token_usage"]["input_tokens"], 120)
        self.assertEqual(summary["token_usage"]["output_tokens"], 55)

        # Check reports generated
        resumen_path = self.output_dir / "00_resumen_sesiones.md"
        qa_path = self.output_dir / "03_preguntas_respuestas.md"
        self.assertTrue(resumen_path.exists())
        self.assertTrue(qa_path.exists())

    def test_qa_pairs_session_isolation(self):
        # Create two interleaved sessions to ensure questions are not cross-matched
        s1_file = self.input_dir / "s1.jsonl"
        s2_file = self.input_dir / "s2.jsonl"

        with open(s1_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "timestamp": "2026-09-05T10:00:00Z", "message": {"content": "Pregunta S1"}}) + "\n")
            f.write(json.dumps({"type": "assistant", "timestamp": "2026-09-05T10:00:30Z", "message": {"id": "m1", "content": [{"type": "text", "text": "Respuesta S1"}]}}) + "\n")

        with open(s2_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "timestamp": "2026-09-05T10:00:05Z", "message": {"content": "Pregunta S2"}}) + "\n")
            f.write(json.dumps({"type": "assistant", "timestamp": "2026-09-05T10:00:20Z", "message": {"id": "m2", "content": [{"type": "text", "text": "Respuesta S2"}]}}) + "\n")

        processor = SessionProcessor(str(self.input_dir), str(self.output_dir))
        processor.process_all_files()

        self.assertEqual(len(processor.qa_pairs), 2)
        for qa in processor.qa_pairs:
            if "S1" in qa["question"]:
                self.assertEqual(qa["answer"], "Respuesta S1")
            elif "S2" in qa["question"]:
                self.assertEqual(qa["answer"], "Respuesta S2")



class TestPencilIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.input_dir = Path(self.temp_dir) / "sessions"
        self.output_dir = Path(self.temp_dir) / "reports"
        self.input_dir.mkdir(parents=True)
        self.pencil_dir = Path(self.temp_dir) / ".pencil"
        (self.pencil_dir / "pi-sessions").mkdir(parents=True)
        (self.pencil_dir / "sessions").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_pi_session(self, name="2026-09-08T00-00-00-000Z_abc.jsonl"):
        pi = self.pencil_dir / "pi-sessions" / name
        events = [
            {"type": "session", "version": 3, "id": "abc",
             "timestamp": "2026-09-08T10:00:00.000Z",
             "cwd": "/Users/tester/dev/proj-app/design/subfolder"},
            {"type": "model_change", "id": "m1", "timestamp": "2026-09-08T10:00:00.100Z",
             "provider": "opencode-go", "modelId": "model-x"},
            {"type": "message", "id": "u1", "parentId": "m1",
             "timestamp": "2026-09-08T10:00:01.000Z",
             "message": {"role": "user", "content": [
                 {"type": "text", "text": "pinta el boton de azul\n\nThe result of `get_app_state` tool call:\n\n# Current App State\nnoise noise"}]}},
            {"type": "message", "id": "a1", "parentId": "u1",
             "timestamp": "2026-09-08T10:00:10.000Z",
             "message": {"role": "assistant", "model": "model-x",
                         "usage": {"input": 100, "output": 5, "reasoning": 2,
                                   "cacheRead": 0, "cacheWrite": 0, "totalTokens": 107,
                                   "cost": {"total": 0.001}},
                         "content": [
                             {"type": "thinking", "thinking": "hmm"},
                             {"type": "toolCall", "name": "execute",
                              "arguments": {"filePath": "/Users/tester/dev/proj-app/design/main.pen", "input": "x"}},
                             {"type": "text", "text": "Listo, boton azul."}]}},
        ]
        pi.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
        return pi

    def _write_desktop_session(self, pi_name):
        desk = self.pencil_dir / "sessions" / "d-uuid.json"
        desk.write_text(json.dumps({
            "version": 1, "updatedAt": 0,
            "conversation": {
                "id": "d-uuid", "title": "Boton azul",
                "modelID": "pi;opencode-go;model-x",
                "sessionId": str(self.pencil_dir / "pi-sessions" / pi_name),
                "messages": [{"role": "user", "text": "ver /Users/tester/dev/proj-app/design/otro.pen"}],
            },
            "bindings": {},
        }), encoding="utf-8")

    def _processor_with_claude_cwd(self):
        sp = SessionProcessor(str(self.input_dir), str(self.output_dir))
        sp.user_messages.append({"cwd": "/Users/tester/dev/proj-app", "timestamp": "2026-09-08T09:00:00Z"})
        sp.assistant_responses.append({"cwd": "/Users/tester/dev/proj-app", "timestamp": "2026-09-08T11:00:00Z"})
        return sp

    def test_parse_pencil_session(self):
        pi = self._write_pi_session()
        sp = self._processor_with_claude_cwd()
        s = sp._parse_pencil_session(pi)
        self.assertEqual(s["session_id"], "abc")
        self.assertEqual(s["cwd"], "/Users/tester/dev/proj-app/design/subfolder")
        self.assertEqual(len(s["qa_pairs"]), 1)
        # El prompt limpio no debe incluir el app_state inyectado
        self.assertEqual(s["qa_pairs"][0]["user"], "pinta el boton de azul")
        self.assertEqual(s["qa_pairs"][0]["assistant"], "Listo, boton azul.")
        self.assertEqual(s["usage"]["total"], 107)
        self.assertAlmostEqual(s["usage"]["cost"], 0.001)
        self.assertEqual(s["tool_calls"], {"execute": 1})
        self.assertIn("/Users/tester/dev/proj-app/design/main.pen", s["external_paths"])
        self.assertIn("model-x", s["models_used"])

    def test_load_and_match_by_cwd(self):
        pi_name = "2026-09-08T00-00-00-000Z_abc.jsonl"
        self._write_pi_session(pi_name)
        self._write_desktop_session(pi_name)
        sp = self._processor_with_claude_cwd()
        sp._load_pencil_sessions(str(self.pencil_dir))
        self.assertEqual(len(sp.pencil_sessions), 1)
        s = sp.pencil_sessions[0]
        self.assertEqual(s["project"], "/Users/tester/dev/proj-app")
        self.assertEqual(s["match_rule"], "cwd")
        self.assertEqual(s["title"], "Boton azul")

    def test_match_by_pen_path_fallback(self):
        pi = self._write_pi_session()
        # reescribir con cwd fuera de proyecto (documento gestionado)
        lines = pi.read_text(encoding="utf-8").splitlines()
        header = json.loads(lines[0])
        header["cwd"] = "/Users/tester/.pencil/documents/uuid-1234"
        lines[0] = json.dumps(header)
        pi.write_text("\n".join(lines), encoding="utf-8")
        sp = self._processor_with_claude_cwd()
        sp._load_pencil_sessions(str(self.pencil_dir))
        s = sp.pencil_sessions[0]
        self.assertEqual(s["project"], "/Users/tester/dev/proj-app")
        self.assertEqual(s["match_rule"], "paths")

    def test_pencil_reports_generated(self):
        pi_name = "2026-09-08T00-00-00-000Z_abc.jsonl"
        self._write_pi_session(pi_name)
        self._write_desktop_session(pi_name)
        sp = self._processor_with_claude_cwd()
        sp._load_pencil_sessions(str(self.pencil_dir))
        sp._generate_pencil_report()
        sp._generate_pencil_models_report()
        r12 = self.output_dir / "12_pencil_sesiones_diseno.md"
        r13 = self.output_dir / "13_pencil_modelos_uso.md"
        self.assertTrue(r12.exists())
        self.assertTrue(r13.exists())
        c12 = r12.read_text(encoding="utf-8")
        self.assertIn("pinta el boton de azul", c12)
        self.assertNotIn("# Current App State", c12)
        self.assertIn("Boton azul", c12)
        c13 = r13.read_text(encoding="utf-8")
        self.assertIn("model-x", c13)


def _has_json1():
    import sqlite3
    try:
        con = sqlite3.connect(":memory:")
        con.execute("SELECT json_extract('{\"a\":1}','$.a')").fetchone()
        con.close()
        return True
    except Exception:
        return False


@unittest.skipUnless(_has_json1(), "sqlite3 sin soporte JSON1")
class TestOpenCodeIntegration(unittest.TestCase):
    """Fixture: opencode.db sintetico con la estructura session->message->part."""

    def setUp(self):
        import sqlite3
        self.temp_dir = tempfile.mkdtemp()
        self.input_dir = Path(self.temp_dir) / "sessions"
        self.output_dir = Path(self.temp_dir) / "reports"
        self.input_dir.mkdir(parents=True)
        self.opencode_dir = Path(self.temp_dir) / ".local/share/opencode"
        self.opencode_dir.mkdir(parents=True)
        self.db_path = self.opencode_dir / "opencode.db"

        def ms(h, m, s=0):
            # 2026-09-08T{h}:{m}:{s} UTC en epoch milisegundos
            from datetime import datetime, timezone
            return int(datetime(2026, 9, 8, h, m, s, tzinfo=timezone.utc).timestamp() * 1000)

        self.ms_start, self.ms_mid, self.ms_end = ms(10, 0), ms(10, 1), ms(10, 2)

        con = sqlite3.connect(str(self.db_path))
        con.executescript("""
            CREATE TABLE project (id TEXT PRIMARY KEY, worktree TEXT NOT NULL);
            CREATE TABLE session (id TEXT PRIMARY KEY, project_id TEXT, parent_id TEXT,
                slug TEXT, directory TEXT, title TEXT, agent TEXT, model TEXT,
                cost REAL DEFAULT 0, tokens_input INTEGER DEFAULT 0,
                tokens_output INTEGER DEFAULT 0, tokens_reasoning INTEGER DEFAULT 0,
                tokens_cache_read INTEGER DEFAULT 0, tokens_cache_write INTEGER DEFAULT 0,
                time_created INTEGER, time_updated INTEGER);
            CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT,
                time_created INTEGER, data TEXT);
            CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT,
                time_created INTEGER, data TEXT);
        """)
        con.execute("INSERT INTO project VALUES ('p1', '/Users/tester/dev/proj-app')")

        # sesión A: cwd subcarpeta del proyecto (raiz)
        con.execute(
            "INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ('sesA', 'p1', None, 'slug-a', '/Users/tester/dev/proj-app/sub',
             'Hero azul', 'build',
             '{"id":"model-x","providerID":"opencode-go","variant":"medium"}',
             0.003, 10, 20, 5, 0, 0, self.ms_start, self.ms_end))
        # sesión B: sub-agente de A
        con.execute(
            "INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ('sesB', 'p1', 'sesA', 'slug-b', '/Users/tester/dev/proj-app/sub',
             'explore tareas', 'explore',
             '{"id":"model-x","providerID":"opencode-go"}',
             0.001, 1, 2, 0, 0, 0, self.ms_mid, self.ms_mid + 1000))
        # sesión C: cwd fuera de todo proyecto, peros paths reales del proyecto
        con.execute(
            "INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ('sesC', 'p1', None, 'slug-c', '/Users/tester/.opencode-cache/uuid-9',
             'Parche suelto', 'build', '', 0.001, 3, 4, 0, 0, 0,
             self.ms_mid, self.ms_end))
        # sesión D: sin cwd ni paths útiles -> solo tiempo
        con.execute(
            "INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ('sesD', 'p1', None, 'slug-d', '/mnt/nada/xyz', 'Sin senales', 'build',
             '', 0, 0, 0, 0, 0, 0, self.ms_start, self.ms_end))

        msgs = [
            ('msgA1', 'sesA', self.ms_start, {"role": "user", "time": {"created": self.ms_start}}),
            ('msgA2', 'sesA', self.ms_mid, {"role": "assistant", "parentID": "msgA1",
                "modelID": "model-x", "providerID": "opencode-go", "variant": "medium",
                "cost": 0.003, "tokens": {"input": 10, "output": 20, "reasoning": 5},
                "time": {"created": self.ms_mid}, "finish": "stop"}),
            ('msgB1', 'sesB', self.ms_mid, {"role": "user", "time": {"created": self.ms_mid}}),
            ('msgB2', 'sesB', self.ms_mid, {"role": "assistant", "parentID": "msgB1",
                "modelID": "model-x", "providerID": "opencode-go", "cost": 0.001,
                "tokens": {"input": 1, "output": 2},
                "time": {"created": self.ms_mid},
                "error": {"name": "MessageAbortedError"}}),
            ('msgC1', 'sesC', self.ms_mid, {"role": "user", "time": {"created": self.ms_mid}}),
            ('msgD1', 'sesD', self.ms_start, {"role": "user", "time": {"created": self.ms_start}}),
        ]
        con.executemany("INSERT INTO message VALUES (?,?,?,?)",
                        [(i, s, t, json.dumps(d)) for i, s, t, d in msgs])
        parts = [
            ('prtA1', 'msgA1', 'sesA', json.dumps({"type": "text", "text": "pinta el hero de azul"})),
            ('prtA2', 'msgA1', 'sesA', json.dumps({"type": "text", "synthetic": True,
                "text": "<env>contexto inyectado AGENTS.md</env>"})),
            ('prtA3', 'msgA2', 'sesA', json.dumps({"type": "tool", "tool": "edit",
                "callID": "c1", "state": {"status": "completed", "input": {
                    "filePath": "/Users/tester/dev/proj-app/src/App.tsx"},
                    "output": "M" * 500000}})),
            ('prtA4', 'msgA2', 'sesA', json.dumps({"type": "patch", "hash": "h",
                "files": ["/Users/tester/dev/proj-app/src/App.tsx",
                           "/Users/tester/dev/proj-app/README.md"]})),
            ('prtA5', 'msgA2', 'sesA', json.dumps({"type": "text", "text": "Listo, hero azul."})),
            ('prtA6', 'msgA2', 'sesA', json.dumps({"type": "reasoning", "text": "penando..."})),
            ('prtB1', 'msgB1', 'sesB', json.dumps({"type": "text", "text": "busca los endpoints"})),
            ('prtC1', 'msgC1', 'sesC', json.dumps({"type": "tool", "tool": "write",
                "callID": "c9", "state": {"status": "completed", "input": {
                    "filePath": "/Users/tester/dev/proj-app/docs/parche.md"},
                    "output": "ok"}})),
        ]
        con.executemany("INSERT INTO part (id, message_id, session_id, data) VALUES (?,?,?,?)",
                        parts)
        con.commit()
        con.close()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _processor(self):
        sp = SessionProcessor(str(self.input_dir), str(self.output_dir))
        sp.user_messages.append({"cwd": "/Users/tester/dev/proj-app",
                                 "timestamp": "2026-09-08T10:00:00.000Z"})
        sp.assistant_responses.append({"cwd": "/Users/tester/dev/proj-app",
                                       "timestamp": "2026-09-08T10:01:30.000Z"})
        return sp

    def _load(self):
        sp = self._processor()
        sp._load_opencode_sessions(str(self.opencode_dir))
        return sp

    def test_parse_by_cwd_and_usage(self):
        sp = self._load()
        by_id = {s['session_id']: s for s in sp.opencode_sessions}
        a = by_id['sesA']
        self.assertEqual(a['project'], '/Users/tester/dev/proj-app')
        self.assertEqual(a['match_rule'], 'cwd')
        self.assertFalse(a['subagent'])
        self.assertEqual(a['title'], 'Hero azul')
        self.assertEqual(a['model'], 'opencode-go/model-x (medium)')
        # uso rollup desde columnas de session
        self.assertEqual(a['usage']['input'], 10)
        self.assertEqual(a['usage']['output'], 20)
        self.assertEqual(a['usage']['total'], 35)
        self.assertAlmostEqual(a['usage']['cost'], 0.003)
        # uso por modelo desde mensajes assistant
        self.assertEqual(a['models_used'], {'opencode-go/model-x (medium)': 1})
        self.assertEqual(a['model_usage']['opencode-go/model-x (medium)']['requests'], 1)
        # Q&A: prompt limpio (el synthetic se descarta) + respuesta
        self.assertEqual(len(a['qa_pairs']), 1)
        self.assertEqual(a['qa_pairs'][0]['user'], 'pinta el hero de azul')
        self.assertEqual(a['qa_pairs'][0]['assistant'], 'Listo, hero azul.')
        self.assertEqual(a['tool_calls'], {'edit': 1})
        self.assertIn('/Users/tester/dev/proj-app/src/App.tsx', a['external_paths'])
        self.assertIn('/Users/tester/dev/proj-app/README.md', a['external_paths'])

    def test_subagent_flag_and_errors(self):
        by_id = {s['session_id']: s for s in self._load().opencode_sessions}
        b = by_id['sesB']
        self.assertTrue(b['subagent'])
        self.assertEqual(b['project'], '/Users/tester/dev/proj-app')
        self.assertEqual(b['errors'], 1)
        self.assertEqual(b['qa_pairs'][0]['user'], 'busca los endpoints')

    def test_match_rule_paths_fallback(self):
        by_id = {s['session_id']: s for s in self._load().opencode_sessions}
        c = by_id['sesC']
        self.assertEqual(c['project'], '/Users/tester/dev/proj-app')
        self.assertEqual(c['match_rule'], 'paths')

    def test_match_rule_tiempo_fallback(self):
        by_id = {s['session_id']: s for s in self._load().opencode_sessions}
        d = by_id['sesD']
        self.assertEqual(d['project'], '/Users/tester/dev/proj-app')
        self.assertEqual(d['match_rule'], 'tiempo')

    def test_opencode_reports_generated(self):
        sp = self._load()
        sp._generate_opencode_report()
        sp._generate_opencode_models_report()
        r14 = self.output_dir / "14_opencode_sesiones.md"
        r15 = self.output_dir / "15_opencode_modelos_uso.md"
        self.assertTrue(r14.exists())
        self.assertTrue(r15.exists())
        c14 = r14.read_text(encoding="utf-8")
        self.assertIn("pinta el hero de azul", c14)
        self.assertIn("Listo, hero azul.", c14)
        self.assertNotIn("contexto inyectado", c14)
        self.assertIn("sub-agente", c14)
        self.assertIn("regla: `cwd`", c14)
        c15 = r15.read_text(encoding="utf-8")
        self.assertIn("opencode-go/model-x", c15)
        self.assertIn("`edit`", c15)

    def test_missing_db_degrades_quietly(self):
        sp = self._processor()
        sp._load_opencode_sessions(str(Path(self.temp_dir) / "inexistente"))
        self.assertEqual(sp.opencode_sessions, [])


class TestAntigravityIntegration(unittest.TestCase):
    """Fixture: ~/.gemini/antigravity-cli/conversations/*.db sinteticos con
    payloads protobuf wire-format reales (steps / gen_metadata / tmb)."""

    @staticmethod
    def _v(n):
        out = bytearray()
        while True:
            b = n & 0x7F
            n >>= 7
            if n:
                out.append(b | 0x80)
            else:
                out.append(b)
                return bytes(out)

    @classmethod
    def _tag(cls, fn, wt):
        return cls._v((fn << 3) | wt)

    @classmethod
    def _tf(cls, fn, data):
        return cls._tag(fn, 2) + cls._v(len(data)) + data

    @classmethod
    def _vf(cls, fn, v):
        return cls._tag(fn, 0) + cls._v(v)

    def _env(self, sec, usage=None):
        e = self._tf(1, self._vf(1, sec) + self._vf(2, 500000000))
        if usage:
            e += self._tf(9, usage)
        return e

    def _user_step(self, sec, text, workspace=None):
        payload = self._tf(2, text.encode('utf-8'))
        if workspace:
            payload += self._tf(12, self._tf(12, workspace.encode('utf-8')))
        return (self._vf(1, 14) + self._vf(4, 3) + self._tf(5, self._env(sec))
                + self._tf(19, payload))

    def _agent_step(self, sec, answer=None, calls=None, usage=None):
        payload = b''
        if answer:
            payload += self._tf(1, answer.encode('utf-8'))
        for name, args in (calls or []):
            payload += self._tf(7, self._vf(1, 0) + self._tf(2, name.encode())
                                + self._tf(3, args.encode('utf-8')))
        return (self._vf(1, 15) + self._vf(4, 3) + self._tf(5, self._env(sec, usage))
                + self._tf(20, payload))

    def _tool_result_step(self, sec, tool='write_file', output='X' * 4096):
        return (self._vf(1, 132) + self._vf(4, 3) + self._tf(5, self._env(sec))
                + self._tf(140, self._tf(2, output.encode('utf-8'))))

    def _gen(self, model, out, ctx, reas):
        usage = self._vf(3, out) + self._vf(5, ctx) + self._vf(9, reas)
        return self._tf(1, self._tf(19, model.encode('utf-8')) + self._tf(4, usage))

    def _make_db(self, path, tmb_uri=None, steps=None, gens=None):
        import sqlite3
        con = sqlite3.connect(str(path))
        con.executescript("""
            CREATE TABLE steps (idx integer PRIMARY KEY, step_type integer,
                status integer, step_payload blob);
            CREATE TABLE gen_metadata (idx integer PRIMARY KEY, data blob);
            CREATE TABLE trajectory_metadata_blob (id text PRIMARY KEY, data blob);
        """)
        if tmb_uri:
            con.execute("INSERT INTO trajectory_metadata_blob VALUES ('main', ?)",
                        (self._tf(1, self._tf(1, tmb_uri.encode('utf-8'))),))
        for i, (stype, payload) in enumerate(steps or []):
            con.execute("INSERT INTO steps VALUES (?,?,?,?)", (i, stype, 3, payload))
        for i, g in enumerate(gens or []):
            con.execute("INSERT INTO gen_metadata VALUES (?,?)", (i, g))
        con.commit()
        con.close()

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.input_dir = Path(self.temp_dir) / "sessions"
        self.output_dir = Path(self.temp_dir) / "reports"
        self.input_dir.mkdir(parents=True)
        self.agy_dir = Path(self.temp_dir) / ".gemini/antigravity-cli"
        self.conv_dir = self.agy_dir / "conversations"
        self.conv_dir.mkdir(parents=True)
        (self.agy_dir / "cache").mkdir(parents=True)

        from datetime import datetime, timezone
        def sec(h, m, s=0):
            return int(datetime(2026, 9, 8, h, m, s, tzinfo=timezone.utc).timestamp())

        # convA: workspace real del proyecto (regla cwd) + Q&A + tools + usage
        self._make_db(
            self.conv_dir / "convA.db",
            tmb_uri="file:///Users/tester/dev/proj-app",
            steps=[
                (14, self._user_step(sec(10, 0), "rediseña el hero")),
                (15, self._agent_step(sec(10, 1), calls=[
                    ("write_file", '{"AbsolutePath":"/Users/tester/dev/proj-app/src/Hero.tsx","Content":"x"}')])),
                (132, self._tool_result_step(sec(10, 1))),
                (15, self._agent_step(sec(10, 2), answer="Listo, hero nuevo.")),
            ],
            gens=[self._gen("gemini-3.8-flash", 800, 20000, 100),
                  self._gen("gemini-3.8-flash", 50, 20500, 0)])

        # convB: workspace fuera de todo proyecto, pero tool calls apuntan al proyecto
        self._make_db(
            self.conv_dir / "convB.db",
            tmb_uri="file:///Users/tester/.agy-cache/scratch-1",
            steps=[
                (14, self._user_step(sec(11, 0), "arregla el bug")),
                (15, self._agent_step(sec(11, 1), answer="Parche aplicado.", calls=[
                    ("view_file", '{"AbsolutePath":"/Users/tester/dev/proj-app/docs/bug.md"}')])),
            ],
            gens=[self._gen("gemini-3.8-flash", 30, 9000, 5)])

        # convC: sin workspace ni paths útiles -> solo tiempo
        self._make_db(
            self.conv_dir / "convC.db",
            steps=[
                (14, self._user_step(sec(10, 59), "hola")),
                (15, self._agent_step(sec(11, 1), answer="hi")),
            ])

        # convD: base vacía (sin steps) -> se degrada, no rompe
        self._make_db(self.conv_dir / "convD.db")

        with open(self.agy_dir / "cache" / "conversation_metadata.json", 'w') as f:
            json.dump({"conversations": {
                "convA": {"summary": {"ID": "convA", "Preview": "Rediseño de Hero"}}}},
                f)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _load(self):
        sp = SessionProcessor(str(self.input_dir), str(self.output_dir))
        sp.user_messages.append({"cwd": "/Users/tester/dev/proj-app",
                                 "timestamp": "2026-09-08T10:00:00.000Z"})
        sp.assistant_responses.append({"cwd": "/Users/tester/dev/proj-app",
                                       "timestamp": "2026-09-08T11:00:30.000Z"})
        sp._load_antigravity_sessions(str(self.agy_dir))
        return sp

    def test_parse_by_cwd_and_usage(self):
        by_id = {s['session_id']: s for s in self._load().antigravity_sessions}
        a = by_id['convA']
        self.assertEqual(a['project'], '/Users/tester/dev/proj-app')
        self.assertEqual(a['match_rule'], 'cwd')
        self.assertEqual(a['cwd'], '/Users/tester/dev/proj-app')
        self.assertEqual(a['title'], 'Rediseño de Hero')
        self.assertEqual(a['usage']['input'], 40500)
        self.assertEqual(a['usage']['output'], 850)
        self.assertEqual(a['usage']['reasoning'], 100)
        self.assertEqual(a['usage']['total'], 41350)
        self.assertEqual(a['models_used'], {'gemini-3.8-flash': 2})
        self.assertEqual(a['model_usage']['gemini-3.8-flash']['requests'], 2)
        self.assertEqual(len(a['qa_pairs']), 1)
        self.assertEqual(a['qa_pairs'][0]['user'], 'rediseña el hero')
        self.assertEqual(a['qa_pairs'][0]['assistant'], 'Listo, hero nuevo.')
        self.assertEqual(a['tool_calls'], {'write_file': 1})
        self.assertIn('/Users/tester/dev/proj-app/src/Hero.tsx', a['external_paths'])

    def test_match_rule_paths_fallback(self):
        by_id = {s['session_id']: s for s in self._load().antigravity_sessions}
        b = by_id['convB']
        self.assertEqual(b['project'], '/Users/tester/dev/proj-app')
        self.assertEqual(b['match_rule'], 'paths')

    def test_match_rule_tiempo_fallback(self):
        by_id = {s['session_id']: s for s in self._load().antigravity_sessions}
        c = by_id['convC']
        self.assertEqual(c['project'], '/Users/tester/dev/proj-app')
        self.assertEqual(c['match_rule'], 'tiempo')

    def test_empty_db_skipped(self):
        ids = {s['session_id'] for s in self._load().antigravity_sessions}
        self.assertNotIn('convD', ids)

    def test_title_falls_back_to_first_prompt(self):
        by_id = {s['session_id']: s for s in self._load().antigravity_sessions}
        self.assertEqual(by_id['convC']['title'], 'hola')

    def test_antigravity_reports_generated(self):
        sp = self._load()
        sp._generate_antigravity_report()
        sp._generate_antigravity_models_report()
        r16 = self.output_dir / "16_antigravity_sesiones.md"
        r17 = self.output_dir / "17_antigravity_modelos_uso.md"
        self.assertTrue(r16.exists())
        self.assertTrue(r17.exists())
        c16 = r16.read_text(encoding="utf-8")
        self.assertIn("rediseña el hero", c16)
        self.assertIn("Listo, hero nuevo.", c16)
        self.assertIn("regla: `cwd`", c16)
        self.assertIn("regla: `paths`", c16)
        self.assertIn("regla: `tiempo`", c16)
        c17 = c17 = r17.read_text(encoding="utf-8")
        self.assertIn("gemini-3.8-flash", c17)
        self.assertIn("`write_file`", c17)

    def test_missing_dir_degrades_quietly(self):
        sp = SessionProcessor(str(self.input_dir), str(self.output_dir))
        sp._load_antigravity_sessions(str(Path(self.temp_dir) / "inexistente"))
        self.assertEqual(sp.antigravity_sessions, [])

    def test_summary_report_includes_external_agents(self):
        sp = self._load()
        sp._generate_sessions_summary()
        r00 = (self.output_dir / "00_resumen_sesiones.md").read_text(encoding="utf-8")
        self.assertIn("Agentes externos", r00)
        self.assertIn("Antigravity CLI", r00)
        self.assertIn("proyecto Claude: 3", r00)


if __name__ == "__main__":
    unittest.main()

