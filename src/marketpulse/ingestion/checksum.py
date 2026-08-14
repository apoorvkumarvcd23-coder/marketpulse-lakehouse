"""Strict SHA-256 checksum parsing and file-integrity verification."""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from pathlib import Path

HASH_CHUNK_BYTES = 64 * 1024
MAX_CHECKSUM_FILE_BYTES = 1024
SHA256_HEX_PATTERN = re.compile(r"[0-9a-fA-F]{64}")
SHA256SUM_RECORD_PATTERN = re.compile(r"(?P<sha256>[0-9a-fA-F]{64})  (?P<filename>[^\r\n]+)")


class ChecksumError(ValueError):
    """Base error for an unreadable, invalid, or mismatched checksum."""


class ChecksumReadError(ChecksumError):
    """A checksum file or target file could not be read safely."""


class ChecksumFormatError(ChecksumError):
    """Published checksum text did not match the required single-record format."""


class ChecksumMismatchError(ChecksumError):
    """A file's calculated SHA-256 did not match the publisher's value."""

    def __init__(self, path: Path, expected: str, actual: str) -> None:
        self.path = Path(path)
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"SHA-256 mismatch for {self.path.name}: expected {expected}, calculated {actual}"
        )


@dataclass(frozen=True, slots=True)
class PublishedChecksum:
    """One publisher-provided SHA-256 digest bound to an exact file name."""

    sha256: str
    filename: str


def parse_sha256_checksum(text: str, *, expected_filename: str) -> PublishedChecksum:
    """Parse one GNU sha256sum-style text record for the expected source file."""
    if not expected_filename or any(mark in expected_filename for mark in ("/", "\\", "\r", "\n")):
        raise ValueError("expected_filename must be one plain file name")

    record_text = text.rstrip("\r\n")
    match = SHA256SUM_RECORD_PATTERN.fullmatch(record_text)
    if match is None:
        raise ChecksumFormatError(
            "checksum must contain exactly one '<64 hexadecimal characters>  <filename>' record"
        )

    filename = match.group("filename")
    if filename != expected_filename:
        raise ChecksumFormatError(
            f"checksum names {filename!r}; expected the exact source file {expected_filename!r}"
        )
    return PublishedChecksum(
        sha256=match.group("sha256").lower(),
        filename=filename,
    )


def read_sha256_checksum(
    path: Path,
    *,
    expected_filename: str,
    max_bytes: int = MAX_CHECKSUM_FILE_BYTES,
) -> PublishedChecksum:
    """Read a small ASCII checksum file and parse its single expected record."""
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")

    checksum_path = Path(path)
    try:
        with checksum_path.open("rb") as source:
            content = source.read(max_bytes + 1)
    except OSError as exc:
        raise ChecksumReadError(f"could not read checksum file {checksum_path}: {exc}") from exc

    if len(content) > max_bytes:
        raise ChecksumFormatError(f"checksum file exceeds the {max_bytes}-byte safety limit")
    if not content:
        raise ChecksumFormatError("checksum file is empty")
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ChecksumFormatError("checksum file must contain ASCII text") from exc
    return parse_sha256_checksum(text, expected_filename=expected_filename)


def sha256_file(path: Path) -> str:
    """Calculate a lowercase SHA-256 digest without loading the whole file at once."""
    digest = hashlib.sha256()
    target_path = Path(path)
    try:
        with target_path.open("rb") as source:
            while chunk := source.read(HASH_CHUNK_BYTES):
                digest.update(chunk)
    except OSError as exc:
        raise ChecksumReadError(f"could not read file for SHA-256 {target_path}: {exc}") from exc
    return digest.hexdigest()


def verify_sha256(path: Path, *, expected_sha256: str) -> str:
    """Return the calculated digest only when it matches the expected SHA-256."""
    if SHA256_HEX_PATTERN.fullmatch(expected_sha256) is None:
        raise ValueError("expected_sha256 must contain exactly 64 hexadecimal characters")

    expected = expected_sha256.lower()
    actual = sha256_file(path)
    if not hmac.compare_digest(actual, expected):
        raise ChecksumMismatchError(Path(path), expected, actual)
    return actual


__all__ = [
    "MAX_CHECKSUM_FILE_BYTES",
    "ChecksumError",
    "ChecksumFormatError",
    "ChecksumMismatchError",
    "ChecksumReadError",
    "PublishedChecksum",
    "parse_sha256_checksum",
    "read_sha256_checksum",
    "sha256_file",
    "verify_sha256",
]
