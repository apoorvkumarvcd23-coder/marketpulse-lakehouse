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
and officially verified archive SHA-256 fingerprint, the UTC ingestion time,
and one run ID shared by the parsed rows. Decimal text goes directly into the
contract; it is never converted through binary floating point.

## Safety boundaries

`uv run marketpulse fetch-sample --limit 5`:

1. downloads the exact `.CHECKSUM` record and ZIP as private candidate files;
2. makes at most three HTTPS attempts per resource, each with a 30-second timeout;
3. retries only temporary transport or HTTP failures with 0.5 then 1.0 seconds
   of exponential backoff;
4. bounds checksum text to 1 KiB and ZIP bytes to 5 MiB;
5. accepts one ASCII checksum record containing 64 hexadecimal characters and
   the exact source ZIP name;
6. calculates SHA-256 locally and stops before publication or parsing on mismatch;
7. publishes the verified pair, then verifies cached bytes again on every run;
8. accepts exactly the expected CSV member and never extracts the ZIP;
9. refuses a CSV member larger than 10 MiB;
10. reads at most 100 rows and validates each selected row as a `MarketCandle`.

Generated archives and checksum files live under `data/`, which Git ignores.
Timeout, retry classification, and capped exponential backoff are defined in
the [HTTP reliability policy](http-reliability.md). Exact source identity,
digest comparison, cache re-verification, and integrity failure behavior are
defined in the [checksum verification policy](checksum-verification.md).
