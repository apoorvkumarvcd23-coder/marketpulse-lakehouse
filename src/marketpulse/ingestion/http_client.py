"""Bounded HTTP downloads with explicit retry and backoff behavior."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

DOWNLOAD_CHUNK_BYTES = 64 * 1024
DEFAULT_RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


class HttpClientError(RuntimeError):
    """Base error for a download that the HTTP client could not publish."""


class HttpStatusError(HttpClientError):
    """A permanent HTTP response was rejected without a retry."""

    def __init__(self, url: str, status_code: int, reason: str) -> None:
        self.url = url
        self.status_code = status_code
        self.reason = reason
        super().__init__(f"GET {url} returned non-retryable HTTP {status_code} {reason}")


class HttpRetryExhausted(HttpClientError):
    """Every allowed attempt failed with a temporary transport or HTTP error."""

    def __init__(self, url: str, attempts: int, last_error: str) -> None:
        self.url = url
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"GET {url} failed after {attempts} attempts; last error: {last_error}")


class HttpResponseTooLarge(HttpClientError):
    """A declared or observed response size crossed the configured boundary."""


class HttpEmptyResponse(HttpClientError):
    """A successful HTTP response contained no file bytes."""


class HttpProtocolError(HttpClientError):
    """The response metadata could not be interpreted safely."""


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Retry count, temporary statuses, and capped exponential delays."""

    max_attempts: int = 3
    initial_backoff_seconds: float = 0.5
    multiplier: float = 2.0
    max_backoff_seconds: float = 8.0
    retryable_statuses: frozenset[int] = field(default_factory=lambda: DEFAULT_RETRYABLE_STATUSES)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.initial_backoff_seconds <= 0:
            raise ValueError("initial_backoff_seconds must be positive")
        if self.multiplier < 1:
            raise ValueError("multiplier must be at least 1")
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("max_backoff_seconds must be at least the initial backoff")
        if not all(100 <= status <= 599 for status in self.retryable_statuses):
            raise ValueError("retryable_statuses must contain valid HTTP status codes")

    def backoff_after(self, failed_attempt: int) -> float:
        """Return the capped delay after a one-based failed attempt number."""
        if failed_attempt < 1:
            raise ValueError("failed_attempt must be at least 1")
        delay = self.initial_backoff_seconds
        for _ in range(failed_attempt - 1):
            delay = min(delay * self.multiplier, self.max_backoff_seconds)
            if delay == self.max_backoff_seconds:
                break
        return delay


@dataclass(frozen=True, slots=True)
class DownloadReceipt:
    """Evidence describing the file successfully published by the client."""

    url: str
    destination: Path
    status_code: int
    bytes_written: int
    attempts: int


class HttpClient:
    """Download HTTP(S) resources with bounded retries and atomic publication."""

    def __init__(
        self,
        retry_policy: RetryPolicy | None = None,
        *,
        opener: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.retry_policy = retry_policy or RetryPolicy()
        self._opener = opener or urlopen
        self._sleeper = sleeper or time.sleep

    def download(
        self,
        url: str,
        destination: Path,
        *,
        timeout_seconds: float = 30.0,
        max_bytes: int,
        headers: Mapping[str, str] | None = None,
    ) -> DownloadReceipt:
        """Download into a temporary file and publish only a complete response."""
        scheme = urlsplit(url).scheme.lower()
        if scheme not in {"http", "https"}:
            raise ValueError("url must use http or https")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")

        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial_path = destination.with_name(f"{destination.name}.part")
        request_headers = {"User-Agent": "MarketPulse-Lakehouse/0.1"}
        request_headers.update(headers or {})

        for attempt in range(1, self.retry_policy.max_attempts + 1):
            partial_path.unlink(missing_ok=True)
            request = Request(url, headers=request_headers, method="GET")
            try:
                status_code, bytes_written = self._download_once(
                    request,
                    partial_path,
                    timeout_seconds=timeout_seconds,
                    max_bytes=max_bytes,
                )
            except HTTPError as exc:
                partial_path.unlink(missing_ok=True)
                if exc.code not in self.retry_policy.retryable_statuses:
                    raise HttpStatusError(url, exc.code, str(exc.reason)) from exc
                last_error = f"HTTP {exc.code} {exc.reason}"
            except (URLError, TimeoutError, ConnectionError) as exc:
                partial_path.unlink(missing_ok=True)
                last_error = f"{type(exc).__name__}: {exc}"
            except HttpClientError:
                partial_path.unlink(missing_ok=True)
                raise
            except (OSError, ValueError) as exc:
                partial_path.unlink(missing_ok=True)
                raise HttpClientError(
                    f"GET {url} could not write a complete response: {exc}"
                ) from exc
            else:
                try:
                    partial_path.replace(destination)
                except OSError as exc:
                    partial_path.unlink(missing_ok=True)
                    raise HttpClientError(
                        f"GET {url} could not publish {destination}: {exc}"
                    ) from exc
                return DownloadReceipt(
                    url=url,
                    destination=destination,
                    status_code=status_code,
                    bytes_written=bytes_written,
                    attempts=attempt,
                )

            if attempt == self.retry_policy.max_attempts:
                raise HttpRetryExhausted(url, attempt, last_error)
            self._sleeper(self.retry_policy.backoff_after(attempt))

        raise AssertionError("retry loop ended without returning or raising")

    def _download_once(
        self,
        request: Request,
        partial_path: Path,
        *,
        timeout_seconds: float,
        max_bytes: int,
    ) -> tuple[int, int]:
        with self._opener(request, timeout=timeout_seconds) as response:
            status_code = int(getattr(response, "status", 200) or 200)
            if not 200 <= status_code < 300:
                reason = str(getattr(response, "reason", "unexpected response"))
                raise HTTPError(request.full_url, status_code, reason, response.headers, None)

            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                try:
                    announced_bytes = int(content_length)
                except ValueError as exc:
                    raise HttpProtocolError(
                        f"response Content-Length is not an integer: {content_length!r}"
                    ) from exc
                if announced_bytes < 0:
                    raise HttpProtocolError("response Content-Length cannot be negative")
                if announced_bytes > max_bytes:
                    raise HttpResponseTooLarge(
                        f"response announced {announced_bytes} bytes; limit is {max_bytes}"
                    )

            bytes_written = 0
            with partial_path.open("wb") as target:
                while chunk := response.read(DOWNLOAD_CHUNK_BYTES):
                    bytes_written += len(chunk)
                    if bytes_written > max_bytes:
                        raise HttpResponseTooLarge(
                            f"response exceeded the {max_bytes}-byte safety limit"
                        )
                    target.write(chunk)

        if bytes_written == 0:
            raise HttpEmptyResponse("server returned an empty response")
        return status_code, bytes_written


__all__ = [
    "DownloadReceipt",
    "HttpClient",
    "HttpClientError",
    "HttpEmptyResponse",
    "HttpProtocolError",
    "HttpResponseTooLarge",
    "HttpRetryExhausted",
    "HttpStatusError",
    "RetryPolicy",
]
