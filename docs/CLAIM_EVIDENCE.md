# Implemented claims and remaining gates

| Claim | Code | Verification |
| --- | --- | --- |
| Bounded three-symbol daily plan | `batch.plan`, `Source`, CLI `batch-day --dry-run` | Unsafe/duplicate symbols, current date and explicit byte/file budget tests |
| Checksum-bound exact archives, explicit ms/us and decimal/UTC validation | `batch.read_archive`, `source_time`, existing checksum/HTTP/contract modules | Both date-unit fixtures; checksum, date, precision, OHLC and duplicate rejection |
| Idempotent bounded backfill without global-cursor skipping | `load_bounded_candles` | Later BTC then earlier ETH and corrected older key; two complete replay runs |
| Trusted snapshot survives a failed update | `writer_lock`, `run_batch`, `current_snapshot` | Cross-process lock; failed checksum/rows/export preserve pointer and previous DB hash |
| DuckDB and partitioned Parquet counts reconcile | `build_analytics`, `run_batch` | Real fixture round trip, reference OHLC/volume, old snapshot reads; public 4,320-key run/replay |
| Read-only symbol/day view and historical/partial/error states | `dashboard.py` | Streamlit AppTest filters, empty/corrupt pointer; actual browser screenshot |

Recorded public-source evidence is `public-run-2026-11-11.json`, with exact URLs,
SHA-256 values, bytes and accepted/replay counts. Synthetic fixture data is
explicitly labelled and is not exchange data. No throughput or business gain
is claimed. The existing 145 checks plus 17 batch/dashboard checks pass locally.

Still required: clean-clone final demo/acceptance, dbt, one-month budgets, broad
quarantine/recovery/retention and full December release gates. Cloud/live streaming
and AI forecasting are unimplemented. No v0.1.0 or v1.0.0 tag is earned here.
