"""Reference control written by the lab author. Never give it to the repair agent."""
def request_with_retry(method, send, max_attempts=3, sleep=lambda seconds: None):
    if type(max_attempts) is not int or not 1 <= max_attempts <= 5:
        raise ValueError("max_attempts must be an integer from 1 to 5")
    allowed = method in {"GET", "HEAD", "OPTIONS", "PUT", "DELETE"}
    for attempt in range(max_attempts):
        response = send(method)
        transient = response["status"] in {429, 502, 503, 504}
        if not (allowed and transient and attempt + 1 < max_attempts):
            return response
        sleep(min(0.1 * 2 ** attempt, 0.4))
