"""External declarative oracle: computes the expected outcome without executing the candidate."""
import copy

def expected(payload):
    method, limit = payload["method"], payload["max_attempts"]
    if type(limit) is not int or not 1 <= limit <= 5:
        return {"error": "ValueError", "calls": [], "sleeps": []}
    statuses = {429, 502, 503, 504}
    replayable = method in {"GET", "HEAD", "OPTIONS", "PUT", "DELETE"}
    sequence = [payload["outcomes"][min(i,len(payload["outcomes"])-1)] for i in range(limit)]
    terminal = next((i for i,x in enumerate(sequence) if x.get("error") or not replayable or x["status"] not in statuses), limit-1)
    response = sequence[terminal]
    answer = {"calls": [method]*(terminal+1), "sleeps": [min(0.1*2**i,0.4) for i in range(terminal)]}
    if response.get("error"):
        answer["error"] = "TimeoutError"
    else:
        answer["response"] = copy.deepcopy(response)
    return answer
