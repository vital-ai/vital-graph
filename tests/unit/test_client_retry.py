"""Unit tests for the VitalGraph client retry policy.

These run entirely against ``httpx.MockTransport`` — no network, no server, and
no real sleeping (``asyncio.sleep`` is patched so backoff is instantaneous but
still observable).
"""

import asyncio
import random
from typing import List, Optional

import httpx
import pytest

from vitalgraph.client.retry import (
    CircuitBreaker,
    CircuitState,
    FailureClass,
    RetryPolicy,
    classify_exception,
    classify_status,
    parse_retry_after,
    safe_log_url,
)
from vitalgraph.client.utils.client_utils import (
    VitalGraphClientConnectionError,
    VitalGraphClientError,
    VitalGraphClientTimeoutError,
    VitalGraphClientUnavailableError,
)
from vitalgraph.client.vitalgraph_client import VitalGraphClient


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class FakeConfig:
    """Minimal stand-in for VitalGraphClientConfig with tunable retry settings."""

    def __init__(self, **overrides):
        self.values = {
            'server_url': 'http://testserver',
            'api_base_path': '/api/v1',
            'timeout': 30.0,
            'connect_timeout': 5.0,
            'pool_timeout': 5.0,
            'request_budget': 60.0,
            'max_retries': 3,
            'retry_delay': 1.0,
            'retry_backoff_base': 2.0,
            'retry_max_delay': 10.0,
            'max_connections': 100,
            'max_keepalive': 20,
            'keepalive_expiry': 5.0,
            'max_concurrency': 0,
            'breaker_threshold': 5,
            'breaker_reset': 30.0,
        }
        self.values.update(overrides)

    def get_server_url(self): return self.values['server_url']
    def get_api_base_path(self): return self.values['api_base_path']
    def get_credentials(self): return ('admin', 'admin')
    def get_timeout(self): return self.values['timeout']
    def get_connect_timeout(self): return self.values['connect_timeout']
    def get_pool_timeout(self): return self.values['pool_timeout']
    def get_request_budget(self): return self.values['request_budget']
    def get_max_retries(self): return self.values['max_retries']
    def get_retry_delay(self): return self.values['retry_delay']
    def get_retry_backoff_base(self): return self.values['retry_backoff_base']
    def get_retry_max_delay(self): return self.values['retry_max_delay']
    def get_max_connections(self): return self.values['max_connections']
    def get_max_keepalive(self): return self.values['max_keepalive']
    def get_keepalive_expiry(self): return self.values['keepalive_expiry']
    def get_max_concurrency(self): return self.values['max_concurrency']
    def get_breaker_threshold(self): return self.values['breaker_threshold']
    def get_breaker_reset(self): return self.values['breaker_reset']


def make_client(handler, clock=None, **config_overrides) -> VitalGraphClient:
    """Build a client wired to a MockTransport, bypassing open()/login."""
    client = VitalGraphClient(config=FakeConfig(**config_overrides), api_key='vg_test')
    client.async_session = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url='http://testserver',
    )
    client.is_open = True
    client.access_token = 'vg_test'
    # Deterministic jitter: rng.uniform(0, cap) always returns the cap.
    client.retry_policy.rng = _MaxRng()
    if clock is not None:
        client._clock = clock
    return client


class _MaxRng(random.Random):
    """RNG whose uniform() always returns the upper bound, for predictable sleeps."""

    def uniform(self, a, b):
        return b


