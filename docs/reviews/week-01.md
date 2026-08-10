# Week 1 acceptance review

This checkpoint verifies that MarketPulse has a reproducible foundation and one
narrow, real source-to-contract path before Week 2 introduces retries,
checksums, manifests, and durable raw-data layout.

## Delivered capabilities

| Area | Evidence at the Day 7 checkpoint |
| --- | --- |
| Repository | Public purpose, 90-day roadmap, MIT license, and explicit private-output boundaries |
| Runtime | Python 3.12 only, `uv` lockfile, Ruff formatting/linting, and pytest |
| Local service | Health-checked PostgreSQL 18 container with local-only port binding and persistent volume |
| Configuration | Typed environment loading, required local password, masked diagnostics, and credential ignore rules |
| Data contract | Immutable 15-field `MarketCandle` with Decimal precision, UTC time, OHLC rules, provenance, and business key |
| First ingestion | Bounded fixed BTCUSDT ZIP download, exact CSV-member check, millisecond normalization, and contract mapping |
| Setup diagnosis | Read-only `marketpulse doctor` with five deterministic checks and repair hints |

## Acceptance evidence

Run these commands from a clean project root:

```powershell
uv sync --locked
uv run marketpulse doctor
uv run ruff format --check .
uv run ruff check .
uv run pytest
uv run marketpulse fetch-sample --limit 5
```

The Day 7 verification produced:

- five of five setup-doctor checks passing;
- 78 automated tests passing;
- five real BTCUSDT one-minute candles parsed from 2024-01-01;
- first business key `BTCUSDT | 1m | 2024-01-01T00:00:00+00:00`;
- local archive SHA-256
  `4ec2915e610ab4e9a4d5e86a5ada1c15bbf6b5db343cdb385681d6ac97166a4e`;
- generated data and private `outputs/` remaining ignored and untracked.

The setup doctor is intentionally deterministic and read-only. It checks the
Python version, required root files, project metadata, lockfile identity, and
privacy boundaries. It does not start Docker, call the network, verify cloud
credentials, or claim that later production services exist.

## Parser failure coverage

The sample tests now cover valid mapping and bounded row selection plus:

- millisecond-versus-microsecond mistakes;
- missing, corrupt, empty, oversized, multi-member, and wrongly named archives;
- invalid UTF-8 and incorrect CSV column counts;
- rows that fail the trusted `MarketCandle` contract with row context retained;
- announced and observed download-size violations;
- empty responses and cleanup of incomplete `.part` files.

## Known limits carried into Week 2

- HTTP failures are reported after one attempt; retry and exponential backoff
  are the Day 8 milestone.
- SHA-256 is calculated locally but not compared with Binance's published
  `.CHECKSUM`; that verification is Day 9.
- Download and processing state is not yet recorded in a manifest; that is Day
  10.
- Raw storage does not yet follow the production data-lake path convention;
  that is Day 11.
- Timestamp-unit normalization is intentionally limited to this pre-2025
  millisecond sample; safe mixed-unit support is Day 17.

These are explicit roadmap boundaries rather than hidden defects. Week 2 should
extend the tested components instead of replacing them with a separate script.
