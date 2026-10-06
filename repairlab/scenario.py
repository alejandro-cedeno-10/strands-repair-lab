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
