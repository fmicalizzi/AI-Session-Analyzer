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


if __name__ == "__main__":
    unittest.main()