class FakeClock:
    """Virtual monotonic clock; tests advance it instead of waiting."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def sleeps(monkeypatch, clock) -> List[float]:
    """Capture backoff sleeps and advance the virtual clock instead of waiting.

    Advancing matters: the request budget is measured against the same clock, so
    a test that skipped sleeps entirely would never see the budget expire.
    """
    recorded: List[float] = []

    async def fake_sleep(seconds):
        recorded.append(seconds)
        clock.advance(seconds)

    monkeypatch.setattr('vitalgraph.client.vitalgraph_client.asyncio.sleep', fake_sleep)
    return recorded


def counting_handler(*outcomes):
    """Build a handler that yields one outcome per call.

    Each outcome is either an exception instance to raise or an
    ``httpx.Response`` factory result. The last outcome repeats if exhausted.
    """
    calls = {'n': 0}

    def handler(request: httpx.Request) -> httpx.Response:
        idx = min(calls['n'], len(outcomes) - 1)
        calls['n'] += 1
        outcome = outcomes[idx]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    handler.calls = calls
    return handler


def ok(body=None):
    return httpx.Response(200, json=body or {'status': 'ok'})


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("exc,expected", [
    (httpx.ConnectError("refused"), FailureClass.PRE_SEND),
    (httpx.ConnectTimeout("timed out"), FailureClass.PRE_SEND),
    (httpx.PoolTimeout("pool exhausted"), FailureClass.PRE_SEND),
    (httpx.ProxyError("bad proxy"), FailureClass.PRE_SEND),
    (httpx.ReadTimeout("slow"), FailureClass.POST_SEND),
    (httpx.ReadError("reset"), FailureClass.POST_SEND),
    (httpx.WriteTimeout("slow write"), FailureClass.POST_SEND),
    (httpx.WriteError("broken pipe"), FailureClass.POST_SEND),
    (httpx.RemoteProtocolError("bad frame"), FailureClass.POST_SEND),
    (ConnectionResetError("reset by peer"), FailureClass.POST_SEND),
    (ValueError("nonsense"), FailureClass.FATAL),
])
def test_classify_exception(exc, expected):
    assert classify_exception(exc) is expected


def test_pool_timeout_is_retryable_regression():
    """PoolTimeout used to be omitted, so pool exhaustion failed on first try."""
    assert classify_exception(httpx.PoolTimeout("x")) is FailureClass.PRE_SEND


@pytest.mark.parametrize("status,expected", [
    (429, FailureClass.DECLINED),
    (503, FailureClass.DECLINED),
    (502, FailureClass.POST_SEND),
    (504, FailureClass.POST_SEND),
    (500, FailureClass.FATAL),
    (404, FailureClass.FATAL),
    (400, FailureClass.FATAL),
])
def test_classify_status(status, expected):
    assert classify_status(status) is expected


def test_parse_retry_after():
    assert parse_retry_after("12") == 12.0
    assert parse_retry_after("-5") == 0.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("garbage") is None
    # HTTP-date form
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") is not None


def test_safe_log_url_strips_query():
    assert safe_log_url("http://h/api?uri=urn:secret") == "http://h/api"


# ---------------------------------------------------------------------------
# Backoff
# ---------------------------------------------------------------------------


def test_backoff_is_exponential_and_capped():
    policy = RetryPolicy(retry_delay=1.0, backoff_base=2.0, max_delay=10.0, rng=_MaxRng())
    assert [policy.compute_sleep(i) for i in range(5)] == [1.0, 2.0, 4.0, 8.0, 10.0]


def test_backoff_has_jitter():
    """Two policies with different seeds must not produce identical schedules."""
    a = RetryPolicy(rng=random.Random(1))
    b = RetryPolicy(rng=random.Random(2))
    assert [a.compute_sleep(i) for i in range(5)] != [b.compute_sleep(i) for i in range(5)]


def test_backoff_never_exceeds_cap_with_jitter():
    policy = RetryPolicy(retry_delay=1.0, backoff_base=2.0, max_delay=10.0,
                         rng=random.Random(42))
    assert all(0.0 <= policy.compute_sleep(i) <= 10.0 for i in range(20))


def test_retry_after_acts_as_floor():
    policy = RetryPolicy(retry_delay=1.0, max_delay=10.0, rng=_MaxRng())
    assert policy.compute_sleep(0, retry_after=7.5) == 7.5
    assert policy.compute_sleep(3, retry_after=2.0) == 8.0


# ---------------------------------------------------------------------------
# Retry behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_retries_pre_send_failure_then_succeeds(sleeps):
    handler = counting_handler(httpx.ConnectError("refused"), ok())
    client = make_client(handler)
    resp = await client._make_authenticated_request('GET', 'http://testserver/x')
    assert resp.status_code == 200
    assert handler.calls['n'] == 2
    assert sleeps == [1.0]


@pytest.mark.asyncio
async def test_get_retries_post_send_failure(sleeps):
    handler = counting_handler(httpx.ReadTimeout("slow"), ok())
    client = make_client(handler)
    resp = await client._make_authenticated_request('GET', 'http://testserver/x')
    assert resp.status_code == 200
    assert handler.calls['n'] == 2


@pytest.mark.asyncio
async def test_post_not_retried_after_send(sleeps):
    """The duplicate-write fix: a POST that may have been processed is not replayed."""
    handler = counting_handler(httpx.ReadTimeout("slow"), ok())
    client = make_client(handler)
    with pytest.raises(VitalGraphClientTimeoutError) as excinfo:
        await client._make_authenticated_request('POST', 'http://testserver/x')
    assert handler.calls['n'] == 1
    assert sleeps == []
    assert "may already have been processed" in str(excinfo.value)
    assert client.retry_stats.non_retryable_writes == 1


@pytest.mark.asyncio
async def test_post_retried_before_send(sleeps):
    """A POST that never reached the server is safe to replay."""
    handler = counting_handler(httpx.ConnectError("refused"), ok())
    client = make_client(handler)
    resp = await client._make_authenticated_request('POST', 'http://testserver/x')
    assert resp.status_code == 200
    assert handler.calls['n'] == 2


@pytest.mark.asyncio
async def test_idempotent_post_retried_after_send(sleeps):
    """Read-only POSTs (search/query) opt in and are replayed."""
    handler = counting_handler(httpx.ReadTimeout("slow"), ok())
    client = make_client(handler)
    resp = await client._make_authenticated_request(
        'POST', 'http://testserver/query', idempotent=True
    )
    assert resp.status_code == 200
    assert handler.calls['n'] == 2


@pytest.mark.asyncio
async def test_non_replayable_body_is_never_retried(sleeps):
    """A consumed generator/file handle would upload a truncated body on retry."""
    handler = counting_handler(httpx.ConnectError("refused"), ok())
    client = make_client(handler)
    with pytest.raises(VitalGraphClientError) as excinfo:
        await client._make_authenticated_request(
            'POST', 'http://testserver/upload', replayable=False
        )
    assert handler.calls['n'] == 1
    assert "cannot be replayed" in str(excinfo.value)


@pytest.mark.asyncio
async def test_replayable_get_still_retried(sleeps):
    """The replayable guard must not suppress ordinary retries."""
    handler = counting_handler(httpx.ConnectError("refused"), ok())
    client = make_client(handler)
    resp = await client._make_authenticated_request('GET', 'http://testserver/x')
    assert resp.status_code == 200
    assert handler.calls['n'] == 2


@pytest.mark.asyncio
async def test_504_not_retried_for_post(sleeps):
    handler = counting_handler(httpx.Response(504), ok())
    client = make_client(handler)
    with pytest.raises(VitalGraphClientError):
        await client._make_authenticated_request('POST', 'http://testserver/x')
    assert handler.calls['n'] == 1


@pytest.mark.asyncio
async def test_503_retried_for_post_and_honors_retry_after(sleeps):
    """A 503 means the server did not process the request, so even a POST is safe."""
    handler = counting_handler(
        httpx.Response(503, headers={'Retry-After': '4'}), ok()
    )
    client = make_client(handler)
    resp = await client._make_authenticated_request('POST', 'http://testserver/x')
    assert resp.status_code == 200
    assert sleeps == [4.0]


@pytest.mark.asyncio
async def test_500_is_not_retried(sleeps):
    handler = counting_handler(httpx.Response(500, json={'detail': 'boom'}), ok())
    client = make_client(handler)
    with pytest.raises(VitalGraphClientError) as excinfo:
        await client._make_authenticated_request('GET', 'http://testserver/x')
    assert handler.calls['n'] == 1
    assert excinfo.value.status_code == 500
    assert 'boom' in str(excinfo.value)


@pytest.mark.asyncio
async def test_404_preserves_status_and_detail(sleeps):
    handler = counting_handler(httpx.Response(404, json={'detail': 'no such space'}))
    client = make_client(handler)
    with pytest.raises(VitalGraphClientError) as excinfo:
        await client._make_authenticated_request('GET', 'http://testserver/x')
    assert excinfo.value.status_code == 404
    assert 'no such space' in str(excinfo.value)


@pytest.mark.asyncio
async def test_retries_exhausted_raises_connection_error(sleeps):
    handler = counting_handler(httpx.ConnectError("refused"))
    client = make_client(handler, breaker_threshold=0)
    with pytest.raises(VitalGraphClientConnectionError):
        await client._make_authenticated_request('GET', 'http://testserver/x')
    assert handler.calls['n'] == 4          # 1 initial + 3 retries
    assert sleeps == [1.0, 2.0, 4.0]        # exponential


@pytest.mark.asyncio
async def test_exhausted_declined_raises_unavailable(sleeps):
    handler = counting_handler(httpx.Response(503))
    client = make_client(handler, breaker_threshold=0)
    with pytest.raises(VitalGraphClientUnavailableError) as excinfo:
        await client._make_authenticated_request('GET', 'http://testserver/x')
    assert excinfo.value.status_code == 503


@pytest.mark.asyncio
async def test_original_exception_is_chained(sleeps):
    handler = counting_handler(httpx.ConnectError("refused"))
    client = make_client(handler, breaker_threshold=0)
    with pytest.raises(VitalGraphClientConnectionError) as excinfo:
        await client._make_authenticated_request('GET', 'http://testserver/x')
    assert isinstance(excinfo.value.__cause__, httpx.ConnectError)


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_stops_retries_early(sleeps, clock):
    """Backoff that would overrun the budget ends the call instead."""
    handler = counting_handler(httpx.ConnectError("refused"))
    client = make_client(handler, clock=clock, request_budget=2.5, breaker_threshold=0)
    with pytest.raises(VitalGraphClientTimeoutError) as excinfo:
        await client._make_authenticated_request('GET', 'http://testserver/x')
    assert 'budget' in str(excinfo.value)
    # First sleep (1.0s) fits in 2.5s; the second (2.0s) does not.
    assert sleeps == [1.0]
    assert client.retry_stats.budget_exhausted == 1


@pytest.mark.asyncio
async def test_attempt_timeout_clamped_to_remaining_budget(sleeps):
    """No single attempt may outlive the budget, even with a large read timeout."""
    client = make_client(counting_handler(ok()), timeout=300.0, request_budget=10.0)
    attempt_timeout = client._build_attempt_timeout(remaining=4.0)
    assert attempt_timeout.read == 4.0
    assert attempt_timeout.connect == 4.0


def test_attempt_timeout_uses_per_phase_config():
    client = make_client(counting_handler(ok()), timeout=30.0, connect_timeout=5.0,
                         pool_timeout=3.0)
    t = client._build_attempt_timeout(remaining=100.0)
    assert (t.connect, t.read, t.write, t.pool) == (5.0, 30.0, 30.0, 3.0)


# ---------------------------------------------------------------------------
# 401 handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_401_refreshes_then_retries(sleeps):
    handler = counting_handler(httpx.Response(401), ok())
    client = make_client(handler)
    refreshed = {'n': 0}

    async def fake_reauth():
        refreshed['n'] += 1

    client._reauthenticate = fake_reauth
    client.refresh_token = None

    resp = await client._make_authenticated_request('GET', 'http://testserver/x')
    assert resp.status_code == 200
    assert refreshed['n'] == 1
    assert sleeps == []           # a 401 refresh is not a backoff retry


@pytest.mark.asyncio
async def test_second_401_gives_up(sleeps):
    handler = counting_handler(httpx.Response(401))
    client = make_client(handler)

    async def fake_reauth():
        pass

    client._reauthenticate = fake_reauth
    client.refresh_token = None

    with pytest.raises(VitalGraphClientError) as excinfo:
        await client._make_authenticated_request('GET', 'http://testserver/x')
    assert excinfo.value.status_code == 401
    assert handler.calls['n'] == 2


@pytest.mark.asyncio
async def test_connection_error_after_refresh_still_retries(sleeps):
    """Regression: the old inline post-401 request bypassed the retry loop."""
    handler = counting_handler(
        httpx.Response(401), httpx.ConnectError("refused"), ok()
    )
    client = make_client(handler)

    async def fake_reauth():
        pass

    client._reauthenticate = fake_reauth
    client.refresh_token = None

    resp = await client._make_authenticated_request('GET', 'http://testserver/x')
    assert resp.status_code == 200
    assert handler.calls['n'] == 3


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


def test_breaker_opens_after_threshold():
    clock = FakeClock()
    breaker = CircuitBreaker(threshold=3, reset_timeout=30.0, clock=clock)
    for _ in range(2):
        breaker.record_failure()
    assert breaker.allows_request()
    breaker.record_failure()
    assert not breaker.allows_request()
    assert breaker.state is CircuitState.OPEN
    assert breaker.trip_count == 1


def test_breaker_half_opens_then_closes_on_success():
    clock = FakeClock()
    breaker = CircuitBreaker(threshold=1, reset_timeout=30.0, clock=clock)
    breaker.record_failure()
    assert not breaker.allows_request()
    clock.advance(31)
    assert breaker.allows_request()
    assert breaker.state is CircuitState.HALF_OPEN
    breaker.record_success()
    assert breaker.state is CircuitState.CLOSED


def test_breaker_reopens_with_doubled_timeout_on_probe_failure():
    clock = FakeClock()
    breaker = CircuitBreaker(threshold=1, reset_timeout=30.0, clock=clock)
    breaker.record_failure()
    clock.advance(31)
    assert breaker.state is CircuitState.HALF_OPEN
    breaker.record_failure()
    assert breaker.state is CircuitState.OPEN
    clock.advance(31)
    assert breaker.state is CircuitState.OPEN      # now needs 60s
    clock.advance(30)
    assert breaker.state is CircuitState.HALF_OPEN


def test_breaker_success_resets_counter():
    breaker = CircuitBreaker(threshold=3)
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    assert breaker.allows_request()


def test_breaker_disabled_at_zero_threshold():
    breaker = CircuitBreaker(threshold=0)
    for _ in range(50):
        breaker.record_failure()
    assert breaker.allows_request()


@pytest.mark.asyncio
async def test_open_breaker_fails_fast(sleeps):
    handler = counting_handler(httpx.ConnectError("refused"))
    client = make_client(handler, breaker_threshold=2, max_retries=1)

    with pytest.raises(VitalGraphClientConnectionError):
        await client._make_authenticated_request('GET', 'http://testserver/x')

    calls_before = handler.calls['n']
    with pytest.raises(VitalGraphClientUnavailableError) as excinfo:
        await client._make_authenticated_request('GET', 'http://testserver/x')
    # No socket was opened for the rejected call.
    assert handler.calls['n'] == calls_before
    assert excinfo.value.retry_after > 0
    assert client.retry_stats.breaker_rejections == 1


@pytest.mark.asyncio
async def test_post_send_failures_do_not_trip_breaker(sleeps):
    """A slow query timing out says nothing about whether the server is up."""
    handler = counting_handler(httpx.ReadTimeout("slow"))
    client = make_client(handler, breaker_threshold=2, max_retries=3)
    with pytest.raises(VitalGraphClientTimeoutError):
        await client._make_authenticated_request('GET', 'http://testserver/x')
    assert client.circuit_breaker.allows_request()


# ---------------------------------------------------------------------------
# Shared core: health, concurrency, stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_uses_short_budget_and_one_retry(sleeps):
    handler = counting_handler(httpx.ConnectError("refused"))
    client = make_client(handler, breaker_threshold=0)
    with pytest.raises(VitalGraphClientConnectionError):
        await client.health()
    # 1 initial + 1 retry, not the configured 3 retries.
    assert handler.calls['n'] == 2


@pytest.mark.asyncio
async def test_health_succeeds_through_core(sleeps):
    client = make_client(counting_handler(ok({'status': 'healthy'})))
    assert await client.health() == {'status': 'healthy'}


@pytest.mark.asyncio
async def test_concurrency_limiter_caps_in_flight(sleeps):
    in_flight = {'now': 0, 'max': 0}

    def handler(request):
        in_flight['now'] += 1
        in_flight['max'] = max(in_flight['max'], in_flight['now'])
        in_flight['now'] -= 1
        return ok()

    client = make_client(handler, max_concurrency=2)
    client._concurrency_limiter = asyncio.Semaphore(2)
    await asyncio.gather(*[
        client._make_authenticated_request('GET', 'http://testserver/x')
        for _ in range(10)
    ])
    assert in_flight['max'] <= 2


@pytest.mark.asyncio
async def test_stats_counters(sleeps):
    handler = counting_handler(httpx.ConnectError("refused"), ok())
    client = make_client(handler)
    await client._make_authenticated_request('GET', 'http://testserver/x')
    stats = client.stats()
    assert stats['requests'] == 1
    assert stats['attempts'] == 2
    assert stats['retries_pre_send'] == 1
    assert stats['breaker_state'] == 'closed'
