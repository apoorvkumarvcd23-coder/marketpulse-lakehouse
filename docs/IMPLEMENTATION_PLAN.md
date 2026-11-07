# MarketPulse Lakehouse — December 2026 implementation plan

## Immediate core milestone — 17 November 2026

The core is needed for resume demonstrations within the next ten days. On
10 November build a bounded one-day BTC/ETH/SOL source-to-Parquet/DuckDB path,
UTC/decimal validation, checksum/recovery boundaries, per-symbol idempotency,
SQL summaries and a minimal read-only dashboard. Use a small offline fixture
and record one real public-source run. Verify the clean integration demo on
15 November and final core acceptance on 17 November. dbt, one-month backfills,
richer analytics and full v1 recovery/measurement work follow through December.
The fixed five-row sample alone is not the finished core target.

## Source-grounded starting point

Reviewed main `d8c0e5fe18fd879e9cab015b129f29854b0386a4`: README/90-day roadmap,
Python package/lock configuration, CLI, validated candle contract, HTTP/checksum
download path, manifests, raw layout, dlt loader, DuckDB summaries and tests.
The implemented source is a fixed BTCUSDT 2024-01-01 sample, bounded to at most
100 parsed rows. Timestamp conversion explicitly accepts milliseconds only.
There are tests for contracts, HTTP failure handling, manifests, raw paths,
incremental loading, summaries, secret exclusions and idempotent reruns.

BigQuery, GCS, Terraform, Spark processing, dbt, live Redpanda/PyFlink ingestion
and a dashboard are roadmap items, not delivered code at this revision. The
historical calendar ending in early November is stale. Replace its current-
delivery section while retaining the earlier milestones as history.

## Bounded December v1

Finish a **local batch analytics lakehouse**: configurable BTC/ETH/SOL one-minute
archives for a bounded requested date range -> checksum verification -> typed
normalisation/quarantine -> raw and Parquet partitions -> dlt/DuckDB -> dbt
analytics -> read-only Streamlit dashboard. Keep Python 3.12, uv.lock and the
existing contract/recovery code. Do not add a second orchestration platform.

Default acceptance backfill is one historical month for three symbols, bounded
by an explicit download byte/file budget. Offline miniature archives provide
repeatable CI without live downloads. Two-year history and cloud/live streaming
remain future phases; they are not prerequisites for this finite local v1.

## Interfaces and data rules

Extend the CLI with a validated date/symbol planner and dry-run manifest, then
bounded backfill, validate/export, build-analytics and dashboard instructions.
Reject arbitrary source hosts, unsafe paths, unbounded ranges and invalid pairs.
Public exchange archives require no trading credentials.

Retain source provenance and decimal precision. Add explicit millisecond and
microsecond normalisation with fixtures at source-format boundaries. Quarantine
invalid rows with reason/count and source reference; checksum-invalid bytes never
enter the trusted table. Preserve the previous trusted output on a failed update.

Use business key `(symbol, interval, open_time)`. Current `dlt_candles.py` has one
pipeline/cursor: adding symbols or older backfills without a policy risks skipped
records. Add regression tests first, then isolate state per source partition or
implement a bounded overlap/backfill mode with documented merge semantics.

Parquet partitions carry symbol/date and deterministic deduplication. Write
bounded batches rather than materialising an entire multi-month corpus. Include
schema, rejected/accepted/duplicate counts and a run ID. Protect per-partition
manifest writes from concurrent writers; atomic file replacement alone is not a
multi-writer transaction.

Build dbt sources/staging and daily marts for OHLC, volume, returns, volatility
and freshness/completeness. Tests cover uniqueness, nulls, accepted symbols,
OHLC relationships and a reference fixture's expected aggregates. Dashboard
filters symbol/time and shows freshness, empty/stale/error states; all access is
read-only. Do not add investment recommendations or an untested AI price forecast.

## Task sequence and acceptance

| ID | Work unit | Observable acceptance |
| --- | --- | --- |
| M01 | Baseline CI and revised delivery status | Locked install, ruff, doctor and existing tests pass; current/future scope separated |
| M02 | Configurable source/date dry-run planner | Valid bounded plans for three symbols; unsafe/oversized inputs fail before download |
| M03 | Millisecond/microsecond normalisation | Both explicit units map to identical UTC candles; ambiguous/invalid values fail |
| M04 | Trusted processing and quarantine | Bad checksum publishes nothing; malformed rows are counted/quarantined with provenance |
| M05 | Partitioned Parquet and deduplication | Small fixture yields expected schema/partitions/unique keys within memory limits |
| M06 | Cursor/backfill state isolation | Loading later BTC then earlier ETH does not skip valid ETH; overlap reruns stay idempotent |
| M07 | dbt DuckDB staging and marts | Build/test/docs pass with reference returns, volume and completeness counts |
| M08 | Read-only Streamlit dashboard | Filters, charts and empty/stale/error states work against fixture and loaded data |
| M09 | Bounded one-month/three-symbol run | Dry-run budget approved by configured limits; actual bytes/files/rows recorded |
| M10 | Recovery and concurrency drill | Interrupted/parallel ingestion resumes safely; trusted outputs and counts reconcile |
| M11 | Release and handover | Clean clone reproduces fixture pipeline/dashboard; CI and acceptance report pass |

## Verification and release

Preserve the existing `uv sync --locked`, ruff and pytest workflow. Add a real
DuckDB/dbt integration job and a small offline source-to-dashboard smoke case.
Network ingestion is a separately labelled manual integration run, with actual
checksums, date range, download budget and row totals retained as evidence.

`v1.0.0` requires M01–M11, data dictionary/lineage, idempotency/recovery report,
dashboard screenshots and commands to reproduce the same fixture analytics.
Document measured time/memory for the bounded run, not fabricated throughput.
Retain the cloud/streaming roadmap as an optional subsequent phase with separate
cost/authentication and acceptance requirements.
