"""Trusted representation of one complete Binance market candle."""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

PositiveDecimal = Annotated[Decimal, Field(gt=Decimal("0"), allow_inf_nan=False)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=Decimal("0"), allow_inf_nan=False)]
Sha256Checksum = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
SourceFile = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class MarketSymbol(StrEnum):
    """Trading pairs included in the MarketPulse project."""

    BTC_USDT = "BTCUSDT"
    ETH_USDT = "ETHUSDT"
    SOL_USDT = "SOLUSDT"


class CandleInterval(StrEnum):
    """Candle durations accepted by the first historical contract."""

    ONE_MINUTE = "1m"


class MarketCandle(BaseModel):
    """One immutable, validated, complete one-minute market candle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    _decimal_fields: ClassVar[tuple[str, ...]] = (
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
    )
    _timestamp_fields: ClassVar[tuple[str, ...]] = (
        "open_time",
        "close_time",
        "ingestion_time",
    )

    symbol: MarketSymbol = Field(description="Binance spot trading pair.")
    interval: CandleInterval = Field(description="Duration represented by this candle.")
    open_time: datetime = Field(description="Inclusive candle start normalized to UTC.")
    close_time: datetime = Field(description="Inclusive candle end normalized to UTC.")
    open: PositiveDecimal = Field(description="First traded price during the interval.")
    high: PositiveDecimal = Field(description="Highest traded price during the interval.")
    low: PositiveDecimal = Field(description="Lowest traded price during the interval.")
    close: PositiveDecimal = Field(description="Last traded price during the interval.")
    volume: NonNegativeDecimal = Field(description="Base-asset volume traded.")
    quote_volume: NonNegativeDecimal = Field(description="Quote-asset volume traded.")
    trade_count: int = Field(ge=0, description="Number of trades in the interval.")
    source_file: SourceFile = Field(description="Raw Binance archive member that supplied the row.")
    checksum: Sha256Checksum = Field(description="Verified SHA-256 checksum of the source archive.")
    ingestion_time: datetime = Field(description="UTC time at which MarketPulse accepted the row.")
    run_id: UUID = Field(description="Pipeline run that produced this trusted record.")

    @field_validator(*_decimal_fields, mode="before")
    @classmethod
    def reject_binary_floats(cls, value: Any) -> Any:
        """Require decimal text or Decimal objects so binary rounding cannot enter silently."""
        if isinstance(value, (bool, float)):
            raise ValueError(
                "decimal fields must be supplied as strings, integers, or Decimal values"
            )
        return value

    @field_validator(*_timestamp_fields, mode="before")
    @classmethod
    def reject_numeric_timestamps(cls, value: Any) -> Any:
        """Force millisecond or microsecond source values through an explicit normalizer."""
        if isinstance(value, (bool, int, float)):
            raise ValueError("numeric timestamps must be normalized before contract validation")
        return value

    @field_validator(*_timestamp_fields)
    @classmethod
    def normalize_aware_datetime_to_utc(cls, value: datetime) -> datetime:
        """Reject timezone-naive values and normalize aware timestamps to UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must include timezone information")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_candle_relationships(self) -> Self:
        """Enforce rules involving more than one field."""
        if self.close_time <= self.open_time:
            raise ValueError("close_time must be later than open_time")
        if self.ingestion_time < self.close_time:
            raise ValueError("ingestion_time cannot be earlier than close_time")
        if self.high < self.low:
            raise ValueError("high cannot be lower than low")
        if self.high < max(self.open, self.close):
            raise ValueError("high must be at least the open and close prices")
        if self.low > min(self.open, self.close):
            raise ValueError("low must be at most the open and close prices")
        return self

    @property
    def business_key(self) -> tuple[MarketSymbol, CandleInterval, datetime]:
        """Return the natural key used to identify one candle across reruns."""
        return (self.symbol, self.interval, self.open_time)


__all__ = ["CandleInterval", "MarketCandle", "MarketSymbol"]
