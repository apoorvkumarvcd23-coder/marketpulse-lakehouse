# BTCUSDT learning sample

Day 6 connects the first trusted data contract to a real public source without
attempting a production backfill.

## Fixed source

- Provider: Binance public market-data archive
- Dataset: spot klines (candles)
- Symbol: `BTCUSDT`
- Interval: `1m`
- Date: `2024-01-01`
- Archive: `BTCUSDT-1m-2024-01-01.zip`
- CSV member: `BTCUSDT-1m-2024-01-01.csv`

Binance documents the public daily/monthly archive layout and the 12 kline
columns in its [public-data repository](https://github.com/binance/binance-public-data).
A pre-2025 file is intentional: Binance states that spot archive timestamps
change to microseconds from 2025-01-01, while this first parser explicitly
accepts milliseconds. Safe mixed-unit normalization is scheduled for Day 17.

## Source-to-contract mapping

| CSV position | Source meaning | `MarketCandle` field |
| ---: | --- | --- |
| 0 | Open time in Unix milliseconds | `open_time` |
| 1 | Open price | `open` |
| 2 | High price | `high` |
| 3 | Low price | `low` |
| 4 | Close price | `close` |
| 5 | Base-asset volume | `volume` |
| 6 | Close time in Unix milliseconds | `close_time` |
| 7 | Quote-asset volume | `quote_volume` |
| 8 | Number of trades | `trade_count` |
| 9–11 | Taker volumes and unused field | Not needed by the current contract |

The parser adds `symbol`, `interval`, `source_file`, a locally calculated
archive SHA-256 fingerprint, the UTC ingestion time, and one run ID shared by
the parsed rows. Decimal text goes directly into the contract; it is never
converted through binary floating point.

## Safety boundaries

`uv run marketpulse fetch-sample --limit 5`:

1. makes at most three HTTPS attempts, each with a 30-second timeout;
2. retries only temporary transport or HTTP failures with 0.5 then 1.0 seconds
   of exponential backoff;
3. refuses a response larger than 5 MiB;
4. writes each attempt to a `.part` file and renames it only after completion;
5. accepts exactly the expected CSV member and never extracts the ZIP;
6. refuses a CSV member larger than 10 MiB;
7. reads at most 100 rows and validates each selected row as a `MarketCandle`.

Generated archives live under `data/`, which Git ignores. This day calculates
a useful local SHA-256 fingerprint but does **not** yet compare it with the
provider's `.CHECKSUM` file. Timeout, retry classification, and capped
exponential backoff are defined in the [HTTP reliability policy](http-reliability.md).
Official checksum verification is Day 9, so the command does not pretend source
integrity comparison already exists.
