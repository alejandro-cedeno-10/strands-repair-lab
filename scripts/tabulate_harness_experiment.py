"""Tabulate the A/B harness experiment (A: harness defaults off, B: on) from runs/.

Run from the repository root: python scripts/tabulate_harness_experiment.py [log]
The log has one line per run: `arm=<A|B> rep=<n> wall=<s> {launcher JSON}`; default runs/harness-experiment.log.
Prices: AWS Price List, Claude Sonnet 4.6 Global in us-east-1, USD per million tokens.
"""
import json
import re
import statistics
import sys
from pathlib import Path

PRICE = {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write_5m": 3.75}
DEFAULT_LOG = Path("runs/harness-experiment.log")


def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def usage_totals(run):
    agent = load(run / "agent.json", {})
    totals = dict(agent.get("usage") or {})
    for review in load(run / "reviewer.json", []):
        for key, value in (review.get("usage") or {}).items():
            if isinstance(value, (int, float)):
                totals[key] = totals.get(key, 0) + value
    return totals


def row(arm, rep, run_id):
    run = Path("runs") / run_id
    manifest = load(run / "manifest.json", {})
    heldout = load(run / "heldout.json", {})
    usage = usage_totals(run)
    uncached, output = usage.get("inputTokens", 0), usage.get("outputTokens", 0)
    read, write = usage.get("cacheReadInputTokens", 0), usage.get("cacheWriteInputTokens", 0)
    cost = (uncached * PRICE["input"] + output * PRICE["output"] + read * PRICE["cache_read"]
            + write * PRICE["cache_write_5m"]) / 1e6
    return {"arm": arm, "rep": rep, "run_id": run_id, "status": manifest.get("status"),
            "heldout": f"{heldout.get('passed')}/{heldout.get('total')}", "model_calls": manifest.get("model_hook_attempts"),
            "inputTokens_uncached": uncached, "cacheReadInputTokens": read, "cacheWriteInputTokens": write,
            "outputTokens": output, "cost_usd_est": round(cost, 4), "elapsed_s": manifest.get("elapsed_seconds")}


def main():
    log = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LOG
    rows = []
    for line in log.read_text(encoding="utf-8").splitlines():
        match = re.match(r"arm=(\w) rep=(\d) wall=\d+ (\{.*\})", line)
        if match:
            rows.append(row(match[1], int(match[2]), json.loads(match[3])["run_id"]))
    summary = {"pricing_usd_per_1M": PRICE, "runs": rows}
    for arm in "AB":
        costs = [r["cost_usd_est"] for r in rows if r["arm"] == arm]
        summary["arm_" + arm] = {"harness_defaults": arm == "B", "n": len(costs), "cost_mean": round(statistics.mean(costs), 4),
                                 "cost_min": min(costs), "cost_max": max(costs)}
    summary["cost_reduction_mean_pct"] = round(100 * (1 - summary["arm_B"]["cost_mean"] / summary["arm_A"]["cost_mean"]), 1)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
