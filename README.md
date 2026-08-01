# MarketPulse Lakehouse

MarketPulse Lakehouse is a 90-day data-engineering portfolio project that will
turn public cryptocurrency market data into reliable, tested analytics.

The project follows the DataTalksClub Data Engineering Zoomcamp curriculum while
building one coherent system rather than a collection of unrelated exercises.

## Current status

Day 2: the repository now has a reproducible Python 3.12 environment, a locked
dependency graph, automated formatting and linting, and its first package tests.

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
