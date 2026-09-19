# Local incremental loading with dlt

dlt is a Python loading library. In this project it is a small, local bridge
between trusted MarketCandle records and a queryable DuckDB table. It does not
replace the raw ZIP, checksum verification, or Day 10 ingestion manifest.

The first run writes validated candle records to an ignored DuckDB database:

    trusted MarketCandle records
      -> dlt resource with an open_time cursor
      -> merge using (symbol, interval, open_time)
      -> data/dlt/marketpulse.duckdb

An incremental cursor is the last open_time dlt saved after a successful load.
On the next run, rows older than that value are skipped. The candle business key
is configured as the merge key as additional protection when the cursor boundary
overlaps a previously seen row.

## Run it

    uv run marketpulse load-sample --limit 5

The command first uses the existing trusted sample flow: it downloads or
revalidates the raw Binance archive, validates its candles, and then loads those
candles into the local DuckDB destination. Both the database and dlt working
state live under ignored data paths and are never committed.

To keep an experiment separate, provide explicit locations:

    uv run marketpulse load-sample --output-dir data/raw-experiment --destination data/dlt-experiment/candles.duckdb --limit 1

## What the code guarantees today

- incremental_candles converts only trusted MarketCandle objects to JSON-safe
  records.
- open_time is dlt persistent cursor.
- (symbol, interval, open_time) is the primary business key used for merge.
- The destination database name and dataset name intentionally differ. DuckDB
  treats a same-named database catalog and schema as ambiguous.
- Focused tests cover the first load, an overlap plus one new candle, an empty
  rerun, and the CLI handoff.

## Current boundary

This is a deliberately small local example. It proves incremental state and
merge semantics before Day 13 introduces interactive DuckDB analysis. It is not
the historical Spark backfill or a multi-worker coordinator. The raw ZIP and
manifest remain the provenance and recovery layers; dlt is the incremental
loading layer.

## Interview-sized explanation

"I used dlt for a narrow incremental loading boundary. A cursor on candle
open_time avoids resubmitting old records after a successful run, and the candle
business key is configured for merge so boundary overlap does not create a
second logical candle. I kept raw source storage and the ingestion manifest
separate because they answer different questions: source provenance and
recovery versus incremental warehouse loading."
