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

CORE09 integration passed at source `254f504ce6a0bf047b2e32c2220c25af23a0187b`:
[clean Linux CI](https://github.com/apoorvkumarvcd23-coder/marketpulse-lakehouse/actions/runs/43633564831),
[native public plus Linux offline evidence](clean-integration-2026-11-15.json)
and [runbook/screenshots](CLEAN_INTEGRATION.md). The real CLI rejects checksum and
typed-row faults without changing the pointer or any trusted snapshot file;
business-content hashes/counts survive replay, and opening/filtering the actual
browser leaves snapshot bytes unchanged. Both ms/us fixtures and all 162 checks
pass; the native public run/replay each contain 4,320 keys.

The [17 November bounded core audit](CORE_ACCEPTANCE.md) records fresh clean-clone
checks and public/offline replay; the acceptance commit needs passing CI before
the v0.1.0 tag. Still required for v1.0.0: dbt, one-month budgets, broad
quarantine/recovery/retention and full December release gates. Cloud/live streaming
and AI forecasting are unimplemented. A core tag does not complete these v1 gates.
