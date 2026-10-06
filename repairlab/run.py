"""Orchestrates evidence and verification; never imports the candidate patch on the host."""
import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import secrets
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from grader.cases import hidden_cases
from grader.verify import evaluate
from repairlab.sandbox import DockerRunner
from repairlab.workspace import BYTECODE, ROOT, TASK, Workspace, EDITABLE, digest, write_json


def converse(agent, manifest):
    """A max_tokens cutoff is model behavior: it is recorded and the proposal is still verified."""
    from strands.types.exceptions import MaxTokensReachedException
    try:
        return agent(f"Investigate {TASK['issue']} and honor the repository contract. "
                     "Reproduce the failure, decide the fix, verify it and submit the diff for review.")
    except MaxTokensReachedException as error:
        manifest["agent_termination"] = {"type": type(error).__name__, "message": str(error)[:2000]}
        return None


def main():
    """Run one repair attempt.

    There is no host fallback without Docker. aws_invoked records an attempt; the metrics tell whether it
    finished. Verification uses a snapshot taken outside the tools, so the model can no longer modify or
    query the verdict.
    """
    p = argparse.ArgumentParser()
    p.add_argument("--image", default=os.getenv("REPAIR_IMAGE"))
    p.add_argument("--model-id", default=os.getenv("BEDROCK_MODEL_ID"))
    p.add_argument("--profile", default=os.getenv("AWS_PROFILE"))
    p.add_argument("--region", default=os.getenv("AWS_REGION", "us-east-1"))
    p.add_argument("--allow-aws", action="store_true")
    p.add_argument("--no-reviewer", action="store_true")
    p.add_argument("--no-edit", action="store_true")
    p.add_argument("--max-calls", type=int, default=24)
    p.add_argument("--harness-defaults", action="store_true")
    p.add_argument("--out", default="runs")
    p.add_argument("--run-id", default=uuid.uuid4().hex)
    a = p.parse_args()
    if not a.allow_aws or not a.model_id or not a.image:
        p.error("Requires --allow-aws, BEDROCK_MODEL_ID and REPAIR_IMAGE")
    if not 1 <= a.max_calls <= 40 or not a.run_id.isalnum():
        p.error("max-calls must be between 1 and 40; run-id must be alphanumeric")
    runner = DockerRunner(a.image)
    runner.run_id = a.run_id
    sandbox = runner.preflight()
    out = Path(a.out) / a.run_id
    ws = Workspace(out, runner, allow_edits=not a.no_edit)
    manifest = {"status": "STARTED", "date_utc": datetime.now(timezone.utc).isoformat(),
        "task": TASK, "synthetic_repository": True, "aws_invoked": False, "model": a.model_id, "region": a.region,
        "sandbox": sandbox, "python": platform.python_version(), "no_edit": a.no_edit,
        "no_reviewer": a.no_reviewer, "max_calls": a.max_calls, "harness_defaults": a.harness_defaults,
        "versions": {n: importlib.metadata.version(n) for n in ("strands-harness", "strands-agents", "boto3")},
        "source_hashes": {str(f.relative_to(ROOT)): digest(f) for d in ("repairlab", "grader", "fixtures")
                          for f in (ROOT / d).rglob("*") if f.is_file() and f.suffix in (".py", ".json", ".md")}}
    write_json(ws.output / "manifest.json", manifest)
    agent, result, reviews, budget = None, None, [], None
    began = time.monotonic()
    try:
        baseline = json.loads(ws.run_tests())
        manifest["baseline_status"] = baseline["status"]
        if baseline["status"] != "FAIL":
            raise RuntimeError("The baseline does not fail: there is no valid repair experiment")
        from repairlab.agent import Budget, build, model_for
        budget = Budget(a.max_calls)
        model = model_for(a.model_id, a.region, a.profile, caching=a.harness_defaults)
        agent, reviews = build(ws, model, budget, not a.no_reviewer, harness_defaults=a.harness_defaults)
        manifest["agent_tools"] = sorted(agent.tool_registry.registry)
        manifest["aws_invoked"] = True
        result = converse(agent, manifest)
        manifest["terminated_by_budget"] = budget.blocked
        snapshot = ws.output / "verification-snapshot"
        shutil.copytree(ws.repo / "src", snapshot, ignore=BYTECODE)
        seed = secrets.randbits(64)
        cases = hidden_cases(seed)
        write_json(ws.output / "heldout-inputs.json", {"seed": seed, "cases": cases})
        heldout = evaluate(runner, snapshot, cases)
        write_json(ws.output / "heldout.json", heldout)
        checks = {
            "baseline_failed": baseline["status"] == "FAIL",
            "submitted": ws.submitted is not None,
            "source_changed": digest(ws.path(EDITABLE)) != ws.original[EDITABLE],
            "protected_files_unchanged": ws.unchanged_protected_files(),
            "submitted_hash_matches": bool(ws.submitted) and ws.submitted["source_sha256"] == digest(snapshot / "http_client.py"),
            "public_tests_passed": bool(ws.last_tests) and ws.last_tests["status"] == "PASS",
            "heldout_passed": heldout["status"] == "PASS",
            "normal_stop": result is not None and str(result.stop_reason) == "end_turn" and not budget.blocked,
            "within_budget": not budget.blocked,
        }
        manifest["status"] = "VERIFIED_CANDIDATE" if all(checks.values()) else "REJECTED"
        write_json(ws.output / "verdict.json", {"status": manifest["status"], "checks": checks,
                                                "human_review": "REQUIRED_BEFORE_MERGE"})
    except Exception as e:
        manifest["status"] = "ERROR"
        manifest["error"] = {"type": type(e).__name__, "message": str(e)}
    finally:
        manifest["elapsed_seconds"] = round(time.monotonic() - began, 3)
        manifest["model_hook_attempts"] = budget.calls if budget else 0
        manifest["tool_hook_attempts"] = budget.tools if budget else 0
        write_json(ws.output / "manifest.json", manifest)
        write_json(ws.output / "reviewer.json", reviews)
        write_json(ws.output / "agent.json", {"messages": agent.messages if agent else [],
            "final": str(result) if result else None,
            "final_synthesized_by_budget_cancel": bool(budget and budget.blocked),
            "usage": dict(result.metrics.accumulated_usage) if result else None})
        (ws.output / "current.patch").write_text(ws.diff(), encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "evidence": str(ws.output)}))
    return 0 if manifest["status"] == "VERIFIED_CANDIDATE" else (1 if manifest["status"] == "REJECTED" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
