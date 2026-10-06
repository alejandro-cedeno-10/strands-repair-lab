"""Runs only the original and reference code written by the lab author, never arbitrary patches."""
import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
import sys
from pathlib import Path

from grader.oracle import expected
from repairlab.scenario import exercise
from grader.reference_solution import request_with_retry as reference
from grader.cases import hidden_cases
from grader.verify import evaluate
from repairlab.workspace import ROOT, EDITABLE, Workspace, digest
from repairlab.sandbox import DockerRunner, bounded_process, SandboxError

BUG_FILE = ROOT / "fixtures/repo/src/http_client.py"
REF_FILE = ROOT / "grader/reference_solution.py"
spec = importlib.util.spec_from_file_location("known_original", BUG_FILE)
known_original = importlib.util.module_from_spec(spec)
spec.loader.exec_module(known_original)


class TrustedControlsRunner:
    """Offline double: recognizes exactly two known sources and rejects any other code."""
    def invoke(self, source, case):
        content = (source / "http_client.py").read_bytes()
        functions = {BUG_FILE.read_bytes(): known_original.request_with_retry, REF_FILE.read_bytes(): reference}
        if content not in functions:
            raise RuntimeError("The offline double never executes arbitrary code")
        data = copy.deepcopy(case["input"])
        original = copy.deepcopy(data)
        result = exercise(functions[content], data)
        return {"result": result, "inputs_unchanged": data == original}


class Controls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ws = Workspace(Path(self.temp.name) / "run", TrustedControlsRunner())

    def repair(self):
        self.ws.run_tests()
        self.ws.replace_text(EDITABLE, digest(self.ws.path(EDITABLE)), self.ws.original_source, REF_FILE.read_text())

    def test_red_then_green_reference(self):
        before = json.loads(self.ws.run_tests())
        self.assertEqual(before["status"], "FAIL")
        self.repair()
        after = json.loads(self.ws.run_tests())
        self.assertEqual(after["status"], "PASS")
        self.ws.submit_patch("Human reference control; not an LLM result")
        self.assertTrue((self.ws.output / "candidate.patch").exists())

    def test_reference_passes_external_cases(self):
        self.repair()
        result = evaluate(TrustedControlsRunner(), self.ws.repo / "src", hidden_cases(7))
        self.assertEqual(result["status"], "PASS")

    def test_path_traversal_rejected(self):
        for path in ("../grader/reference_solution.py", "/etc/passwd", "grader/oracle.py", "src/../README.md"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.ws.read_file(path)

    def test_tests_cannot_be_edited(self):
        self.ws.run_tests()
        with self.assertRaises(ValueError):
            self.ws.replace_text("tests/public_cases.json", "x", "old", "new")

    def test_reproduction_required(self):
        with self.assertRaises(ValueError):
            self.ws.replace_text(EDITABLE, digest(self.ws.path(EDITABLE)), self.ws.original_source, REF_FILE.read_text())

    def test_stale_hash_rejected(self):
        self.ws.run_tests()
        with self.assertRaises(ValueError):
            self.ws.replace_text(EDITABLE, "outdated", self.ws.original_source, REF_FILE.read_text())

    def test_green_before_edit_is_not_enough(self):
        self.repair()
        with self.assertRaises(ValueError):
            self.ws.submit_patch("New version not tested")

    def test_no_edit_control(self):
        self.ws.allow_edits = False
        with self.assertRaises(ValueError):
            self.repair()

    def test_strict_output_types(self):
        class WrongTypes:
            def invoke(self, source, case):
                return {"result": True, "inputs_unchanged": True}
        self.assertEqual(evaluate(WrongTypes(), Path("unused"), hidden_cases(7)[:1])["status"], "FAIL")

    def test_retry_contract_matrix(self):
        for c in hidden_cases(42):
            with self.subTest(c["name"]):
                self.assertEqual(exercise(reference,c["input"]),expected(c["input"]))

    def test_bytecode_not_exposed_to_agent(self):
        self.assertFalse(any(name.endswith(".pyc") or "__pycache__" in name for name in json.loads(self.ws.list_files())))

    def test_heldout_rejects_denylist_and_open_status_range(self):
        def loose(method, send, max_attempts=3, sleep=lambda seconds: None):
            if type(max_attempts) is not int or not 1 <= max_attempts <= 5:
                raise ValueError("max_attempts")
            for attempt in range(max_attempts):
                response = send(method)
                transient = response["status"] == 429 or response["status"] >= 502
                if method in {"POST", "PATCH"} or not transient or attempt + 1 == max_attempts:
                    return response
                sleep(min(0.1 * 2 ** attempt, 0.4))
        failing = {c["name"] for c in hidden_cases(42) if exercise(loose, c["input"]) != expected(c["input"])}
        self.assertTrue({"unlisted-method-TRACE", "unlisted-status-505"} <= failing)
        self.assertFalse(any(name.startswith("matrix-") for name in failing))

    def test_docker_restricts_execution(self):
        cmd = DockerRunner("sha256:"+"a"*64).command(Path("."),"probe")
        self.assertIn("--read-only",cmd)
        self.assertEqual(cmd[cmd.index("--network")+1],"none")
        self.assertNotIn("--privileged",cmd)

if __name__ == "__main__":
    unittest.main()
