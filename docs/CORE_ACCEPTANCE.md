# Core acceptance — 17 November 2026

This audit covers the bounded **v0.1.0 core**, with extensions and full v1.0.0
hardening continuing through December. The clean checkout audited here is
`0767dee482e11088e305b5daf96b17f0c09d6c1a`. The release tag is created only after the reviewed acceptance
commit also passes its complete clean-checkout CI. Exact immutable tag/commit/CI
links are recorded in the [portfolio release ledger](https://github.com/apoorvkumarvcd23-coder/apoorvkumarvcd23-coder/blob/main/docs/CORE_RELEASES_2026-11-18.md).
Native audit observations are dated 17 November; publication and release checks
carried forward to 18 November. Commit and tag timestamps use their actual time.
No version tag substitutes for the checks.

## Architecture and contract ledger

Bounded BTC/ETH/SOL archive plan → checksum/UTC/decimal validation → dlt/DuckDB business-key merge → immutable Parquet/SQL snapshot → read-only Streamlit.

| Core contract | Implementation | Actual verification |
| --- | --- | --- |
| Bounded one-day three-symbol source and verified archives | src/marketpulse/batch.py plan/read_archive; ingestion/checksum.py | Dry-run byte/file bounds; fresh native public 2025-01-01 run/replay; no exchange credentials |
| Explicit millisecond/microsecond and decimal contracts | batch.source_time; contracts/market_candle.py | Both actual offline units produce 9 exact candles; precision/date/OHLC and checksum rejection tests |
| Trusted immutable outputs and idempotent DuckDB/Parquet | batch.run_batch/current_snapshot; load_bounded_candles | Fresh public run/replay each 4,320 unique keys/1440 per symbol; earlier-other-symbol correction regression |
| Daily SQL and read-only browser | batch.build_analytics; dashboard.py | Actual Streamlit/Chromium empty/invalid/filter/partial/public views; table/chart and snapshot bytes verified |
| Failure/replay reconciliation and clean install | scripts/demo_batch.py; uv.lock; .gitattributes | 162 tests; checksum and checksum-valid bad OHLC preserve pointer/all trusted bytes; LF checkout policy fixes Windows formatter setup |

See the [detailed claim-to-code/test ledger](CLAIM_EVIDENCE.md) and
[full workflow/runbook](CLEAN_INTEGRATION.md). The [machine-readable audit](core-acceptance-2026-11-17.json)
records native observations and hashes of the existing public evidence, retaining
their platform/model distinction. The [previous verified CI](https://github.com/apoorvkumarvcd23-coder/marketpulse-lakehouse/actions/runs/43633979920)
is source-grounded evidence; fresh release-head CI must pass before tagging.

[Actual native acceptance screenshot](evidence/2026-11-17/core-acceptance.png)

## Reproduce from a clean clone

Install the prerequisites in README and follow the full runbook before these
commands. Use a new ignored artifact directory and synthetic/public data only.
Keep generated account/config files private. All service demos use disposable
owned local services; no paid service or external account is required.

```sh
uv sync --locked
uv run python -m playwright install chromium
uv run python scripts/demo_batch.py --artifacts artifacts/core-offline
uv run python scripts/demo_batch.py --artifacts artifacts/core-public --public-date 2025-01-01
```

The native audit used actual installed dependencies and fresh disposable data.
Its platform is recorded explicitly; native fallback does not prove a different
database/service backend. Linux CI executes the documented real-service path.

## Defensible project wording

These are permitted implementation claims for this core, not a personal resume
file or a claim of customer/employer use:

- Built checksum-verified public market-data ingestion with typed UTC/decimal validation, durable manifests and bounded retries.
- Validated a 4,320-record three-symbol day and replay, reconciled DuckDB/Parquet counts and exposed read-only symbol/day SQL summaries in Streamlit.

## Remaining scope and limits

- One bounded historical day for three symbols; not a two-year/cloud/live-streaming deployment.
- dbt, month-scale budgets, broader quarantine/recovery/retention and December release gates remain open.
- No investment-performance, price-forecast or throughput claims.
