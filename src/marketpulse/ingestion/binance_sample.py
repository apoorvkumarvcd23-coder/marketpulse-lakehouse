"""Download and parse one bounded Binance BTCUSDT learning sample."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import TextIOWrapper
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from zipfile import BadZipFile, ZipFile

from pydantic import ValidationError

from marketpulse.contracts import MarketCandle
from marketpulse.ingestion.checksum import (
    MAX_CHECKSUM_FILE_BYTES,
    ChecksumError,
    PublishedChecksum,
    read_sha256_checksum,
    sha256_file,
    verify_sha256,
)
from marketpulse.ingestion.http_client import HttpClient, HttpClientError

SAMPLE_ARCHIVE_NAME = "BTCUSDT-1m-2024-01-01.zip"
SAMPLE_MEMBER_NAME = "BTCUSDT-1m-2024-01-01.csv"
SAMPLE_URL = f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1m/{SAMPLE_ARCHIVE_NAME}"
SAMPLE_CHECKSUM_NAME = f"{SAMPLE_ARCHIVE_NAME}.CHECKSUM"
SAMPLE_CHECKSUM_URL = f"{SAMPLE_URL}.CHECKSUM"
DEFAULT_SAMPLE_DIRECTORY = Path("data/samples")
MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 10 * 1024 * 1024
MAX_SAMPLE_ROWS = 100
MIN_SAMPLE_TIMESTAMP_MS = 946_684_800_000  # 2000-01-01T00:00:00Z
MAX_SAMPLE_TIMESTAMP_MS = 4_102_444_800_000  # 2100-01-01T00:00:00Z


class SampleDownloadError(RuntimeError):
    """The fixed public sample could not be downloaded safely."""


class SampleFormatError(ValueError):
    """The downloaded archive does not match the expected sample format."""


class SampleIntegrityError(ValueError):
    """The archive could not be tied to Binance's published SHA-256 checksum."""


@dataclass(frozen=True, slots=True)
class SampleBatch:
    """A source archive and the trusted candle records parsed from it."""

    archive_path: Path
    archive_sha256: str
    candles: tuple[MarketCandle, ...]
    checksum_path: Path | None = None
    official_checksum_verified: bool = False


@dataclass(frozen=True, slots=True)
class VerifiedSampleDownload:
    """A downloaded archive and checksum that matched before publication."""

    archive_path: Path
    checksum_path: Path
    sha256: str


def download_sample(
    destination: Path,
    *,
    url: str = SAMPLE_URL,
    checksum_url: str | None = None,
    checksum_destination: Path | None = None,
    timeout_seconds: float = 30.0,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
    http_client: HttpClient | None = None,
) -> VerifiedSampleDownload:
    """Download candidates, verify the official checksum, then publish both files."""
    destination = Path(destination)
    published_checksum_path = Path(
        checksum_destination or destination.with_name(f"{destination.name}.CHECKSUM")
    )
    source_filename = PurePosixPath(urlsplit(url).path).name
    if not source_filename:
        raise ValueError("url must identify one source file")

    candidate_id = uuid4().hex
    archive_candidate = destination.with_name(f".{destination.name}.{candidate_id}.candidate")
    checksum_candidate = published_checksum_path.with_name(
        f".{published_checksum_path.name}.{candidate_id}.candidate"
    )
    client = http_client or HttpClient()
    try:
        client.download(
            checksum_url or f"{url}.CHECKSUM",
            checksum_candidate,
            timeout_seconds=timeout_seconds,
            max_bytes=MAX_CHECKSUM_FILE_BYTES,
        )
        client.download(
            url,
            archive_candidate,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
        )
        published = read_sha256_checksum(
            checksum_candidate,
            expected_filename=source_filename,
        )
        calculated = verify_sha256(
            archive_candidate,
            expected_sha256=published.sha256,
        )
        archive_candidate.replace(destination)
        checksum_candidate.replace(published_checksum_path)
    except (HttpClientError, ChecksumError, OSError) as exc:
        raise SampleDownloadError(
            f"could not download and verify {source_filename}: {exc}"
        ) from exc
    finally:
        for candidate in (archive_candidate, checksum_candidate):
            candidate.unlink(missing_ok=True)
            candidate.with_name(f"{candidate.name}.part").unlink(missing_ok=True)

    return VerifiedSampleDownload(
        archive_path=destination,
        checksum_path=published_checksum_path,
        sha256=calculated,
    )


def _read_official_checksum(checksum_path: Path) -> PublishedChecksum:
    try:
        return read_sha256_checksum(
            checksum_path,
            expected_filename=SAMPLE_ARCHIVE_NAME,
        )
    except ChecksumError as exc:
        raise SampleIntegrityError(
            f"official checksum is unavailable or invalid: {exc}; rerun with --force"
        ) from exc


def milliseconds_to_utc(value: str | int) -> datetime:
    """Convert an explicit Unix-millisecond value to a timezone-aware UTC datetime."""
    if isinstance(value, bool):
        raise SampleFormatError("timestamp must be an integer number of milliseconds")
    try:
        timestamp_ms = int(value)
    except (TypeError, ValueError) as exc:
        raise SampleFormatError("timestamp must be an integer number of milliseconds") from exc

    if not MIN_SAMPLE_TIMESTAMP_MS <= timestamp_ms < MAX_SAMPLE_TIMESTAMP_MS:
        raise SampleFormatError(
            "sample timestamp is outside the millisecond range; "
            "microsecond detection is introduced on Day 17"
        )

    seconds, milliseconds = divmod(timestamp_ms, 1_000)
    return datetime.fromtimestamp(seconds, tz=UTC) + timedelta(milliseconds=milliseconds)


