# HTTP reliability policy

MarketPulse uses one reusable HTTP client for bounded public-file downloads.
This document defines which failures are retried, how long the client waits,
and which errors fail immediately.

## Default request policy

| Control | Default | Reason |
| --- | ---: | --- |
| Timeout | 30 seconds per attempt | Prevent a blocked connection or read from waiting forever |
| Maximum attempts | 3 total | Bound latency and load; the first request counts as attempt 1 |
| First backoff | 0.5 seconds | Give a temporarily unhealthy source time to recover |
| Multiplier | 2 | Produce 0.5 then 1.0 seconds between three attempts |
| Backoff cap | 8 seconds | Prevent future policies with more attempts from waiting without a bound |
| Response size | Set by each caller | Reject unexpected data before it exhausts local storage or memory |

Backoff is exponential: after failed attempt `n`, the delay is
`initial_backoff * multiplier^(n-1)`, limited by the configured cap. The first
client is deterministic and does not add random jitter. Jitter should be
considered before many workers make concurrent requests, because synchronized
retries can overload an already unhealthy source.

## Failure classification

The client retries transport failures (`URLError`, connection errors, and
timeouts) plus these HTTP statuses:

- `408 Request Timeout`
- `425 Too Early`
- `429 Too Many Requests`
- `500 Internal Server Error`
- `502 Bad Gateway`
- `503 Service Unavailable`
- `504 Gateway Timeout`

Other HTTP statuses fail once as `HttpStatusError`. Invalid URL schemes,
non-positive limits, invalid response metadata, empty responses, and size-limit
violations also fail without retry. Repeating those requests would not repair
the input or policy problem.

When all temporary attempts fail, `HttpRetryExhausted` records the URL, number
of attempts, and final error. A successful `DownloadReceipt` records the status,
published path, byte count, and actual number of attempts.

## File safety across attempts

Every attempt writes to `<destination>.part`. The partial file is removed before
the next attempt and after any failed attempt. Only a complete, non-empty,
within-limit response is atomically renamed to the final destination. If an
older valid destination already exists and all new attempts fail, the older
file remains untouched.

## Scope boundary

Python's documented `urlopen` timeout is passed to every attempt, and its
`HTTPError` and `URLError` types provide the transport signals classified here.
The client currently downloads only HTTP(S) GET resources and does not retry
non-idempotent writes.

Day 8 does not compare downloaded bytes with the provider's published checksum.
Official `.CHECKSUM` retrieval and SHA-256 comparison are the Day 9 milestone.

## Evidence

Run the deterministic reliability tests without network access:

```powershell
uv run pytest tests/test_http_client.py -q
```

The tests prove successful publication, timeout propagation, transient recovery,
retry exhaustion, exponential delays, delay capping, permanent-status behavior,
size and empty-response rejection, metadata validation, and preservation of an
older destination.

## References

- [Python 3.12 urllib.request documentation](https://docs.python.org/3.12/library/urllib.request.html)
- [Python 3.12 urllib.error documentation](https://docs.python.org/3.12/library/urllib.error.html)
- [AWS Builders' Library: Timeouts, retries, and backoff with jitter](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/)
