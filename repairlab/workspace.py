"""Tools with allow-listed paths, hash-checked edits and persistent evidence."""
from __future__ import annotations

import ast
import difflib
import hashlib
import json
import shutil
import threading
from pathlib import Path

from grader.verify import evaluate

ROOT = Path(__file__).resolve().parents[1]
TASK = json.loads((ROOT / "task.json").read_text())
EDITABLE = TASK["editable"]
BYTECODE = shutil.ignore_patterns("__pycache__", "*.pyc")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


class Workspace:
    def __init__(self, output: Path, runner, allow_edits: bool = True):
        self.output = output.resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        self.repo = self.output / "worktree"
        shutil.copytree(ROOT / TASK["repository"], self.repo, ignore=BYTECODE)
        self.allowed = {p.relative_to(self.repo).as_posix() for p in self.repo.rglob("*") if p.is_file()}
        self.original = {p: digest(self.repo / p) for p in self.allowed}
        self.original_source = (self.repo / EDITABLE).read_text(encoding="utf-8")
        self.runner, self.allow_edits = runner, allow_edits
        self.lock = threading.RLock()
        self.baseline = None
        self.last_tests = None
        self.submitted = None
        self.events = []
        self.test_runs = 0
        self.edits = 0
        self.public_cases = json.loads((self.repo / TASK["public_cases"]).read_text())

    def event(self, kind, **data):
        with self.lock:
            self.events.append({"sequence": len(self.events) + 1, "kind": kind, **data})
            write_json(self.output / "events.json", self.events)

    def path(self, name: str) -> Path:
        if name not in self.allowed:
            raise ValueError("Path is not in the allow list")
        p = self.repo / name
        if p.is_symlink() or self.repo not in p.resolve().parents:
            raise ValueError("Path not allowed")
        return p

    def list_files(self) -> str:
        return json.dumps(sorted(self.allowed))

    def read_file(self, name: str) -> str:
        with self.lock:
            p = self.path(name)
            self.event("read", path=name)
            return json.dumps({"path": name, "sha256": digest(p), "content": p.read_text(encoding="utf-8")}, ensure_ascii=False)

    def diff(self) -> str:
        with self.lock:
            return "".join(difflib.unified_diff(self.original_source.splitlines(keepends=True),
                self.path(EDITABLE).read_text(encoding="utf-8").splitlines(keepends=True),
                fromfile="a/" + EDITABLE, tofile="b/" + EDITABLE))

    def run_tests(self) -> str:
        with self.lock:
            if self.test_runs >= 6:
                raise ValueError("Limit of six public test runs reached")
            self.test_runs += 1
            sha = digest(self.path(EDITABLE))
            result = evaluate(self.runner, self.repo / "src", self.public_cases)
            result["source_sha256"] = sha
            write_json(self.output / f"public-{self.test_runs:02}.json", result)
            if self.baseline is None:
                self.baseline = result
            self.last_tests = result
            self.event("public_tests", status=result["status"], source_sha256=sha)
            return json.dumps(result, ensure_ascii=False)

    def replace_text(self, path: str, expected_sha256: str, old: str, new: str) -> str:
        """Apply one exact replacement; the result is only parsed with ast, never executed."""
        with self.lock:
            if not self.allow_edits:
                raise ValueError("Edits are disabled for the negative control")
            if self.submitted:
                raise ValueError("The patch was already submitted")
            if path != EDITABLE:
                raise ValueError("Only this file may be edited: " + EDITABLE)
            if self.baseline is None or self.baseline["status"] != "FAIL":
                raise ValueError("Reproduce the failure with run_tests first")
            if self.edits >= 8:
                raise ValueError("Limit of eight edits reached")
            p = self.path(path)
            current = p.read_text(encoding="utf-8")
            if digest(p) != expected_sha256:
                raise ValueError("Stale hash: read the file again")
            if not old or current.count(old) != 1:
                raise ValueError("old must match exactly one occurrence")
            updated = current.replace(old, new, 1)
            if len(updated.encode()) > 32768:
                raise ValueError("File too large")
            ast.parse(updated)
            if not updated.endswith("\n"):
                updated += "\n"
            p.write_text(updated, encoding="utf-8", newline="\n")
            self.edits += 1
            self.last_tests = None
            self.event("edit", path=path, before=expected_sha256, after=digest(p))
            return json.dumps({"sha256": digest(p), "requires_test": True})

    def unchanged_protected_files(self) -> bool:
        return all(digest(self.path(p)) == sha for p, sha in self.original.items() if p != EDITABLE)

    def submit_patch(self, explanation: str) -> str:
        with self.lock:
            sha = digest(self.path(EDITABLE))
            if not explanation.strip() or len(explanation) > 12000:
                raise ValueError("Explain the cause, the change and the limits")
            if not self.diff() or not self.unchanged_protected_files():
                raise ValueError("No valid patch, or a protected file changed")
            if not self.last_tests or self.last_tests["status"] != "PASS" or self.last_tests["source_sha256"] != sha:
                raise ValueError("Run green public tests on the current version")
            self.submitted = {"source_sha256": sha, "explanation": explanation,
                              "status": "PROPOSED_PENDING_INDEPENDENT_VERIFICATION"}
            write_json(self.output / "submission.json", self.submitted)
            (self.output / "candidate.patch").write_text(self.diff(), encoding="utf-8")
            self.event("submit", source_sha256=sha)
            return json.dumps(self.submitted)
