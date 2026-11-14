# Clean CLI-to-dashboard integration

## Recorded 15 November 2026

The [permanent native and Linux report](clean-integration-2026-11-15.json)
records source `254f504ce6a0bf047b2e32c2220c25af23a0187b` and
[passing clean-checkout CI](https://github.com/apoorvkumarvcd23-coder/marketpulse-lakehouse/actions/runs/43633564831).
All 162 tests, lint/format, doctor and the actual offline CLI/browser walkthrough
pass. Native Windows separately fetched the public archives twice: each run
reconciles 4,320 unique candles, 1,440 per symbol, from 196,942 ZIP bytes. Both
ms/us fixtures leave nine unique candles; both rejected-input drills preserve
the pointer and every trusted snapshot byte. No source/model/HTTP mocks are
used by this walkthrough; deterministic lower-level tests remain separate.

Inspected native screenshots:
[empty](evidence/2026-11-15/empty.png),
[invalid pointer](evidence/2026-11-15/invalid-pointer.png),
[synthetic partial ETH day](evidence/2026-11-15/fixture-eth.png),
[public full ETH day](evidence/2026-11-15/public-eth.png).
The report includes their hashes and the separate Linux offline results.

## Reproduce the walkthrough

Use Python 3.12 and the committed `uv.lock`. The browser verifier is a pinned
development dependency; it does not add a browser requirement to batch ingestion.
All data created by this walkthrough stays under the chosen ignored artifact
directory. Choose a new directory for each run: existing results are never
overwritten. No accounts, trading credentials or paid services are used.

```sh
uv sync --locked
uv run python -m playwright install chromium
uv run python scripts/demo_batch.py --artifacts artifacts/integration-offline
```

The offline command launches actual package CLI processes, dlt/DuckDB/Parquet,
loopback Streamlit servers and Chromium. It runs no mocked browser or API:

- Millisecond (2024-01-01) and microsecond (2025-01-01) fixtures each load nine
  unique candles, three per symbol, with one duplicate per source. Exact decimal
  aggregates, business-key uniqueness and warehouse/Parquet counts are checked.
- Replays preserve the same typed business-content hash and counts. Every file
  of the previous immutable snapshot remains byte-for-byte unchanged.
- A bad checksum and then checksum-valid invalid OHLC input each fail through
  the real CLI. The current pointer and every trusted snapshot file retain
  their hashes. Rejected candidates remain separate and cannot become trusted.
- Chromium verifies empty and invalid-pointer states, symbol selection,
  historical/partial labels and fully rendered table/chart. The view remains
  read-only: opening and filtering it changes no trusted snapshot bytes.

To separately exercise the bounded public downloader, choose a completed day:

```sh
uv run python scripts/demo_batch.py --artifacts artifacts/integration-public --public-date 2025-01-01
```

Public mode fetches checksum-verified BTC/ETH/SOL archives twice through the real
HTTP client, without reading prior runs. Each load must reconcile 4,320 unique
minutes in DuckDB and Parquet, 1,440 per symbol. The public dashboard is separately
labelled, must not show the fixture's partial-day warning, and is checked against
unchanged snapshot hashes. Source URLs, exact archive SHA-256 values/bytes and
both load reports are retained in `integration.json`; screenshots are PNGs beside
it. Generated archives, databases and raw dashboard logs are never public evidence.

The `local-batch` CI job runs the locked tests, doctor and offline CLI/browser
walkthrough on a clean Linux checkout. Public-source execution is explicitly
separate, because live availability should not replace deterministic CI fixtures.
A passing job/report is required before claiming this integration was verified.

These are bounded integration fixtures and one-day observations, not throughput,
investment performance, month-scale backfill, dbt or complete December release
claims. Final four-project acceptance remains 17 November; no release tag is
earned by the walkthrough alone.
