# MarketCandle data contract

`MarketCandle` is the first trusted record in MarketPulse. It represents one
complete one-minute Binance spot candlestick after source parsing and timestamp
normalization, but before storage or warehouse loading.

## Fields

| Field | Type | Rule |
| --- | --- | --- |
| `symbol` | enum | `BTCUSDT`, `ETHUSDT`, or `SOLUSDT` |
| `interval` | enum | `1m` |
| `open_time` | datetime | timezone-aware and normalized to UTC |
| `close_time` | datetime | timezone-aware, UTC, and later than `open_time` |
| `open`, `high`, `low`, `close` | Decimal | positive and internally consistent |
| `volume`, `quote_volume` | Decimal | zero or greater |
| `trade_count` | integer | zero or greater |
| `source_file` | string | non-empty raw archive member name |
| `checksum` | string | 64 lowercase hexadecimal SHA-256 characters |
| `ingestion_time` | datetime | timezone-aware UTC time at or after `close_time` |
| `run_id` | UUID | identifies the pipeline execution |

The uniqueness key is `(symbol, interval, open_time)`. A rerun that encounters
the same key must update or ignore the existing candle rather than insert a
duplicate.

## Precision and time rules

Price and volume values remain `Decimal` values. Binary floating-point inputs
are rejected because they can silently change exact source values. JSON output
serializes decimals as strings.

Numeric timestamps are also rejected by this trusted contract. Binance public
spot archives use microseconds for data from 2025 onward while older files use
milliseconds. The ingestion parser must detect and normalize that unit before
constructing `MarketCandle`.

## Source mapping

Binance kline archives provide open time, OHLC prices, base volume, close time,
quote volume, trade count, taker-buy volumes, and an ignored field. MarketPulse
keeps the analytics fields above and adds source filename, verified archive
checksum, ingestion time, and run ID so every trusted row has provenance.

## Rejection behavior

The contract fails closed on unknown fields, unsupported symbols or intervals,
ambiguous timestamps, invalid checksums, malformed UUIDs, negative measures,
impossible OHLC relationships, or ingestion before candle completion. Invalid
source rows will later be routed to quarantine rather than silently discarded.
