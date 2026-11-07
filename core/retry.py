"""
retry.py — retry-with-backoff for outbound API calls.

Ports V7's node-level policy (`retryOnFail: true, maxTries: 3, waitBetweenTries: 5000`),
which every HTTP node in the workflow used. Without it, one blip or one rate-limit
response loses a lead *and* still burns the credit that was spent finding it.

Retries transient failures only — timeouts, connection drops, HTTP 429 and 5xx.
A 4xx that isn't 429 means the request itself is wrong (bad key, bad payload), so
retrying would just waste time; those raise straight away.
"""
from __future__ import annotations

import time
import urllib.error

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


def is_transient(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in RETRY_STATUS
    if isinstance(exc, urllib.error.URLError):
        return True                      # DNS / connection refused / TLS wobble
    return isinstance(exc, (TimeoutError, ConnectionError, OSError))


def retry_after_seconds(exc: Exception) -> float | None:
    """Honour a server's Retry-After header when it sends one."""
    if isinstance(exc, urllib.error.HTTPError):
        hdrs = getattr(exc, "headers", None)      # don't test truthiness: an empty
        raw = hdrs.get("Retry-After") if hdrs is not None else None   # header set is falsy
        if raw:
            try:
                return max(0.0, float(str(raw).strip()))
            except ValueError:
                return None
    return None


def call(fn, *args, tries: int = 3, wait: float = 5.0, on_retry=None, **kwargs):
    """Run fn(*args, **kwargs), retrying transient failures up to `tries` times."""
    attempts = max(1, int(tries or 1))
    last = None
    for attempt in range(1, attempts + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — decide by type below
            last = exc
            if attempt >= attempts or not is_transient(exc):
                raise
            pause = retry_after_seconds(exc)
            if pause is None:
                pause = float(wait) * attempt        # linear backoff, like V7's fixed wait
            if on_retry:
                on_retry(attempt, attempts, exc, pause)
            if pause > 0:
                time.sleep(pause)
    raise last  # unreachable
