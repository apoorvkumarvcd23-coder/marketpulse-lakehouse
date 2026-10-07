"""Bounded, read-only summaries over the local DuckDB candle table."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import duckdb

from marketpulse.contracts import CandleInterval, MarketSymbol
from marketpulse.ingestion import DEFAULT_DLT_DESTINATION, DLT_DATASET_NAME, DLT_TABLE_NAME


class DuckDbAnalysisError(RuntimeError):
    """Raised when a local analytical query cannot safely run."""


@dataclass(frozen=True)
class CandleSummary:
    """A compact, interview-friendly aggregate for one symbol and interval."""

    symbol: MarketSymbol
    interval: CandleInterval
    candle_count: int
    first_open_time: datetime | None
    last_open_time: datetime | None
    lowest_price: Decimal | None
    highest_price: Decimal | None
    total_volume: Decimal


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise DuckDbAnalysisError("database returned a timestamp without a timezone")
    return value.astimezone(UTC)


def _validate_window(start: datetime | None, end: datetime | None) -> None:
    if start is not None and (start.tzinfo is None or start.utcoffset() is None):
        raise ValueError("start must include a timezone")
    if end is not None and (end.tzinfo is None or end.utcoffset() is None):
        raise ValueError("end must include a timezone")
    if start is not None and end is not None and start >= end:
        raise ValueError("start must be earlier than end")


def summarize_candles(
    *,
    symbol: MarketSymbol,
    interval: CandleInterval = CandleInterval.ONE_MINUTE,
    start: datetime | None = None,
    end: datetime | None = None,
    destination_path: Path = DEFAULT_DLT_DESTINATION,
) -> CandleSummary:
    """Return a parameterized aggregate without modifying the local database."""
    _validate_window(start, end)
    if not destination_path.is_file():
        raise DuckDbAnalysisError(
            f"local DuckDB database was not found at {destination_path}; run load-sample first"
        )

    conditions = ["symbol = ?", "interval = ?"]
    parameters: list[object] = [symbol.value, interval.value]
    if start is not None:
        conditions.append("open_time >= ?")
        parameters.append(start.astimezone(UTC))
    if end is not None:
        conditions.append("open_time < ?")
        parameters.append(end.astimezone(UTC))
    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT
            COUNT(*) AS candle_count,
            MIN(open_time) AS first_open_time,
            MAX(open_time) AS last_open_time,
            MIN(CAST(low AS DECIMAL(38, 8))) AS lowest_price,
            MAX(CAST(high AS DECIMAL(38, 8))) AS highest_price,
            COALESCE(SUM(CAST(volume AS DECIMAL(38, 8))), 0) AS total_volume
        FROM {DLT_DATASET_NAME}.{DLT_TABLE_NAME}
        WHERE {where_clause}
    """

    try:
        connection = duckdb.connect(str(destination_path), read_only=True)
        try:
            row = connection.execute(query, parameters).fetchone()
        finally:
            connection.close()
    except duckdb.Error as exc:
        raise DuckDbAnalysisError(
            "could not read the trusted candle table; run load-sample to create it"
        ) from exc

    assert row is not None
    return CandleSummary(
        symbol=symbol,
        interval=interval,
        candle_count=int(row[0]),
        first_open_time=_utc(row[1]),
        last_open_time=_utc(row[2]),
        lowest_price=Decimal(str(row[3])) if row[3] is not None else None,
        highest_price=Decimal(str(row[4])) if row[4] is not None else None,
        total_volume=Decimal(str(row[5])),
    )
