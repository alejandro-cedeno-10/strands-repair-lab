"""Experiment deadline and cleanup of its labeled containers."""
import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--deadline", type=int, default=900)
    a, extra = p.parse_known_args()
    if not 60 <= a.deadline <= 1800:
        p.error("deadline must be between 60 and 1800 seconds")
    if any(x == "--out" or x.startswith("--out=") or x == "--run-id" or x.startswith("--run-id=") for x in extra):
        p.error("The launcher manages --out and --run-id")
    run_id = uuid.uuid4().hex
    logs = Path("runs") / ("launcher-" + run_id)
    logs.mkdir(parents=True)
    outcome = {"run_id": run_id, "deadline": a.deadline}
    try:
        with (logs / "stdout.txt").open("w", encoding="utf-8") as stdout, (logs / "stderr.txt").open("w", encoding="utf-8") as stderr:
            r = subprocess.run([sys.executable, "-m", "repairlab.run", "--run-id", run_id, *extra],
                               stdout=stdout, stderr=stderr, timeout=a.deadline)
            outcome["exit_code"] = r.returncode
    except subprocess.TimeoutExpired:
        outcome.update(exit_code=124, status="TIMEOUT_PARTIAL_EVIDENCE")
    finally:
        try:
            listing = subprocess.run(["docker", "ps", "-aq", "--filter", "label=repairlab.run=" + run_id],
                                     capture_output=True, text=True, timeout=15, check=True)
            ids = listing.stdout.split()
            if ids:
                subprocess.run(["docker", "rm", "-f", *ids], capture_output=True, timeout=20, check=True)
        except Exception as e:
            outcome["cleanup_error"] = str(e)
        (logs / "launcher.json").write_text(json.dumps(outcome, indent=2), encoding="utf-8")
    print(json.dumps({**outcome, "logs": str(logs), "evidence": "runs/" + run_id}))
    return outcome.get("exit_code", 2)


if __name__ == "__main__":
    raise SystemExit(main())
