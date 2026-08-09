"""First tests for the bounded Binance learning sample."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from marketpulse.ingestion import binance_sample
from marketpulse.ingestion.binance_sample import (
    SAMPLE_ARCHIVE_NAME,
    SAMPLE_MEMBER_NAME,
    SampleDownloadError,
    SampleFormatError,
    download_sample,
    milliseconds_to_utc,
    read_sample_archive,
    sha256_file,
)

INGESTION_TIME = datetime(2026, 8, 9, 13, 30, tzinfo=UTC)
RUN_ID = UUID("7e3a91f4-4ead-45e0-a811-08839e4275f9")
VALID_ROWS = (
    "1704067200000,42283.58000000,42288.00000000,42261.02000000,"
    "42266.95000000,13.70612000,1704067259999,579426.35515540,"
    "624,6.64918000,281051.16154220,0",
    "1704067260000,42266.94000000,42282.26000000,42265.00000000,"
    "42280.00000000,8.98765000,1704067319999,379989.12340000,"
    "512,4.10000000,173340.00000000,0",
)


def _write_archive(path: Path, rows: tuple[str, ...], member: str = SAMPLE_MEMBER_NAME) -> Path:
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(member, "\n".join(rows))
    return path


def _archive_bytes(rows: tuple[str, ...] = VALID_ROWS) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(SAMPLE_MEMBER_NAME, "\n".join(rows))
    return buffer.getvalue()


class FakeResponse:
    """Small context-managed HTTP response used without network access."""

    def __init__(self, content: bytes, announced_length: int | None = None) -> None:
        self._content = BytesIO(content)
        self.headers = {}
        if announced_length is not None:
            self.headers["Content-Length"] = str(announced_length)

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._content.read(size)


def test_archive_rows_become_trusted_market_candles(tmp_path: Path) -> None:
    archive_path = _write_archive(tmp_path / SAMPLE_ARCHIVE_NAME, VALID_ROWS)

    batch = read_sample_archive(
        archive_path,
        limit=2,
        ingestion_time=INGESTION_TIME,
        run_id=RUN_ID,
    )

    first = batch.candles[0]
    assert len(batch.candles) == 2
    assert first.open_time == datetime(2024, 1, 1, tzinfo=UTC)
    assert first.close_time == datetime(2024, 1, 1, 0, 0, 59, 999000, tzinfo=UTC)
    assert first.open == Decimal("42283.58000000")
    assert first.source_file == SAMPLE_MEMBER_NAME
    assert first.checksum == sha256_file(archive_path) == batch.archive_sha256
    assert first.run_id == batch.candles[1].run_id == RUN_ID


def test_row_limit_bounds_the_learning_sample(tmp_path: Path) -> None:
    archive_path = _write_archive(tmp_path / SAMPLE_ARCHIVE_NAME, VALID_ROWS)

    batch = read_sample_archive(archive_path, limit=1, ingestion_time=INGESTION_TIME)

    assert len(batch.candles) == 1


def test_millisecond_parser_rejects_microseconds_instead_of_guessing() -> None:
    assert milliseconds_to_utc("1704067200000") == datetime(2024, 1, 1, tzinfo=UTC)

    with pytest.raises(SampleFormatError, match="microsecond detection is introduced on Day 17"):
        milliseconds_to_utc("1735689600000000")


def test_wrong_column_count_reports_the_member_and_row(tmp_path: Path) -> None:
    archive_path = _write_archive(tmp_path / SAMPLE_ARCHIVE_NAME, ("one,two,three",))

    with pytest.raises(SampleFormatError, match=r"\.csv row 1: expected 12 CSV columns"):
        read_sample_archive(archive_path, ingestion_time=INGESTION_TIME)


def test_archive_member_must_be_the_expected_csv(tmp_path: Path) -> None:
    archive_path = _write_archive(
        tmp_path / SAMPLE_ARCHIVE_NAME,
        VALID_ROWS,
        member="../unexpected.csv",
    )

    with pytest.raises(SampleFormatError, match="archive must contain only"):
        read_sample_archive(archive_path, ingestion_time=INGESTION_TIME)


def test_corrupt_zip_is_rejected_with_a_domain_error(tmp_path: Path) -> None:
    archive_path = tmp_path / SAMPLE_ARCHIVE_NAME
    archive_path.write_bytes(b"this is not a zip archive")

    with pytest.raises(SampleFormatError, match="could not read ZIP archive"):
        read_sample_archive(archive_path, ingestion_time=INGESTION_TIME)


def test_download_is_published_only_after_it_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = _archive_bytes()
    monkeypatch.setattr(
        binance_sample,
        "urlopen",
        lambda _request, timeout: FakeResponse(content, announced_length=len(content)),
    )
    destination = tmp_path / SAMPLE_ARCHIVE_NAME

    result = download_sample(destination, timeout_seconds=2, max_bytes=len(content))

    assert result.read_bytes() == content
    assert not destination.with_name(f"{destination.name}.part").exists()


def test_download_size_limit_removes_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = _archive_bytes()
    monkeypatch.setattr(
        binance_sample,
        "urlopen",
        lambda _request, timeout: FakeResponse(content),
    )
    destination = tmp_path / SAMPLE_ARCHIVE_NAME

    with pytest.raises(SampleDownloadError, match="download exceeded"):
        download_sample(destination, max_bytes=10)

    assert not destination.exists()
    assert not destination.with_name(f"{destination.name}.part").exists()
