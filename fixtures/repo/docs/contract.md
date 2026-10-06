# Contract for this lab
- Methods arrive in uppercase. Conservative policy: only GET, HEAD, OPTIONS,
  PUT and DELETE allow retries. POST and PATCH are never retried automatically.
- Transient statuses chosen by the project: 429, 502, 503 and 504. Any other status is terminal.
  This list is an example policy, not an exhaustive rule from the HTTP standard.
- max_attempts counts the initial attempt: an exact integer from 1 to 5, bool excluded.
  Otherwise, raise ValueError before calling the transport or sleep.
- Return the dictionary of the last response without altering its content.
- Before the next attempt: sleep(min(0.1 * 2**retry_index, 0.4)); the first index is 0.
  Do not sleep after a terminal response or when attempts are exhausted.
- Transport exceptions propagate without retrying. This is deliberately conservative.
- Do not modify arguments or invent responses; do not send extra calls.
Out of scope: Retry-After, jitter, connection-failure classification, deadlines,
streaming, authentication, TLS and server idempotency guarantees.
The backoff is deterministic so it can be verified; do not present it as a production policy.
