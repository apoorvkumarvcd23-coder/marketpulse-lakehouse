# Raw local data lake layout

The **raw zone** is the first durable home for a file received from a data source.
It keeps the source file as received, alongside its checksum and ingestion
manifest. It is not yet a cleaned analytics table.

MarketPulse stores files under `data/raw` using this predictable layout:

```text
data/raw/
  source=binance/
    dataset=klines/
      interval=1m/
        symbol=BTCUSDT/
          year=2024/
            month=01/
              BTCUSDT-1m-2024-01-01.zip
              BTCUSDT-1m-2024-01-01.zip.CHECKSUM
              ingestion-manifest.json
```

Each `name=value` folder is a **partition**: a small, clearly labelled slice of
the overall data. The labels are deliberately stable so Spark, DuckDB, and cloud
storage readers can select only the files they need later. For example, a query
for `symbol=BTCUSDT` does not need to scan an ETHUSDT directory.

`RawLakePartition` in `src/marketpulse/storage/raw_lake.py` validates every
folder value before composing a path. It rejects path traversal such as
`../outside.zip`, ambiguous values such as `btc/usdt`, and invalid months. This
keeps untrusted source metadata from deciding where the pipeline writes files.

## Try it safely

From the repository root, run:

```powershell
uv run marketpulse fetch-sample --limit 5
```

The sample archive, its official checksum, and its ingestion manifest will be
created below the BTCUSDT January-2024 partition. `data/` is ignored by Git, so
the downloaded market data never becomes part of the public source repository.

To use a disposable learning folder instead, provide `--output-dir` explicitly:

```powershell
uv run marketpulse fetch-sample --output-dir data/learning-copy --limit 1
```

## Interview-sized explanation

"I treated raw storage as an auditable landing zone. I used a Hive-style
`key=value` directory convention because the same business dimensions later help
both local tools and cloud engines prune irrelevant data. I validate path parts
before writing so source-controlled names cannot escape the lake root."
