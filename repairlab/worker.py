"""Deterministic transport to observe calls, sleeps and exceptions."""
import copy

def exercise(function, payload):
    calls, sleeps = [], []
    outcomes = copy.deepcopy(payload["outcomes"])
    def send(method):
        calls.append(method)
        item = outcomes[min(len(calls)-1, len(outcomes)-1)]
        if item.get("error"):
            raise TimeoutError("scripted transport timeout")
        return copy.deepcopy(item)
    try:
        value = function(payload["method"], send, payload["max_attempts"], sleeps.append)
        result = {"response": value, "calls": calls, "sleeps": sleeps}
    except Exception as error:
        result = {"error": type(error).__name__, "calls": calls, "sleeps": sleeps}
    return result

import contextlib
import importlib.util
import json
import sys

def main():
    payload = json.loads(sys.stdin.read())
    original = copy.deepcopy(payload)
    spec = importlib.util.spec_from_file_location("candidate", "/candidate/http_client.py")
    module = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(sys.stderr):
        spec.loader.exec_module(module)
        result = exercise(module.request_with_retry, payload)
    print(json.dumps({"result": result, "inputs_unchanged": payload == original}, allow_nan=False))

if __name__ == "__main__":
    main()
