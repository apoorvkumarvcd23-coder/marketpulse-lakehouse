"""Tests for read-only aggregates over the Day 12 dlt destination."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from marketpulse.analysis import DuckDbAnalysisError, summarize_candles
from marketpulse.contracts import MarketCandle, MarketSymbol
from marketpulse.ingestion import load_incremental_candles


def _candle(minute: int, *, volume: str = "2.50") -> MarketCandle:
    open_time = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(minutes=minute)
    return MarketCandle.model_validate(
        {
            "symbol": "BTCUSDT",
            "interval": "1m",
            "open_time": open_time,
            "close_time": open_time + timedelta(seconds=59, milliseconds=999),
            "open": "100.00",
            "high": str(101 + minute),
            "low": str(99 - minute),
            "close": "100.50",
            "volume": volume,
            "quote_volume": "250.00",
            "trade_count": 2,
            "source_file": "BTCUSDT-1m-2024-01-01.csv",
            "checksum": "a" * 64,
            "ingestion_time": datetime(2026, 10, 7, tzinfo=UTC),
            "run_id": UUID("f7ec9eae-7d31-4171-b039-0269c8d1c6e4"),
        }
    )


def test_summary_reads_only_the_requested_utc_window(tmp_path: Path) -> None:
    destination = tmp_path / "marketpulse.duckdb"
    load_incremental_candles(
        [_candle(0, volume="1.25"), _candle(1, volume="2.50"), _candle(2, volume="3.75")],
        destination_path=destination,
    )

    summary = summarize_candles(
        symbol=MarketSymbol.BTC_USDT,
        start=datetime(2024, 1, 1, 0, 1, tzinfo=UTC),
        end=datetime(2024, 1, 1, 0, 3, tzinfo=UTC),
        destination_path=destination,
    )

    assert summary.candle_count == 2
    assert summary.first_open_time == datetime(2024, 1, 1, 0, 1, tzinfo=UTC)
    assert summary.last_open_time == datetime(2024, 1, 1, 0, 2, tzinfo=UTC)
    assert str(summary.lowest_price) == "97.00000000"
    assert str(summary.highest_price) == "103.00000000"
    assert str(summary.total_volume) == "6.25000000"


def test_summary_reports_an_empty_window_without_mutating_data(tmp_path: Path) -> None:
    destination = tmp_path / "marketpulse.duckdb"
    load_incremental_candles([_candle(0)], destination_path=destination)

    summary = summarize_candles(
        symbol=MarketSymbol.BTC_USDT,
        start=datetime(2024, 2, 1, tzinfo=UTC),
        destination_path=destination,
    )

    assert summary.candle_count == 0
    assert summary.first_open_time is None
    assert summary.lowest_price is None
    assert str(summary.total_volume) == "0E-8"


def test_summary_requires_an_existing_local_database(tmp_path: Path) -> None:
    with pytest.raises(DuckDbAnalysisError, match="run load-sample first"):
        summarize_candles(
            symbol=MarketSymbol.BTC_USDT,
            destination_path=tmp_path / "missing.duckdb",
        )


def test_summary_rejects_a_reversed_time_window(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="start must be earlier"):
        summarize_candles(
            symbol=MarketSymbol.BTC_USDT,
            start=datetime(2024, 1, 2, tzinfo=UTC),
            end=datetime(2024, 1, 1, tzinfo=UTC),
            destination_path=tmp_path / "unused.duckdb",
        )
