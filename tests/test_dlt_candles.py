"""Tests for the small, local dlt incremental candle pipeline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import duckdb

from marketpulse.contracts import MarketCandle
from marketpulse.ingestion.dlt_candles import (
    DLT_DATASET_NAME,
    DLT_TABLE_NAME,
    load_incremental_candles,
)

RUN_ID = UUID("f7ec9eae-7d31-4171-b039-0269c8d1c6e4")
INGESTION_TIME = datetime(2026, 9, 19, tzinfo=UTC)


def _candle(minute: int, *, close: str = "42266.95000000") -> MarketCandle:
    open_time = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(minutes=minute)
    return MarketCandle.model_validate(
        {
            "symbol": "BTCUSDT",
            "interval": "1m",
            "open_time": open_time,
            "open": "42283.58000000",
            "high": "42288.00000000",
            "low": "42261.02000000",
            "close": close,
            "volume": "13.70612000",
            "close_time": open_time + timedelta(seconds=59, milliseconds=999),
            "quote_volume": "579426.35515540",
            "trade_count": 624,
            "source_file": "BTCUSDT-1m-2024-01-01.csv",
            "checksum": "a" * 64,
            "ingestion_time": INGESTION_TIME,
            "run_id": RUN_ID,
        }
    )


def _stored_rows(destination: Path) -> list[tuple[str, str, str]]:
    connection = duckdb.connect(str(destination), read_only=True)
    try:
        return connection.execute(
            f"""
            SELECT symbol, CAST(open_time AS VARCHAR), close
            FROM {DLT_DATASET_NAME}.{DLT_TABLE_NAME}
            ORDER BY open_time
            """
        ).fetchall()
    finally:
        connection.close()


def test_first_dlt_run_creates_a_local_merged_candle_table(tmp_path: Path) -> None:
    destination = tmp_path / "marketpulse.duckdb"

    result = load_incremental_candles([_candle(0), _candle(1)], destination_path=destination)

    assert result.destination_path == destination
    assert result.submitted_rows == 2
    assert len(result.load_ids) == 1
    assert [(symbol, close) for symbol, _open_time, close in _stored_rows(destination)] == [
        ("BTCUSDT", "42266.95000000"),
        ("BTCUSDT", "42266.95000000"),
    ]


def test_incremental_rerun_keeps_old_keys_and_loads_only_the_newer_candle(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "marketpulse.duckdb"
    load_incremental_candles([_candle(0), _candle(1)], destination_path=destination)

    result = load_incremental_candles(
        [
            _candle(0, close="42267.00000000"),
            _candle(1),
            _candle(2, close="42270.00000000"),
        ],
        destination_path=destination,
    )
    rows = _stored_rows(destination)

    assert result.submitted_rows == 3
    assert len(rows) == 3
    assert [row[2] for row in rows] == [
        "42266.95000000",
        "42266.95000000",
        "42270.00000000",
    ]


def test_empty_incremental_run_is_safe_after_the_cursor_is_saved(tmp_path: Path) -> None:
    destination = tmp_path / "marketpulse.duckdb"
    load_incremental_candles([_candle(0)], destination_path=destination)

    result = load_incremental_candles([], destination_path=destination)

    assert result.submitted_rows == 0
    assert _stored_rows(destination)[0][0] == "BTCUSDT"
