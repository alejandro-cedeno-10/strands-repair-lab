"""Descriptive summary of runs; not a benchmark or a bill."""
import argparse
import json
from collections import Counter
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("root", nargs="?", default="runs")
    a = p.parse_args()
    summary = []
    for path in sorted(Path(a.root).rglob("manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        usage = Counter()
        complete = True
        for file in (path.parent / "agent.json", path.parent / "reviewer.json"):
            if not file.exists():
                complete = False
                continue
            records = json.loads(file.read_text(encoding="utf-8"))
            for record in records if isinstance(records, list) else [records]:
                if record.get("usage") is None:
                    complete = False
                for key, value in (record.get("usage") or {}).items():
                    if isinstance(value, (int, float)):
                        usage[key] += value
        summary.append({"run": str(path.parent), "status": manifest["status"],
            "model": manifest["model"], "region": manifest["region"],
            "seconds": manifest.get("elapsed_seconds"), "model_attempts": manifest.get("model_hook_attempts"),
            "reported_usage": dict(usage), "usage_available_for_completed_results": complete,
            "billing_reconciled": False})
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
