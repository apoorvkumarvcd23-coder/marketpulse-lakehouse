# Local DuckDB candle analysis

DuckDB is a database that runs as a file on your computer.  Day 12 writes only
trusted candle records to `data/dlt/marketpulse.duckdb`; Day 13 reads that file
without changing it.

Run a small safe load first, then ask for a summary:

```powershell
uv run marketpulse load-sample --limit 5
uv run marketpulse analyze-local --start 2024-01-01T00:00:00Z --end 2024-01-01T00:05:00Z
```

The first timestamp is included and the end timestamp is excluded.  That avoids
counting a candle twice when adjacent windows are combined.  Every timestamp
must contain a timezone; `Z` means UTC.

The command reports the count, first and last candle, price range, and total
base-asset volume for one symbol and one-minute interval.  It opens DuckDB in
read-only mode and supplies user values as query parameters rather than joining
them into SQL text.  The table and schema names are internal constants.

If the database does not exist, run `load-sample` first.  If the result has zero
candles, the requested time window simply contains no loaded data; it is not an
error and the price fields display `<none>`.

This is deliberately a small local inspection tool, not a dashboard or an
investment recommendation.  Later milestones move the same trusted data into
warehouse models and visualizations.
