"""Real Docker controls without Bedrock. Run before the agent."""
import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from grader.cases import hidden_cases
from grader.verify import evaluate
from repairlab.sandbox import DockerRunner
from repairlab.workspace import ROOT, write_json


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--image", default=os.getenv("REPAIR_IMAGE"))
    p.add_argument("--out", default="runs/sandbox-check.json")
    a = p.parse_args()
    if not a.image:
        p.error("Set REPAIR_IMAGE")
    out = Path(a.out)
    if out.exists():
        p.error("Use a new path to preserve existing evidence")
    runner = DockerRunner(a.image)
    checks = {"environment": runner.preflight()}
    cases = json.loads((ROOT / "fixtures/repo/tests/public_cases.json").read_text()) + hidden_cases(12345, count=2)
    with tempfile.TemporaryDirectory(prefix="repair-controls-") as temp:
        src = Path(temp) / "src"
        src.mkdir(mode=0o755)
        target = src / "http_client.py"
        shutil.copyfile(ROOT / "fixtures/repo/src/http_client.py", target)
        checks["broken_control"] = evaluate(runner, src, cases)
        shutil.copyfile(ROOT / "grader/reference_solution.py", target)
        checks["reference_control"] = evaluate(runner, src, cases)
        target.write_text("import os\ndef request_with_retry(method, send, max_attempts=3, sleep=None):\n    os._exit(0)\n")
        checks["false_green_control"] = evaluate(runner, src, cases[:1])
        target.write_text('''import os
def request_with_retry(method, send, max_attempts=3, sleep=None):
    try:
        open('/candidate/not-allowed', 'w').write('x')
        readonly = False
    except OSError:
        readonly = True
    return {'readonly': readonly, 'uid': os.getuid(),
            'aws_env_absent': not any(k.startswith('AWS_') for k in os.environ),
            'grader_not_mounted': not os.path.exists('/grader')}
''')
        probe = runner.invoke(src, cases[0])
        checks["boundary_probe"] = probe
    expected_probe = {"readonly": True, "uid": 65534, "aws_env_absent": True, "grader_not_mounted": True}
    passed = checks["broken_control"]["status"] == "FAIL" and checks["reference_control"]["status"] == "PASS" and checks["false_green_control"]["status"] == "FAIL" and probe.get("result", {}).get("response") == expected_probe
    checks["status"] = "PASS" if passed else "FAIL"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(out, checks)
    print(json.dumps({"status": checks["status"], "evidence": str(out)}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
