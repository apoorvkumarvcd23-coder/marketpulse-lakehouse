"""Retry, timeout, classification, and cleanup tests for the HTTP client."""

from __future__ import annotations

from collections.abc import Iterable
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from marketpulse.ingestion.http_client import (
    HttpClient,
    HttpEmptyResponse,
    HttpProtocolError,
    HttpResponseTooLarge,
    HttpRetryExhausted,
    HttpStatusError,
    RetryPolicy,
)

TEST_URL = "https://example.test/market-data.zip"


class FakeResponse:
    """Minimal context-managed response for deterministic tests."""

    def __init__(
        self,
        content: bytes,
        *,
        status: int = 200,
        reason: str = "OK",
        headers: dict[str, str] | None = None,
    ) -> None:
        self._content = BytesIO(content)
        self.status = status
        self.reason = reason
        self.headers = headers or {}

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._content.read(size)


class SequenceOpener:
    """Return responses or raise errors in a fixed order."""

    def __init__(self, events: Iterable[FakeResponse | Exception]) -> None:
        self.events = list(events)
        self.requests = []
        self.timeouts: list[float] = []

    def __call__(self, request: object, *, timeout: float) -> FakeResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        event = self.events.pop(0)
        if isinstance(event, Exception):
            raise event
        return event


def _http_error(status: int, reason: str) -> HTTPError:
    return HTTPError(TEST_URL, status, reason, {}, None)


def test_success_publishes_an_atomic_download_receipt(tmp_path: Path) -> None:
    opener = SequenceOpener([FakeResponse(b"complete", headers={"Content-Length": "8"})])
    destination = tmp_path / "market-data.zip"
    client = HttpClient(opener=opener, sleeper=lambda _seconds: None)

    receipt = client.download(TEST_URL, destination, timeout_seconds=4, max_bytes=8)

    assert destination.read_bytes() == b"complete"
    assert receipt.destination == destination
    assert receipt.status_code == 200
    assert receipt.bytes_written == 8
    assert receipt.attempts == 1
    assert opener.timeouts == [4]
    assert not destination.with_name(f"{destination.name}.part").exists()


def test_retryable_statuses_use_exponential_backoff_then_succeed(tmp_path: Path) -> None:
    opener = SequenceOpener(
        [
            _http_error(503, "Service Unavailable"),
            _http_error(429, "Too Many Requests"),
            FakeResponse(b"ok"),
        ]
    )
    sleeps: list[float] = []
    policy = RetryPolicy(
        max_attempts=3,
        initial_backoff_seconds=0.25,
        multiplier=2,
        max_backoff_seconds=2,
    )
    client = HttpClient(policy, opener=opener, sleeper=sleeps.append)

    receipt = client.download(TEST_URL, tmp_path / "data.zip", max_bytes=10)

    assert receipt.attempts == 3
    assert sleeps == [0.25, 0.5]
    assert len(opener.requests) == 3


def test_non_retryable_status_fails_once_and_preserves_existing_file(tmp_path: Path) -> None:
    opener = SequenceOpener([_http_error(404, "Not Found")])
    sleeps: list[float] = []
    destination = tmp_path / "data.zip"
    destination.write_bytes(b"previous-good-file")
    client = HttpClient(opener=opener, sleeper=sleeps.append)

    with pytest.raises(HttpStatusError, match="non-retryable HTTP 404") as error:
        client.download(TEST_URL, destination, max_bytes=100)

    assert error.value.status_code == 404
    assert destination.read_bytes() == b"previous-good-file"
    assert len(opener.requests) == 1
    assert sleeps == []


def test_transport_errors_exhaust_attempts_and_remove_partial_file(tmp_path: Path) -> None:
    opener = SequenceOpener([URLError("offline"), URLError("offline"), URLError("offline")])
    sleeps: list[float] = []
    policy = RetryPolicy(
        max_attempts=3,
        initial_backoff_seconds=0.1,
        multiplier=2,
        max_backoff_seconds=1,
    )
    client = HttpClient(policy, opener=opener, sleeper=sleeps.append)
    destination = tmp_path / "data.zip"

    with pytest.raises(HttpRetryExhausted, match="failed after 3 attempts") as error:
        client.download(TEST_URL, destination, max_bytes=100)

    assert error.value.attempts == 3
    assert sleeps == [0.1, 0.2]
    assert not destination.exists()
    assert not destination.with_name(f"{destination.name}.part").exists()


