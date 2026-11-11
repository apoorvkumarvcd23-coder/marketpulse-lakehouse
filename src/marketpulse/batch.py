"""Bounded daily archives and atomic, immutable local analytics snapshots."""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from io import TextIOWrapper
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

import duckdb

from marketpulse.contracts import MarketCandle, MarketSymbol
from marketpulse.ingestion.binance_sample import download_sample
from marketpulse.ingestion.checksum import read_sha256_checksum, sha256_file, verify_sha256
from marketpulse.ingestion.dlt_candles import load_bounded_candles

ARCHIVE_LIMIT = 1024 * 1024
EXPANDED_LIMIT = 2 * 1024 * 1024
MAX_ROWS = 2880  # one day plus bounded duplicate overlap
BASE_URL = "https://data.binance.vision/data/spot/daily/klines"


class BatchError(ValueError):
    """A bounded batch could not be safely published."""


@dataclass(frozen=True)
class Source:
    symbol: str
    day: date

    @property
    def name(self) -> str:
        return f"{self.symbol}-1m-{self.day.isoformat()}.zip"

    @property
    def url(self) -> str:
        return f"{BASE_URL}/{self.symbol}/1m/{self.name}"

    @property
    def unit(self) -> str:
        return "us" if self.day >= date(2025, 1, 1) else "ms"


def plan(day: date, symbols: list[str] | None = None) -> tuple[Source, ...]:
    if not date(2020, 1, 1) <= day < datetime.now(UTC).date():
        raise BatchError("choose one completed UTC day from 2020 onwards")
    selected = symbols if symbols is not None else [s.value for s in MarketSymbol]
    if not selected or len(selected) > 3 or len(set(selected)) != len(selected):
        raise BatchError("select one to three distinct supported symbols")
    try:
        return tuple(Source(MarketSymbol(s).value, day) for s in sorted(selected))
    except ValueError as exc:
        raise BatchError("only BTCUSDT, ETHUSDT and SOLUSDT are supported") from exc


def source_time(value: str, unit: str) -> datetime:
    """Unit is explicit from the archive date, never guessed from magnitude."""
    if unit not in {"ms", "us"} or not re.fullmatch(r"[0-9]{1,16}", value):
        raise BatchError("timestamp must be unsigned integer text with explicit ms/us unit")
    divisor = 1000 if unit == "ms" else 1_000_000
    number = int(value)
    if not 1_577_836_800 * divisor <= number < 4_102_444_800 * divisor:
        raise BatchError("timestamp outside supported unit/range")
    seconds, fraction = divmod(number, divisor)
    return datetime.fromtimestamp(seconds, UTC) + timedelta(
        microseconds=fraction * (1000 if unit == "ms" else 1)
    )


