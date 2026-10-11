# Idempotent local sample reruns

An idempotent operation reaches the same correct stored result when it is run
again with the same input.  MarketPulse needs that property because an operator
may retry after an interrupted command or a scheduler may repeat a run.

Run the safe learning sample twice:

```powershell
uv run marketpulse load-sample --limit 5
uv run marketpulse load-sample --limit 5
```

Both commands submit five trusted candles to the local loader.  The command now
also prints `Stored BTCUSDT 1m candles: 5`.  The total must stay five after the
second run, not become ten.

The protection has two layers. dlt saves an `open_time` cursor and configures a
merge key of symbol, interval, and open_time. The Day 14 end-to-end test runs
the real command path twice against one local DuckDB file, then checks that both
the row count and distinct business-key count are five.

This proof deliberately uses a mocked download boundary. It exercises the
already-tested trusted-candle loading path without making a public network call
inside the test suite. A real production workflow will additionally record run
IDs, failure recovery, and warehouse-level idempotency.
