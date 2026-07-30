"""VitalGraph Client Retry Policy

Failure classification, backoff computation, and circuit breaking for the
VitalGraph HTTP client.

The central idea is that retry safety is decided by *how far the request got*,
not merely by the exception type:

- **pre-send**  — the request never reached the server, so replaying it cannot
  duplicate work. Safe to retry regardless of HTTP method.
- **post-send** — the server may have received and processed the request. Safe
  to retry only if the call is idempotent.
- **declined**  — the server explicitly refused to process it (429/503). Safe to
  retry regardless of method, honoring ``Retry-After``.
- **fatal**     — everything else. Never retried.
"""

from __future__ import annotations

import enum
import logging
import random
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class FailureClass(enum.Enum):
    """How far a failed request got before it failed."""

    PRE_SEND = "pre_send"
    POST_SEND = "post_send"
    DECLINED = "declined"
    FATAL = "fatal"


# HTTP methods that are idempotent by definition (RFC 9110). A retry of one of
# these cannot duplicate server-side effects, so post-send failures are safe.
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE", "PUT", "DELETE"})

# Request never left the client / never reached the application.
_PRE_SEND_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
    httpx.ProxyError,
)

# The server may have seen the request. WriteError/WriteTimeout are classified
# conservatively here: httpx cannot tell us whether a partially written body was
# already parsed and acted upon. ConnectionResetError is likewise conservative —
# a reset can arrive mid-request as easily as during connect.
_POST_SEND_EXCEPTIONS = (
    httpx.ReadTimeout,
    httpx.ReadError,
    httpx.WriteTimeout,
    httpx.WriteError,
    httpx.CloseError,
    httpx.RemoteProtocolError,
    ConnectionResetError,
)

# Server explicitly declined to process the request.
DECLINED_STATUS = frozenset({429, 503})

# Server-side transient failures that may have processed the request first.
POST_SEND_STATUS = frozenset({502, 504})


def classify_exception(exc: BaseException) -> FailureClass:
    """Classify a transport-level exception.

    Order matters: httpx's timeout and network errors share base classes, so the
    specific types are tested before any fallback.
    """
    if isinstance(exc, _PRE_SEND_EXCEPTIONS):
        return FailureClass.PRE_SEND
    if isinstance(exc, _POST_SEND_EXCEPTIONS):
        return FailureClass.POST_SEND
    # Unknown transport errors are treated as post-send: assume the worst about
    # whether the server saw the request.
    if isinstance(exc, httpx.TransportError):
        return FailureClass.POST_SEND
    return FailureClass.FATAL


def classify_status(status_code: int) -> FailureClass:
    """Classify an HTTP status code.

    500 is deliberately fatal: it usually signals a deterministic server-side
    bug, and retrying triples load for a result that will not change.
    """
    if status_code in DECLINED_STATUS:
        return FailureClass.DECLINED
    if status_code in POST_SEND_STATUS:
        return FailureClass.POST_SEND
    return FailureClass.FATAL


def parse_retry_after(value: Optional[str], now: Optional[float] = None) -> Optional[float]:
    """Parse a ``Retry-After`` header into seconds, or None if unusable.

    Accepts both the delta-seconds and the HTTP-date forms.
    """
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    try:
        delta = when.timestamp() - (now if now is not None else time.time())
    except (OverflowError, OSError, ValueError):
        return None
    return max(0.0, delta)