def test_timeout_is_forwarded_on_every_attempt(tmp_path: Path) -> None:
    opener = SequenceOpener([TimeoutError("slow"), FakeResponse(b"ok")])
    client = HttpClient(opener=opener, sleeper=lambda _seconds: None)

    receipt = client.download(
        TEST_URL,
        tmp_path / "data.zip",
        timeout_seconds=7.5,
        max_bytes=10,
    )

    assert receipt.attempts == 2
    assert opener.timeouts == [7.5, 7.5]


def test_announced_size_limit_is_permanent_and_not_retried(tmp_path: Path) -> None:
    opener = SequenceOpener([FakeResponse(b"ignored", headers={"Content-Length": "101"})])
    sleeps: list[float] = []
    client = HttpClient(opener=opener, sleeper=sleeps.append)

    with pytest.raises(HttpResponseTooLarge, match="announced 101 bytes"):
        client.download(TEST_URL, tmp_path / "data.zip", max_bytes=100)

    assert len(opener.requests) == 1
    assert sleeps == []


def test_observed_size_limit_preserves_existing_destination(tmp_path: Path) -> None:
    opener = SequenceOpener([FakeResponse(b"01234567890")])
    destination = tmp_path / "data.zip"
    destination.write_bytes(b"previous")
    client = HttpClient(opener=opener, sleeper=lambda _seconds: None)

    with pytest.raises(HttpResponseTooLarge, match="exceeded the 10-byte"):
        client.download(TEST_URL, destination, max_bytes=10)

    assert destination.read_bytes() == b"previous"
    assert not destination.with_name(f"{destination.name}.part").exists()


def test_empty_response_is_not_published_or_retried(tmp_path: Path) -> None:
    opener = SequenceOpener([FakeResponse(b"")])
    sleeps: list[float] = []
    client = HttpClient(opener=opener, sleeper=sleeps.append)
    destination = tmp_path / "data.zip"

    with pytest.raises(HttpEmptyResponse, match="empty response"):
        client.download(TEST_URL, destination, max_bytes=10)

    assert not destination.exists()
    assert sleeps == []


def test_invalid_retry_policies_fail_before_network_use() -> None:
    invalid_policies = (
        {"max_attempts": 0},
        {"initial_backoff_seconds": 0},
        {"multiplier": 0.5},
        {"initial_backoff_seconds": 2, "max_backoff_seconds": 1},
        {"retryable_statuses": frozenset({999})},
    )

    for values in invalid_policies:
        with pytest.raises(ValueError):
            RetryPolicy(**values)


def test_exponential_backoff_is_capped() -> None:
    policy = RetryPolicy(
        max_attempts=5,
        initial_backoff_seconds=1,
        multiplier=3,
        max_backoff_seconds=4,
    )

    assert [policy.backoff_after(attempt) for attempt in range(1, 5)] == [1, 3, 4, 4]


def test_invalid_content_length_is_a_protocol_error_without_retry(tmp_path: Path) -> None:
    opener = SequenceOpener([FakeResponse(b"content", headers={"Content-Length": "not-a-number"})])
    sleeps: list[float] = []
    client = HttpClient(opener=opener, sleeper=sleeps.append)

    with pytest.raises(HttpProtocolError, match="Content-Length is not an integer"):
        client.download(TEST_URL, tmp_path / "data.zip", max_bytes=100)

    assert len(opener.requests) == 1
    assert sleeps == []


def test_invalid_download_arguments_fail_before_opening_network(tmp_path: Path) -> None:
    opener = SequenceOpener([])
    client = HttpClient(opener=opener, sleeper=lambda _seconds: None)
    destination = tmp_path / "data.zip"

    invalid_calls = (
        {"url": "file:///private/data", "timeout_seconds": 1, "max_bytes": 1},
        {"url": TEST_URL, "timeout_seconds": 0, "max_bytes": 1},
        {"url": TEST_URL, "timeout_seconds": 1, "max_bytes": 0},
    )
    for arguments in invalid_calls:
        with pytest.raises(ValueError):
            client.download(destination=destination, **arguments)

    assert opener.requests == []
