"""Minimal client with injectable transport and sleep."""
def request_with_retry(method, send, max_attempts=3, sleep=lambda seconds: None):
    for attempt in range(max_attempts):
        response = send(method)
        if response["status"] < 400:
            return response
        if attempt + 1 < max_attempts:
            sleep(0.1)
    return response
