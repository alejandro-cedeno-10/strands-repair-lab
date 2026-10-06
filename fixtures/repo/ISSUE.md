# The client retries operations it should not
A POST sequence that returns 503 ends up being sent again. A GET with 401 is also
repeated. We want to keep recovering from transient failures without multiplying
operations or repeating permanent errors. Investigate and fix according to docs/contract.md.
Deliver the cause, the diff, the checks you ran and the limits. Do not change the contract or the tests.
