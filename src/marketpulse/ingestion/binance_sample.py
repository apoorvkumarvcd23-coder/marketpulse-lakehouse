"""Download and parse one bounded Binance BTCUSDT learning sample."""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import TextIOWrapper
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4
from zipfile import BadZipFile, ZipFile

from pydantic import ValidationError

from marketpulse.contracts import MarketCandle

SAMPLE_ARCHIVE_NAME = "BTCUSDT-1m-2024-01-01.zip"
SAMPLE_MEMBER_NAME = "BTCUSDT-1m-2024-01-01.csv"
SAMPLE_URL = f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1m/{SAMPLE_ARCHIVE_NAME}"
DEFAULT_SAMPLE_DIRECTORY = Path("data/samples")
DOWNLOAD_CHUNK_BYTES = 64 * 1024
MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 10 * 1024 * 1024
MAX_SAMPLE_ROWS = 100
MIN_SAMPLE_TIMESTAMP_MS = 946_684_800_000  # 2000-01-01T00:00:00Z
MAX_SAMPLE_TIMESTAMP_MS = 4_102_444_800_000  # 2100-01-01T00:00:00Z


class SampleDownloadError(RuntimeError):
    """The fixed public sample could not be downloaded safely."""


class SampleFormatError(ValueError):
    """The downloaded archive does not match the expected sample format."""


@dataclass(frozen=True, slots=True)
class SampleBatch:
    """A source archive and the trusted candle records parsed from it."""

    archive_path: Path
    archive_sha256: str
    candles: tuple[MarketCandle, ...]


def download_sample(
    destination: Path,
    *,
    url: str = SAMPLE_URL,
    timeout_seconds: float = 30.0,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
) -> Path:
    """Download once into a temporary file, then atomically publish the result."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial_path = destination.with_name(f"{destination.name}.part")
    partial_path.unlink(missing_ok=True)
    request = Request(url, headers={"User-Agent": "MarketPulse-Lakehouse/0.1"})

    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) > max_bytes:
                raise SampleDownloadError(
                    f"server announced {content_length} bytes; limit is {max_bytes}"
                )

            downloaded_bytes = 0
            with partial_path.open("wb") as target:
                while chunk := response.read(DOWNLOAD_CHUNK_BYTES):
                    downloaded_bytes += len(chunk)
                    if downloaded_bytes > max_bytes:
                        raise SampleDownloadError(
                            f"download exceeded the {max_bytes}-byte safety limit"
                        )
                    target.write(chunk)
    except SampleDownloadError:
        partial_path.unlink(missing_ok=True)
        raise
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        partial_path.unlink(missing_ok=True)
        raise SampleDownloadError(f"could not download {url}: {exc}") from exc

    if downloaded_bytes == 0:
        partial_path.unlink(missing_ok=True)
        raise SampleDownloadError("the server returned an empty file")

    partial_path.replace(destination)
    return destination


def sha256_file(path: Path) -> str:
    """Return the lowercase SHA-256 fingerprint of a local file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        while chunk := source.read(DOWNLOAD_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


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
) -> SampleBatch:
    """Read a few rows from the expected CSV member without extracting the ZIP."""
    if not 1 <= limit <= MAX_SAMPLE_ROWS:
        raise ValueError(f"limit must be between 1 and {MAX_SAMPLE_ROWS}")

    archive_path = Path(archive_path)
    try:
        checksum = sha256_file(archive_path)
    except OSError as exc:
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
    )


def fetch_sample(
    output_directory: Path = DEFAULT_SAMPLE_DIRECTORY,
    *,
    limit: int = 5,
    force: bool = False,
) -> SampleBatch:
    """Download the fixed sample when needed and return its first validated candles."""
    archive_path = Path(output_directory) / SAMPLE_ARCHIVE_NAME
    if force or not archive_path.is_file():
        download_sample(archive_path)
    elif not 0 < archive_path.stat().st_size <= MAX_DOWNLOAD_BYTES:
        raise SampleDownloadError(
            "cached sample is empty or exceeds the download safety limit; rerun with --force"
        )

    return read_sample_archive(archive_path, limit=limit)
