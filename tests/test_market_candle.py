"""Contract tests for trusted historical market candles."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from marketpulse.contracts import CandleInterval, MarketCandle, MarketSymbol

OPEN_TIME = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
CLOSE_TIME = OPEN_TIME + timedelta(minutes=1) - timedelta(microseconds=1)
INGESTION_TIME = OPEN_TIME + timedelta(minutes=5)
RUN_ID = UUID("a17fbab3-47fb-4a5e-bf77-6be80a61e537")


def valid_candle_data(**overrides: Any) -> dict[str, Any]:
    """Return a complete valid record with optional test-specific changes."""
    data: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "interval": "1m",
        "open_time": OPEN_TIME,
        "close_time": CLOSE_TIME,
        "open": "67234.12000000",
        "high": "67280.00000000",
        "low": "67200.50000000",
        "close": "67260.33000000",
        "volume": "12.34560000",
        "quote_volume": "830123.45678900",
        "trade_count": 418,
        "source_file": "BTCUSDT-1m-2026-08.csv",
        "checksum": "a" * 64,
        "ingestion_time": INGESTION_TIME,
        "run_id": str(RUN_ID),
    }
    data.update(overrides)
    return data


def test_valid_candle_exposes_stable_business_key() -> None:
    """The natural key must match the deduplication rule in the project plan."""
    candle = MarketCandle.model_validate(valid_candle_data())

    assert candle.symbol is MarketSymbol.BTC_USDT
    assert candle.interval is CandleInterval.ONE_MINUTE
    assert candle.business_key == (MarketSymbol.BTC_USDT, CandleInterval.ONE_MINUTE, OPEN_TIME)


def test_decimal_text_preserves_market_precision() -> None:
    """Decimal text should not be converted through a binary floating-point value."""
    candle = MarketCandle.model_validate(valid_candle_data())

    assert candle.open == Decimal("67234.12000000")
    assert str(candle.open) == "67234.12000000"
    assert str(candle.quote_volume) == "830123.45678900"


@pytest.mark.parametrize("field", ["open", "high", "low", "close", "volume", "quote_volume"])
def test_binary_float_inputs_are_rejected(field: str) -> None:
    """A float must not silently reduce source precision."""
    with pytest.raises(ValidationError, match="decimal fields must be supplied"):
        MarketCandle.model_validate(valid_candle_data(**{field: 1.1}))


def test_json_serialization_keeps_decimals_as_strings_and_times_in_utc() -> None:
    """JSON-safe records should preserve decimal text and explicit UTC timestamps."""
    payload = MarketCandle.model_validate(valid_candle_data()).model_dump(mode="json")

    assert payload["open"] == "67234.12000000"
    assert payload["volume"] == "12.34560000"
    assert payload["open_time"] == "2026-08-08T12:00:00Z"
    assert payload["run_id"] == str(RUN_ID)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"high": "67220"}, "high must be at least"),
        ({"low": "67250"}, "low must be at most"),
        ({"high": "67190", "low": "67200"}, "high cannot be lower"),
        ({"close_time": OPEN_TIME}, "close_time must be later"),
        ({"ingestion_time": OPEN_TIME}, "ingestion_time cannot be earlier"),
    ],
)
def test_cross_field_invariants_are_enforced(overrides: dict[str, Any], message: str) -> None:
    """Impossible price or time relationships must be rejected."""
    with pytest.raises(ValidationError, match=message):
        MarketCandle.model_validate(valid_candle_data(**overrides))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("open", "0"),
        ("high", "-1"),
        ("volume", "-0.0001"),
        ("quote_volume", "-1"),
        ("trade_count", -1),
    ],
)
def test_price_volume_and_count_ranges_are_enforced(field: str, value: Any) -> None:
    """Prices must be positive; volumes and counts cannot be negative."""
    with pytest.raises(ValidationError, match=field):
        MarketCandle.model_validate(valid_candle_data(**{field: value}))


@pytest.mark.parametrize("field", ["open_time", "close_time", "ingestion_time"])
def test_timezone_naive_timestamps_are_rejected(field: str) -> None:
    """A timestamp without an offset is ambiguous and cannot enter trusted data."""
    naive = datetime(2026, 8, 8, 12, 0)

    with pytest.raises(ValidationError, match="timestamps must include timezone"):
        MarketCandle.model_validate(valid_candle_data(**{field: naive}))


@pytest.mark.parametrize("field", ["open_time", "close_time", "ingestion_time"])
def test_numeric_timestamps_must_be_normalized_first(field: str) -> None:
    """The contract must not guess whether source integers use milliseconds or microseconds."""
    with pytest.raises(ValidationError, match="numeric timestamps must be normalized"):
        MarketCandle.model_validate(valid_candle_data(**{field: 1_754_651_200_000}))


def test_offset_aware_timestamps_are_normalized_to_utc() -> None:
    """Equivalent aware timestamps should produce the same UTC business key."""
    india = timezone(timedelta(hours=5, minutes=30))
    local_open = OPEN_TIME.astimezone(india)
    local_close = CLOSE_TIME.astimezone(india)
    local_ingestion = INGESTION_TIME.astimezone(india)

    candle = MarketCandle.model_validate(
        valid_candle_data(
            open_time=local_open,
            close_time=local_close,
            ingestion_time=local_ingestion,
        )
    )

    assert candle.open_time == OPEN_TIME
    assert candle.open_time.tzinfo is UTC
    assert candle.business_key[2] == OPEN_TIME


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("symbol", "DOGEUSDT"),
        ("interval", "5m"),
        ("checksum", "not-a-sha256"),
        ("source_file", "   "),
        ("run_id", "not-a-uuid"),
    ],
)
def test_identity_and_provenance_fields_are_strict(field: str, value: Any) -> None:
    """Unexpected scope or unverifiable provenance must fail validation."""
    with pytest.raises(ValidationError, match=field):
        MarketCandle.model_validate(valid_candle_data(**{field: value}))


def test_unknown_fields_are_rejected_and_records_are_immutable() -> None:
    """Silent schema drift and mutation would make downstream behavior unpredictable."""
    with pytest.raises(ValidationError, match="extra_forbidden"):
        MarketCandle.model_validate(valid_candle_data(unexpected="value"))

    candle = MarketCandle.model_validate(valid_candle_data())
    with pytest.raises(ValidationError, match="frozen_instance"):
        candle.close = Decimal("1")


def test_json_schema_documents_every_contract_field() -> None:
    """The contract should be inspectable by people and future tooling."""
    schema = MarketCandle.model_json_schema()
    required = set(schema["required"])

    assert required == {
        "symbol",
        "interval",
        "open_time",
        "close_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "trade_count",
        "source_file",
        "checksum",
        "ingestion_time",
        "run_id",
    }
    assert schema["additionalProperties"] is False
    assert schema["properties"]["checksum"]["description"].startswith("Verified SHA-256")