def _parse_kline_row(
    row: list[str],
    *,
    source_file: str,
    checksum: str,
    ingestion_time: datetime,
    run_id: UUID,
) -> MarketCandle:
    if len(row) != 12:
        raise SampleFormatError(f"expected 12 CSV columns, received {len(row)}")

    try:
        return MarketCandle.model_validate(
            {
                "symbol": "BTCUSDT",
                "interval": "1m",
                "open_time": milliseconds_to_utc(row[0]),
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "volume": row[5],
                "close_time": milliseconds_to_utc(row[6]),
                "quote_volume": row[7],
                "trade_count": int(row[8]),
                "source_file": source_file,
                "checksum": checksum,
                "ingestion_time": ingestion_time,
                "run_id": run_id,
            }
        )
    except (ValidationError, ValueError) as exc:
        raise SampleFormatError(f"row failed MarketCandle validation: {exc}") from exc


def read_sample_archive(
    archive_path: Path,
    *,
    limit: int = 5,
    ingestion_time: datetime | None = None,
    run_id: UUID | None = None,
    expected_sha256: str | None = None,
    checksum_path: Path | None = None,
) -> SampleBatch:
    """Read a few rows from the expected CSV member without extracting the ZIP."""
    if not 1 <= limit <= MAX_SAMPLE_ROWS:
        raise ValueError(f"limit must be between 1 and {MAX_SAMPLE_ROWS}")

    archive_path = Path(archive_path)
    try:
        checksum = (
            verify_sha256(archive_path, expected_sha256=expected_sha256)
            if expected_sha256 is not None
            else sha256_file(archive_path)
        )
    except ChecksumError as exc:
        if expected_sha256 is not None:
            raise SampleIntegrityError(
                f"could not verify ZIP archive {archive_path}: {exc}"
            ) from exc
        raise SampleFormatError(f"could not read ZIP archive {archive_path}: {exc}") from exc
    accepted_at = ingestion_time or datetime.now(UTC)
    batch_run_id = run_id or uuid4()

    try:
        with ZipFile(archive_path) as archive:
            members = [member for member in archive.infolist() if not member.is_dir()]
            if len(members) != 1 or members[0].filename != SAMPLE_MEMBER_NAME:
                names = ", ".join(member.filename for member in members) or "<empty>"
                raise SampleFormatError(
                    f"archive must contain only {SAMPLE_MEMBER_NAME}; found {names}"
                )

            member = members[0]
            if member.file_size > MAX_UNCOMPRESSED_BYTES:
                raise SampleFormatError(
                    f"CSV expands to {member.file_size} bytes; limit is {MAX_UNCOMPRESSED_BYTES}"
                )

            candles: list[MarketCandle] = []
            with archive.open(member, "r") as raw_source:
                with TextIOWrapper(raw_source, encoding="utf-8", newline="") as text_source:
                    for row_number, row in enumerate(csv.reader(text_source), start=1):
                        if len(candles) == limit:
                            break
                        try:
                            candle = _parse_kline_row(
                                row,
                                source_file=member.filename,
                                checksum=checksum,
                                ingestion_time=accepted_at,
                                run_id=batch_run_id,
                            )
                        except SampleFormatError as exc:
                            raise SampleFormatError(
                                f"{member.filename} row {row_number}: {exc}"
                            ) from exc
                        candles.append(candle)
    except UnicodeError as exc:
        raise SampleFormatError(f"{SAMPLE_MEMBER_NAME} is not valid UTF-8 text: {exc}") from exc
    except (BadZipFile, OSError) as exc:
        raise SampleFormatError(f"could not read ZIP archive {archive_path}: {exc}") from exc

    if not candles:
        raise SampleFormatError(f"{SAMPLE_MEMBER_NAME} contains no candle rows")

    return SampleBatch(
        archive_path=archive_path,
        archive_sha256=checksum,
        candles=tuple(candles),
        checksum_path=Path(checksum_path) if checksum_path is not None else None,
        official_checksum_verified=expected_sha256 is not None,
    )


def fetch_sample(
    output_directory: Path = DEFAULT_SAMPLE_DIRECTORY,
    *,
    limit: int = 5,
    force: bool = False,
) -> SampleBatch:
    """Download the fixed sample when needed and return its first validated candles."""
    archive_path = Path(output_directory) / SAMPLE_ARCHIVE_NAME
    checksum_path = Path(output_directory) / SAMPLE_CHECKSUM_NAME
    if force or not archive_path.is_file() or not checksum_path.is_file():
        verified = download_sample(
            archive_path,
            checksum_destination=checksum_path,
        )
        expected_sha256 = verified.sha256
    elif not 0 < archive_path.stat().st_size <= MAX_DOWNLOAD_BYTES:
        raise SampleDownloadError(
            "cached sample is empty or exceeds the download safety limit; rerun with --force"
        )
    else:
        expected_sha256 = _read_official_checksum(checksum_path).sha256

    return read_sample_archive(
        archive_path,
        limit=limit,
        expected_sha256=expected_sha256,
        checksum_path=checksum_path,
    )
