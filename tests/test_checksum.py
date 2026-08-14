"""Tests for strict publisher checksum parsing and file verification."""

from __future__ import annotations

from pathlib import Path

import pytest

from marketpulse.ingestion.checksum import (
    ChecksumFormatError,
    ChecksumMismatchError,
    PublishedChecksum,
    parse_sha256_checksum,
    read_sha256_checksum,
    sha256_file,
    verify_sha256,
)

ARCHIVE_NAME = "BTCUSDT-1m-2024-01-01.zip"
KNOWN_SHA256 = "4ec2915e610ab4e9a4d5e86a5ada1c15bbf6b5db343cdb385681d6ac97166a4e"


def test_parses_the_official_single_record_format() -> None:
    record = parse_sha256_checksum(
        f"{KNOWN_SHA256}  {ARCHIVE_NAME}\n",
        expected_filename=ARCHIVE_NAME,
    )

    assert record == PublishedChecksum(sha256=KNOWN_SHA256, filename=ARCHIVE_NAME)


def test_uppercase_digest_is_normalized_to_lowercase() -> None:
    record = parse_sha256_checksum(
        f"{KNOWN_SHA256.upper()}  {ARCHIVE_NAME}\r\n",
        expected_filename=ARCHIVE_NAME,
    )

    assert record.sha256 == KNOWN_SHA256


def test_checksum_must_name_the_exact_requested_archive() -> None:
    with pytest.raises(ChecksumFormatError, match="expected the exact source file"):
        parse_sha256_checksum(
            f"{KNOWN_SHA256}  ETHUSDT-1m-2024-01-01.zip\n",
            expected_filename=ARCHIVE_NAME,
        )


@pytest.mark.parametrize(
    "content",
    [
        f"{KNOWN_SHA256} {ARCHIVE_NAME}\n",
        f"short  {ARCHIVE_NAME}\n",
        f"{KNOWN_SHA256}  {ARCHIVE_NAME}\nextra",
        "",
    ],
)
def test_malformed_checksum_records_are_rejected(content: str) -> None:
    with pytest.raises(ChecksumFormatError):
        parse_sha256_checksum(content, expected_filename=ARCHIVE_NAME)


def test_checksum_file_has_a_small_byte_boundary(tmp_path: Path) -> None:
    checksum_path = tmp_path / f"{ARCHIVE_NAME}.CHECKSUM"
    checksum_path.write_bytes(b"x" * 11)

    with pytest.raises(ChecksumFormatError, match="10-byte safety limit"):
        read_sha256_checksum(
            checksum_path,
            expected_filename=ARCHIVE_NAME,
            max_bytes=10,
        )


def test_checksum_file_must_be_ascii(tmp_path: Path) -> None:
    checksum_path = tmp_path / f"{ARCHIVE_NAME}.CHECKSUM"
    checksum_path.write_bytes(b"\xff" * 64)

    with pytest.raises(ChecksumFormatError, match="ASCII"):
        read_sha256_checksum(checksum_path, expected_filename=ARCHIVE_NAME)


def test_matching_digest_returns_the_calculated_sha256(tmp_path: Path) -> None:
    archive_path = tmp_path / ARCHIVE_NAME
    archive_path.write_bytes(b"trusted bytes")
    expected = sha256_file(archive_path)

    assert verify_sha256(archive_path, expected_sha256=expected) == expected


def test_mismatch_reports_expected_and_calculated_digests(tmp_path: Path) -> None:
    archive_path = tmp_path / ARCHIVE_NAME
    archive_path.write_bytes(b"changed bytes")

    with pytest.raises(ChecksumMismatchError, match="SHA-256 mismatch") as error:
        verify_sha256(archive_path, expected_sha256="0" * 64)

    assert error.value.expected == "0" * 64
    assert error.value.actual == sha256_file(archive_path)
    assert error.value.path == archive_path