def read_archive(path: Path, source: Source, run_id: str) -> tuple[list[MarketCandle], int]:
    published = read_sha256_checksum(
        path.with_name(path.name + ".CHECKSUM"), expected_filename=source.name
    )
    digest = verify_sha256(path, expected_sha256=published.sha256)
    if path.stat().st_size > ARCHIVE_LIMIT:
        raise BatchError("archive byte budget exceeded")
    unique: dict[datetime, MarketCandle] = {}
    duplicates = 0
    try:
        with ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) != 1 or members[0].filename != source.name[:-4] + ".csv":
                raise BatchError("archive must contain exactly its expected CSV member")
            member = members[0]
            if member.file_size > EXPANDED_LIMIT or member.flag_bits & 1:
                raise BatchError("expanded/encrypted archive is outside the budget")
            with archive.open(member) as raw, TextIOWrapper(raw, encoding="utf-8") as text:
                for row_number, row in enumerate(csv.reader(text), start=1):
                    if row_number > MAX_ROWS or len(row) != 12:
                        raise BatchError(f"row {row_number}: row/column budget violated")
                    try:
                        start = source_time(row[0], source.unit)
                        end = source_time(row[6], source.unit)
                        if (
                            start.date() != source.day
                            or start.second
                            or start.microsecond
                            or not start < end < start + timedelta(minutes=1)
                        ):
                            raise BatchError("wrong date, minute alignment or candle interval")
                        candle = MarketCandle.model_validate(
                            {
                                "symbol": source.symbol,
                                "interval": "1m",
                                "open_time": start,
                                "close_time": end,
                                "open": row[1],
                                "high": row[2],
                                "low": row[3],
                                "close": row[4],
                                "volume": row[5],
                                "quote_volume": row[7],
                                "trade_count": int(row[8]),
                                "source_file": source.url,
                                "checksum": digest,
                                "ingestion_time": datetime.now(UTC),
                                "run_id": run_id,
                            }
                        )
                        for field in ("open", "high", "low", "close", "volume", "quote_volume"):
                            value = getattr(candle, field)
                            if value >= 10**30:
                                raise BatchError("decimal magnitude exceeds DECIMAL(38,8)")
                            with localcontext() as context:
                                context.prec = 40
                                if value != value.quantize(Decimal("0.00000001")):
                                    raise BatchError("decimal precision exceeds DECIMAL(38,8)")
                    except (ValueError, ArithmeticError) as exc:
                        raise BatchError(f"row {row_number}: invalid typed candle") from exc
                    previous = unique.get(start)
                    if previous is not None:
                        fields = {"ingestion_time", "run_id"}
                        if previous.model_dump(exclude=fields) != candle.model_dump(exclude=fields):
                            raise BatchError(f"row {row_number}: conflicting duplicate key")
                        duplicates += 1
                    unique[start] = candle
    except (BadZipFile, UnicodeError, csv.Error, RuntimeError) as exc:
        raise BatchError("invalid ZIP/CSV encoding or integrity") from exc
    if not unique:
        raise BatchError("empty archive")
    return sorted(unique.values(), key=lambda c: c.open_time), duplicates


