# MarketPulse Lakehouse

MarketPulse Lakehouse is a 90-day data-engineering portfolio project that will
turn public cryptocurrency market data into reliable, tested analytics.

The project follows the DataTalksClub Data Engineering Zoomcamp curriculum while
building one coherent system rather than a collection of unrelated exercises.

## Current status

Day 9: the sample now downloads Binance's matching `.CHECKSUM` record, binds it
to the exact ZIP name, calculates SHA-256 locally, and refuses unverified bytes
before ZIP or CSV parsing begins.

## What the finished system will do

1. Download two years of one-minute BTC/USDT, ETH/USDT, and SOL/USDT candles.
2. Verify source checksums and quarantine invalid data.
3. Store raw and processed data in a partitioned data lake.
4. Load queryable models into BigQuery.
5. Transform and test analytics models with dbt.
6. Process live aggregate trades with Redpanda and PyFlink.
7. Present price, volume, returns, volatility, and freshness in Streamlit.

## Safety and scope

- This project uses public market data only.
- It never accesses exchange accounts, API trading keys, or user funds.
- It does not execute trades or provide investment advice.
- Secrets, generated datasets, and the private learning journal are excluded
  from Git.

## Learning approach

The public repository contains professional implementation and operational
documentation. A separate private local journal explains every daily commit
from first principles and includes interview practice.

See [ROADMAP.md](ROADMAP.md) for the scheduled milestones.

## Check the local setup

Run the setup doctor from the repository root whenever a command behaves
unexpectedly or after cloning the project on another computer:

```powershell
uv run marketpulse doctor
```

It checks five deterministic requirements: Python 3.12, required project files,
project metadata, the `uv` lockfile, and Git exclusions for generated data,
private outputs, and `.env`. Every failure includes one repair hint. The doctor
is read-only: it does not start Docker, download data, inspect secrets, or make
network calls.

See the [Week 1 acceptance review](docs/reviews/week-01.md) for delivered
capabilities, verification commands, parser failure coverage, and the explicit
limits carried into Week 2.

## Fetch the learning sample

The first ingestion command uses Binance's public BTCUSDT one-minute file for
2024-01-01. A fixed historical date makes the result repeatable, and the
generated ZIP stays under the ignored `data/` directory.

```powershell
uv run marketpulse fetch-sample --limit 5
```

The command prints the archive path, number of parsed candles, first business
key, locally calculated SHA-256 fingerprint, and `Official checksum: verified`.
It downloads both the ZIP and Binance's matching `.CHECKSUM` through the bounded
HTTP client. Candidate files remain private until the checksum names the exact
source archive and the locally calculated digest matches. A mismatch preserves
the previous published pair and stops before parsing. See the
[sample ingestion guide](docs/ingestion/btcusdt-sample.md) for the source-to-contract
mapping and safety boundaries, and the
[HTTP reliability policy](docs/ingestion/http-reliability.md) for failure
classification and retry behavior. The
[checksum verification policy](docs/ingestion/checksum-verification.md) explains
the trust boundary, strict file format, cache behavior, and failure evidence.

## Developer setup

The project uses [uv](https://docs.astral.sh/uv/) to install the correct Python
version and reproduce the same dependency versions on every machine.

```powershell
uv python install 3.12
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run pytest
```

`uv.lock` must change in the same commit whenever project dependencies change.

## Local configuration

Configuration means the values that can change between a laptop, automated
tests, and production without changing the application code. Create a private
local `.env` file from the committed example before running the database:

```powershell
Copy-Item .env.example .env
```

The example contains only a clearly marked local-development password. Change
that value in `.env`; never add real cloud credentials or exchange keys to
`.env.example`. The application validates values at startup and masks the
PostgreSQL password in its safe diagnostic summary:

```powershell
uv run python -c "from marketpulse.config import get_settings; print(get_settings().public_summary())"
```

The real `.env` file, common credential formats, and the private `secrets/`
directory are ignored by Git. `.dockerignore` also prevents those files from
being sent into a future container-image build context.

## First data contract

`MarketCandle` is the boundary between untrusted source rows and trusted
pipeline data. It accepts only the three project symbols and one-minute
candles, preserves prices and volumes as decimals, normalizes timezone-aware
timestamps to UTC, and records source provenance.

```python
from marketpulse.contracts import MarketCandle
```

The natural uniqueness key is `(symbol, interval, open_time)`. Unsupported or
impossible records fail validation before they can reach storage. See the
[MarketCandle contract](docs/data-contracts/market-candle.md) for every field,
invariant, source mapping, and rejection rule.

## Local PostgreSQL

The database runs in Docker, so PostgreSQL does not need to be installed directly
on the computer. The published port is bound to `127.0.0.1`, which means it is
reachable from this computer but is not exposed to the local network.

```powershell
docker compose up -d --wait postgres
docker compose ps
docker compose exec -T postgres pg_isready -U marketpulse -d marketpulse
docker compose exec -T postgres psql -U marketpulse -d marketpulse -c "SELECT 1;"
docker compose down
```

The named `postgres-data` volume survives `docker compose down`. PostgreSQL now
receives its password from the private `.env` file; Compose stops with a useful
message if that required value is missing.
