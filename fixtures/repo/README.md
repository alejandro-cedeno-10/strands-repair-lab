# Lab HTTP client
Synthetic repository, not linked to any company. Read ISSUE.md and docs/contract.md.
The public interface is request_with_retry(method, send, max_attempts=3, sleep=...).
The transport send(method) returns a dictionary with status and body. sleep receives seconds.
The tests inject the transport and the clock: they need neither Internet nor real waits.
Only src/http_client.py may be modified; tools and budget belong to the runner.