@contextmanager
def writer_lock(root: Path):
    """OS-owned nonblocking lock releases on process death; never unlink the lock file."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".writer.lock").open("a+b") as handle:
        handle.write(b"0")
        handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise BatchError("another batch writer is active") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def current_snapshot(root: Path) -> Path | None:
    pointer = root / "current.json"
    if not pointer.exists():
        return None
    try:
        run_id = json.loads(pointer.read_text())["run_id"]
        if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("invalid run id")
        snapshot = root / "runs" / run_id
        if not (snapshot / "report.json").is_file():
            raise ValueError("incomplete snapshot")
        return snapshot
    except (ValueError, KeyError, TypeError) as exc:
        raise BatchError("invalid current snapshot pointer") from exc


def build_analytics(database: Path, parquet: Path) -> None:
    with duckdb.connect(str(database)) as connection:
        connection.execute("SET TimeZone = 'UTC'")
        decimals = ", ".join(
            f"CAST({field} AS DECIMAL(38,8)) AS {field}"
            for field in ("open", "high", "low", "close", "volume", "quote_volume")
        )
        connection.execute(f"""
            CREATE OR REPLACE VIEW marketpulse_data.typed_candles AS
            SELECT symbol, interval, open_time, close_time, {decimals}, trade_count,
                   source_file, checksum, run_id, ingestion_time,
                   CAST(open_time AT TIME ZONE 'UTC' AS DATE) AS trade_date
            FROM marketpulse_data.market_candles
        """)
        connection.execute("""
            CREATE OR REPLACE VIEW marketpulse_data.daily_summary AS
            SELECT symbol, trade_date, COUNT(*) AS candle_count,
                   1440 AS expected_minutes, COUNT(*) / 1440.0 AS completeness,
                   ARG_MIN(open, open_time) AS open, MAX(high) AS high, MIN(low) AS low,
                   ARG_MAX(close, open_time) AS close, SUM(volume) AS volume,
                   ARG_MAX(close, open_time) / ARG_MIN(open, open_time) - 1 AS daily_return,
                   MIN(open_time) AS first_open_time, MAX(open_time) AS last_open_time
            FROM marketpulse_data.typed_candles GROUP BY symbol, trade_date
        """)
        escaped = str(parquet).replace("'", "''")
        connection.execute(f"""
            COPY (SELECT * FROM marketpulse_data.typed_candles ORDER BY symbol, open_time)
            TO '{escaped}' (FORMAT PARQUET, PARTITION_BY (symbol, trade_date))
        """)


def run_batch(
    day: date,
    *,
    root: Path = Path("data/batch"),
    symbols: list[str] | None = None,
    fixture_dir: Path | None = None,
) -> dict:
    sources = plan(day, symbols)
    run_id = uuid4().hex
    with writer_lock(root):
        previous = current_snapshot(root)
        stage = root / "runs" / run_id
        stage.mkdir(parents=True)
        report: dict = {
            "run_id": run_id,
            "day": day.isoformat(),
            "mode": ("synthetic-fixture" if fixture_dir is not None else "public-source"),
            "created_at": datetime.now(UTC).isoformat(),
            "sources": [],
        }
        try:
            all_candles: list[MarketCandle] = []
            for source in sources:
                raw = (
                    stage
                    / "raw"
                    / "source=binance"
                    / f"symbol={source.symbol}"
                    / (f"date={source.day.isoformat()}")
                )
                raw.mkdir(parents=True)
                target = raw / source.name
                if fixture_dir is None:
                    download_sample(target, url=source.url, max_bytes=ARCHIVE_LIMIT)
                else:
                    for suffix in ("", ".CHECKSUM"):
                        shutil.copyfile(
                            fixture_dir / (source.name + suffix), raw / (source.name + suffix)
                        )
                candles, duplicates = read_archive(target, source, run_id)
                if fixture_dir is None and len(candles) != 1440:
                    raise BatchError("public-source day must contain all 1440 unique minutes")
                all_candles.extend(candles)
                report["sources"].append(
                    {
                        **asdict(source),
                        "day": source.day.isoformat(),
                        "url": source.url,
                        "timestamp_unit": source.unit,
                        "sha256": sha256_file(target),
                        "bytes": target.stat().st_size,
                        "accepted": len(candles),
                        "duplicates": duplicates,
                        "expected_minutes": 1440,
                    }
                )
            database = stage / "warehouse.duckdb"
            if previous:
                shutil.copyfile(previous / "warehouse.duckdb", database)
            load_bounded_candles(all_candles, database)
            build_analytics(database, stage / "parquet")
            with duckdb.connect(str(database), read_only=True) as connection:
                count, distinct = connection.execute("""
                    SELECT COUNT(*), COUNT(DISTINCT (symbol, interval, open_time))
                    FROM marketpulse_data.typed_candles
                """).fetchone()
                parquet_count = connection.execute(
                    "SELECT COUNT(*) FROM read_parquet(?, hive_partitioning=true)",
                    [str(stage / "parquet" / "**" / "*.parquet")],
                ).fetchone()[0]
            if count != distinct or count != parquet_count:
                raise BatchError("warehouse/Parquet key counts do not reconcile")
            report.update(
                status="published",
                stored_rows=count,
                distinct_keys=distinct,
                parquet_rows=parquet_count,
                rejected=0,
            )
            (stage / "report.json").write_text(json.dumps(report, indent=2) + "\n")
            candidate = root / f".{run_id}.pointer"
            candidate.write_text(json.dumps({"run_id": run_id}) + "\n")
            candidate.replace(root / "current.json")  # sole publication point
            return report
        except Exception as exc:
            report.update(status="rejected", error_type=type(exc).__name__, reason=str(exc))
            (stage / "rejected.json").write_text(json.dumps(report, indent=2) + "\n")
            raise


def create_fixture(directory: Path, day: date = date(2024, 1, 1)) -> None:
    """Tiny synthetic archives with duplicate overlap; not exchange observations."""
    directory.mkdir(parents=True, exist_ok=True)
    for source in plan(day):
        start = int(datetime.combine(day, datetime.min.time(), UTC).timestamp())
        multiplier = 1_000_000 if source.unit == "us" else 1000
        rows = []
        for minute in range(3):
            ts = (start + minute * 60) * multiplier
            rows.append(
                [
                    ts,
                    "100.00000001",
                    "103",
                    "99",
                    str(101 + minute),
                    "2.5",
                    ts + 60 * multiplier - 1,
                    "250",
                    10,
                    "1",
                    "100",
                    "0",
                ]
            )
        rows.append(rows[-1])
        target = directory / source.name
        with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
            import io

            text = io.StringIO(newline="")
            csv.writer(text, lineterminator="\n").writerows(rows)
            archive.writestr(source.name[:-4] + ".csv", text.getvalue())
        target.with_name(target.name + ".CHECKSUM").write_text(
            f"{sha256_file(target)}  {target.name}\n"
        )
