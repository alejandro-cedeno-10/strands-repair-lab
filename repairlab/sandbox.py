"""Custom bounded backend: exposes no free shell and never runs the candidate on the host."""
from __future__ import annotations

import json
import re
import subprocess
import threading
import uuid
from pathlib import Path


class SandboxError(RuntimeError):
    pass


CANDIDATE_LIMITS = {"TimeoutExpired", "OUTPUT_LIMIT"}


def bounded_process(cmd: list[str], payload: str = "", timeout: int = 20, limit: int = 131072):
    """Bounded capture: shell=False, a time budget and a combined output limit."""
    if len(payload.encode()) > 32768:
        raise SandboxError("Case input exceeds 32 KiB")
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    lock, overflow = threading.Lock(), threading.Event()

    def consume(stream, name):
        while chunk := stream.read(4096):
            with lock:
                available = max(0, limit - sum(map(len, buffers.values())))
                buffers[name].extend(chunk[:available])
                if len(chunk) > available:
                    overflow.set()
                    p.kill()
                    break

    readers = [threading.Thread(target=consume, args=(p.stdout, "stdout"), daemon=True),
               threading.Thread(target=consume, args=(p.stderr, "stderr"), daemon=True)]
    def send_input():
        try:
            p.stdin.write(payload.encode())
            p.stdin.close()
        except (BrokenPipeError, OSError):
            pass
    writer = threading.Thread(target=send_input, daemon=True)
    for reader in readers:
        reader.start()
    writer.start()
    try:
        p.wait(timeout=timeout)
    except (subprocess.TimeoutExpired, BrokenPipeError) as error:
        p.kill()
        p.wait()
        raise SandboxError(type(error).__name__) from error
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
        for reader in readers:
            reader.join(timeout=2)
        writer.join(timeout=2)
        for stream in (p.stdout, p.stderr):
            stream.close()
    if overflow.is_set():
        raise SandboxError("OUTPUT_LIMIT")
    return p.returncode, *(bytes(buffers[k]).decode("utf-8", errors="replace") for k in ("stdout", "stderr"))


class DockerRunner:
    def __init__(self, image: str, timeout: int = 20):
        """Accept only the immutable ID of a local image the user already pulled."""
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
            raise ValueError("Use the full sha256 ID of the local image, not a mutable tag")
        self.image, self.timeout = image, timeout
        self.run_id = uuid.uuid4().hex

    def command(self, source: Path, name: str) -> list[str]:
        worker = Path(__file__).with_name("worker.py").resolve()
        source = source.resolve()
        if "," in str(source) or "," in str(worker):
            raise ValueError("Docker --mount: use a directory without commas")
        return ["docker", "run", "--rm", "--name", name, "--label", "repairlab.run=" + self.run_id,
                "--pull", "never", "--network", "none",
                "--read-only", "--user", "65534:65534", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--memory", "128m", "--memory-swap", "128m",
                "--cpus", "1", "--pids-limit", "32", "--log-driver", "none",
                "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=16m", "-i",
                "--mount", f"type=bind,source={source},target=/candidate,readonly",
                "--mount", f"type=bind,source={worker},target=/worker.py,readonly",
                "--entrypoint", "python", self.image, "-I", "-S", "/worker.py"]

    def daemon_healthy(self) -> bool:
        try:
            code, out, _ = bounded_process(["docker", "info", "--format", "{{.OSType}}"], timeout=15)
        except SandboxError:
            return False
        return code == 0 and out.strip() == "linux"

    def invoke(self, source: Path, case: dict) -> dict:
        """Separate candidate failures (rejected row) from daemon failures (SandboxError).

        Timeout, OUTPUT_LIMIT or exit 125-127 with a healthy daemon are attributed to the candidate,
        which controls its own process; if the daemon does not respond, abort as infrastructure.
        The finally block removes only the container created by this invocation.
        """
        name = "strands-repair-" + uuid.uuid4().hex
        try:
            try:
                code, stdout, stderr = bounded_process(
                    self.command(source, name),
                    json.dumps(case["input"]),
                    timeout=self.timeout,
                )
            except SandboxError as error:
                if str(error) not in CANDIDATE_LIMITS or not self.daemon_healthy():
                    raise
                return {"candidate_error": "SANDBOX_LIMIT: " + str(error)}
            if code in (125, 126, 127):
                if not self.daemon_healthy() or stderr.startswith("docker:"):
                    raise SandboxError("Docker could not run: " + stderr[:2000])
                return {"candidate_error": stderr[:4000], "exit_code": code}
            if code:
                return {"candidate_error": stderr[:4000], "exit_code": code}
            try:
                result = json.loads(stdout)
            except (ValueError, RecursionError):
                return {"candidate_error": "Invalid JSON output", "stdout": stdout[:4000]}
            if not isinstance(result, dict) or set(result) != {"result", "inputs_unchanged"}:
                return {"candidate_error": "Invalid JSON envelope"}
            return result
        finally:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)

    def preflight(self) -> dict:
        code, out, err = bounded_process(["docker", "info", "--format", "{{.OSType}}"], timeout=15)
        if code or out.strip() != "linux":
            raise SandboxError("A Docker daemon with Linux containers is required: " + err[:1000])
        code, out, err = bounded_process(["docker", "image", "inspect", self.image, "--format", "{{.Id}}"], timeout=15)
        if code or out.strip() != self.image:
            raise SandboxError("Local image not available: " + err[:1000])
        return {"image_id": self.image, "os": "linux", "network": "none", "candidate_mount": "readonly"}