@dataclass
class RetryPolicy:
    """Backoff and attempt-count policy for a client.

    Attributes:
        max_retries: Retries *after* the first attempt (so 3 => up to 4 sends).
        retry_delay: Base delay in seconds; the first backoff is drawn from it.
        backoff_base: Exponential growth factor per attempt.
        max_delay: Ceiling on the pre-jitter delay.
        request_budget: Total wall-clock ceiling for one logical call, covering
            every attempt and every sleep between them.
        rng: Injectable for deterministic tests.
    """

    max_retries: int = 3
    retry_delay: float = 1.0
    backoff_base: float = 2.0
    max_delay: float = 10.0
    request_budget: float = 60.0
    rng: random.Random = field(default_factory=random.Random)

    def compute_sleep(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """Full-jitter exponential backoff for a zero-based attempt index.

        Full jitter (uniform over [0, capped]) rather than equal jitter: it
        decorrelates independent clients most aggressively, which is the whole
        point when N workers fail against the same server simultaneously.

        A server-supplied ``Retry-After`` acts as a floor — never retry sooner
        than the server asked, but still add backoff growth beyond it.
        """
        capped = min(self.max_delay, self.retry_delay * (self.backoff_base ** attempt))
        sleep_for = self.rng.uniform(0.0, max(0.0, capped))
        if retry_after is not None:
            sleep_for = max(sleep_for, retry_after)
        return sleep_for


class CircuitState(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Per-client breaker that stops retries from amplifying an outage.

    Counts consecutive pre-send failures and server-declined responses. Once the
    threshold trips, calls fail immediately — no socket, no sleep, no budget
    burned — until the reset timeout elapses, after which a single probe decides
    whether to close again.
    """

    def __init__(
        self,
        threshold: int = 5,
        reset_timeout: float = 30.0,
        max_reset_timeout: float = 300.0,
        clock=time.monotonic,
    ):
        self.threshold = threshold
        self.base_reset_timeout = reset_timeout
        self.max_reset_timeout = max_reset_timeout
        self._clock = clock
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float = 0.0
        self._current_reset_timeout = reset_timeout
        self.trip_count = 0

    @property
    def state(self) -> CircuitState:
        """Current state, transitioning OPEN -> HALF_OPEN once the timeout expires."""
        if self._state is CircuitState.OPEN:
            if self._clock() - self._opened_at >= self._current_reset_timeout:
                self._state = CircuitState.HALF_OPEN
        return self._state

    @property
    def enabled(self) -> bool:
        return self.threshold > 0

    def allows_request(self) -> bool:
        """False only when the breaker is open and the reset timeout has not elapsed."""
        if not self.enabled:
            return True
        return self.state is not CircuitState.OPEN

    def retry_after(self) -> float:
        """Seconds until the open breaker will admit a probe."""
        if self._state is not CircuitState.OPEN:
            return 0.0
        return max(0.0, self._current_reset_timeout - (self._clock() - self._opened_at))

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._current_reset_timeout = self.base_reset_timeout
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Record a failure that indicates the *server* is unreachable or refusing.

        Post-send failures are not recorded: a slow query timing out says nothing
        about whether the server is up.
        """
        if not self.enabled:
            return
        if self._state is CircuitState.HALF_OPEN:
            # The probe failed — reopen with a longer timeout.
            self._current_reset_timeout = min(
                self.max_reset_timeout, self._current_reset_timeout * 2
            )
            self._open()
            return
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.threshold:
            self._open()

    def _open(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = self._clock()
        self.trip_count += 1
        logger.warning(
            "Circuit breaker opened after %d consecutive failures; "
            "failing fast for %.1fs",
            self._consecutive_failures,
            self._current_reset_timeout,
        )


@dataclass
class RetryStats:
    """In-process counters, surfaced via ``VitalGraphClient.stats()``."""

    requests: int = 0
    attempts: int = 0
    retries_pre_send: int = 0
    retries_post_send: int = 0
    retries_declined: int = 0
    budget_exhausted: int = 0
    breaker_rejections: int = 0
    non_retryable_writes: int = 0

    def record_retry(self, failure_class: FailureClass) -> None:
        if failure_class is FailureClass.PRE_SEND:
            self.retries_pre_send += 1
        elif failure_class is FailureClass.POST_SEND:
            self.retries_post_send += 1
        elif failure_class is FailureClass.DECLINED:
            self.retries_declined += 1

    def as_dict(self) -> dict:
        return {
            "requests": self.requests,
            "attempts": self.attempts,
            "retries_pre_send": self.retries_pre_send,
            "retries_post_send": self.retries_post_send,
            "retries_declined": self.retries_declined,
            "budget_exhausted": self.budget_exhausted,
            "breaker_rejections": self.breaker_rejections,
            "non_retryable_writes": self.non_retryable_writes,
        }


def safe_log_url(url: str) -> str:
    """Strip the query string before logging — it can carry entity URIs."""
    return str(url).split("?", 1)[0]
