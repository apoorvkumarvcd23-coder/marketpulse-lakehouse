"""First tests for the bounded Binance learning sample."""

from __future__ import annotations

import hashlib
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
    SAMPLE_CHECKSUM_NAME,
    SAMPLE_MEMBER_NAME,
    SampleDownloadError,
    SampleFormatError,
    SampleIntegrityError,
    download_sample,
    fetch_sample,
    milliseconds_to_utc,
    read_sample_archive,
    sha256_file,
)
from marketpulse.ingestion.http_client import HttpClient

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


class SequenceOpener:
    """Return a checksum response and then an archive response."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses

    def __call__(self, _request: object, *, timeout: float) -> FakeResponse:
        del timeout
        return self.responses.pop(0)


def _checksum_bytes(content: bytes, *, filename: str = SAMPLE_ARCHIVE_NAME) -> bytes:
    digest = hashlib.sha256(content).hexdigest()
    return f"{digest}  {filename}\n".encode("ascii")


def _verified_client(
    content: bytes,
    *,
    checksum_content: bytes | None = None,
    archive_announced_length: int | None = None,
) -> HttpClient:
    opener = SequenceOpener(
        [
            FakeResponse(checksum_content or _checksum_bytes(content)),
            FakeResponse(content, announced_length=archive_announced_length),
        ]
    )
    return HttpClient(opener=opener, sleeper=lambda _seconds: None)


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


def test_download_is_published_only_after_it_finishes(tmp_path: Path) -> None:
    content = _archive_bytes()
    client = _verified_client(
        content,
        archive_announced_length=len(content),
    )
    destination = tmp_path / SAMPLE_ARCHIVE_NAME

    result = download_sample(
        destination,
        timeout_seconds=2,
        max_bytes=len(content),
        http_client=client,
    )

    assert result.archive_path == destination
    assert result.archive_path.read_bytes() == content
    assert result.checksum_path == tmp_path / SAMPLE_CHECKSUM_NAME
    assert result.checksum_path.read_bytes() == _checksum_bytes(content)
    assert result.sha256 == hashlib.sha256(content).hexdigest()
    assert not destination.with_name(f"{destination.name}.part").exists()
    assert list(tmp_path.glob("*.candidate")) == []


def test_download_size_limit_removes_partial_file(tmp_path: Path) -> None:
    content = _archive_bytes()
    client = _verified_client(content)
    destination = tmp_path / SAMPLE_ARCHIVE_NAME

    with pytest.raises(SampleDownloadError, match="response exceeded"):
        download_sample(destination, max_bytes=10, http_client=client)

    assert not destination.exists()
    assert not destination.with_name(f"{destination.name}.part").exists()


def test_missing_archive_is_reported_as_a_sample_format_error(tmp_path: Path) -> None:
    archive_path = tmp_path / SAMPLE_ARCHIVE_NAME

    with pytest.raises(SampleFormatError, match="could not read ZIP archive"):
        read_sample_archive(archive_path, ingestion_time=INGESTION_TIME)


def test_empty_csv_is_rejected(tmp_path: Path) -> None:
    archive_path = _write_archive(tmp_path / SAMPLE_ARCHIVE_NAME, ())

    with pytest.raises(SampleFormatError, match="contains no candle rows"):
        read_sample_archive(archive_path, ingestion_time=INGESTION_TIME)


def test_archive_with_multiple_files_is_rejected(tmp_path: Path) -> None:
    archive_path = tmp_path / SAMPLE_ARCHIVE_NAME
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(SAMPLE_MEMBER_NAME, VALID_ROWS[0])
        archive.writestr("surprise.csv", VALID_ROWS[1])

    with pytest.raises(SampleFormatError, match="archive must contain only"):
        read_sample_archive(archive_path, ingestion_time=INGESTION_TIME)


def test_expanded_csv_size_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive_path = _write_archive(tmp_path / SAMPLE_ARCHIVE_NAME, VALID_ROWS)
    monkeypatch.setattr(binance_sample, "MAX_UNCOMPRESSED_BYTES", 1)

    with pytest.raises(SampleFormatError, match="CSV expands to"):
        read_sample_archive(archive_path, ingestion_time=INGESTION_TIME)


def test_non_utf8_csv_is_rejected_with_a_domain_error(tmp_path: Path) -> None:
    archive_path = tmp_path / SAMPLE_ARCHIVE_NAME
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(SAMPLE_MEMBER_NAME, b"\xff\xfe\x00")

    with pytest.raises(SampleFormatError, match="is not valid UTF-8 text"):
        read_sample_archive(archive_path, ingestion_time=INGESTION_TIME)


def test_contract_validation_failure_keeps_row_context(tmp_path: Path) -> None:
    impossible = VALID_ROWS[0].split(",")
    impossible[2] = "1.00000000"
    archive_path = _write_archive(tmp_path / SAMPLE_ARCHIVE_NAME, (",".join(impossible),))

    with pytest.raises(
        SampleFormatError,
        match=r"\.csv row 1: row failed MarketCandle validation",
    ):
        read_sample_archive(archive_path, ingestion_time=INGESTION_TIME)


@pytest.mark.parametrize("limit", [0, 101])
def test_row_limit_must_stay_inside_the_learning_boundary(tmp_path: Path, limit: int) -> None:
    archive_path = _write_archive(tmp_path / SAMPLE_ARCHIVE_NAME, VALID_ROWS)

    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        read_sample_archive(archive_path, limit=limit, ingestion_time=INGESTION_TIME)


def test_announced_download_size_is_rejected_before_writing(tmp_path: Path) -> None:
    content = _archive_bytes()
    client = _verified_client(
        content,
        archive_announced_length=len(content) + 1,
    )
    destination = tmp_path / SAMPLE_ARCHIVE_NAME

    with pytest.raises(SampleDownloadError, match="response announced"):
        download_sample(destination, max_bytes=len(content), http_client=client)

    assert not destination.exists()
    assert not destination.with_name(f"{destination.name}.part").exists()


def test_empty_download_removes_partial_file(tmp_path: Path) -> None:
    client = _verified_client(b"")
    destination = tmp_path / SAMPLE_ARCHIVE_NAME

    with pytest.raises(SampleDownloadError, match="server returned an empty response"):
        download_sample(destination, http_client=client)

    assert not destination.exists()
    assert not destination.with_name(f"{destination.name}.part").exists()


def test_checksum_mismatch_preserves_previous_published_pair(tmp_path: Path) -> None:
    new_content = _archive_bytes()
    checksum_for_different_bytes = _checksum_bytes(b"different archive")
    client = _verified_client(new_content, checksum_content=checksum_for_different_bytes)
    destination = tmp_path / SAMPLE_ARCHIVE_NAME
    checksum_path = tmp_path / SAMPLE_CHECKSUM_NAME
    destination.write_bytes(b"previous archive")
    checksum_path.write_bytes(_checksum_bytes(b"previous archive"))

    with pytest.raises(SampleDownloadError, match="SHA-256 mismatch"):
        download_sample(destination, http_client=client)

    assert destination.read_bytes() == b"previous archive"
    assert checksum_path.read_bytes() == _checksum_bytes(b"previous archive")
    assert list(tmp_path.glob("*.candidate")) == []


def test_checksum_with_wrong_source_filename_is_not_published(tmp_path: Path) -> None:
    content = _archive_bytes()
    client = _verified_client(
        content,
        checksum_content=_checksum_bytes(content, filename="ETHUSDT-1m-2024-01-01.zip"),
    )
    destination = tmp_path / SAMPLE_ARCHIVE_NAME

    with pytest.raises(SampleDownloadError, match="expected the exact source file"):
        download_sample(destination, http_client=client)

    assert not destination.exists()
    assert not (tmp_path / SAMPLE_CHECKSUM_NAME).exists()
    assert list(tmp_path.glob("*.candidate")) == []


def test_cached_sample_is_verified_against_its_official_checksum(tmp_path: Path) -> None:
    content = _archive_bytes()
    archive_path = tmp_path / SAMPLE_ARCHIVE_NAME
    checksum_path = tmp_path / SAMPLE_CHECKSUM_NAME
    archive_path.write_bytes(content)
    checksum_path.write_bytes(_checksum_bytes(content))

    batch = fetch_sample(tmp_path, limit=1)

    assert len(batch.candles) == 1
    assert batch.archive_sha256 == hashlib.sha256(content).hexdigest()
    assert batch.checksum_path == checksum_path
    assert batch.official_checksum_verified is True


def test_tampered_cached_sample_is_rejected_before_parsing(tmp_path: Path) -> None:
    original_content = _archive_bytes()
    archive_path = tmp_path / SAMPLE_ARCHIVE_NAME
    checksum_path = tmp_path / SAMPLE_CHECKSUM_NAME
    archive_path.write_bytes(b"tampered archive")
    checksum_path.write_bytes(_checksum_bytes(original_content))

    with pytest.raises(SampleIntegrityError, match="SHA-256 mismatch"):
        fetch_sample(tmp_path, limit=1)
