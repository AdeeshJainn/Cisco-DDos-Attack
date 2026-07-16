"""Retry helper for payment-svc's outbound calls.

Downstream hiccups — a slow notify instance, a dropped connection — are
common enough that every outbound call goes through call_with_retry. Two
rules keep retries safe:

- attempts are capped, so a dependency that is actually down gets surfaced
  instead of hammered;
- waits grow exponentially with jitter, so a herd of callers backs off
  instead of retrying in lockstep.
"""

import logging
import random
import time
from collections.abc import Callable

MAX_RETRIES = 3  # total attempts = 1 + MAX_RETRIES
BASE_DELAY_S = 0.2
BACKOFF_FACTOR = 2.0
MAX_DELAY_S = 2.0

log = logging.getLogger("payment-svc.retry")


class TransientError(Exception):
    """Raise for failures worth retrying (timeouts, 5xx from a dependency)."""


def backoff_delay(attempt: int) -> float:
    """Delay before retry `attempt` (1-based): exponential, capped, jittered."""
    delay = min(BASE_DELAY_S * BACKOFF_FACTOR ** (attempt - 1), MAX_DELAY_S)
    return delay * random.uniform(0.5, 1.0)


def call_with_retry(fn: Callable[[], object], *, what: str = "call") -> object:
    """Run fn, retrying TransientError up to MAX_RETRIES times with backoff."""
    attempt = 0
    while True:
        try:
            return fn()
        except TransientError as err:
            attempt += 1
            if attempt > MAX_RETRIES:
                log.error("%s failed after %d attempts: %s", what, attempt, err)
                raise
            delay = backoff_delay(attempt)
            log.warning("%s attempt %d failed (%s); retrying in %.2fs", what, attempt, err, delay)
            time.sleep(delay)
