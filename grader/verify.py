"""Comparison outside the container. Expectations are never sent to the candidate."""
from pathlib import Path
import json
from grader.oracle import expected


def evaluate(runner, source: Path, cases: list[dict]) -> dict:
    rows = []
    for case in cases:
        actual = runner.invoke(source, case)
        wanted = expected(case["input"])
        try:
            same_result = json.dumps(actual.get("result"), sort_keys=True, allow_nan=False) == json.dumps(wanted, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError):
            same_result = False
        passed = "candidate_error" not in actual and actual.get("inputs_unchanged") is True and same_result
        rows.append({"name": case["name"], "pass": passed, "expected": wanted, "actual": actual})
    return {"status": "PASS" if rows and all(r["pass"] for r in rows) else "FAIL",
            "passed": sum(r["pass"] for r in rows), "total": len(rows), "cases": rows}
