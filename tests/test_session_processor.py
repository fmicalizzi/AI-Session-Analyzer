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


if __name__ == "__main__":
    unittest.main()
