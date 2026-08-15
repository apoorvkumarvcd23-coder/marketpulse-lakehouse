# 90-Day Roadmap

Day 1 was completed on July 28, 2026, and Day 2 resumed on August 1 after three
missed dates. No build ran on August 2 or August 3, so Day 3 resumed on August 4.
No build ran on August 5 or August 6; the user explicitly resumed Day 4 on
August 7. No build ran on August 12 or August 13; the user explicitly resumed
Day 9 on August 14. The remaining sequence now runs daily through November 3,
2026. Days 1 through 9 retain their truthful one-commit history. Starting with
Day 10, each daily milestone is split into three to five meaningful, separately
reviewable commits when its honest scope supports them. Commits are never empty,
cosmetic, padded, fabricated, or backdated.

## Week 1 — Foundations

- D01: Repository, project purpose, private-journal separation, and roadmap.
- D02: Python 3.12 tooling, dependency locking, formatting, linting, and tests.
- D03: Docker Compose and a health-checked PostgreSQL database.
- D04: Configuration loading, environment examples, and secret prevention.
- D05: `MarketCandle` data contract and tests.
- D06: Download and parse a small BTC/USDT candle sample.
- D07: Parser tests, weekly review, and repeatable setup check.

## Week 2 — Reliable ingestion

- D08: HTTP timeouts, retries, and exponential backoff.
- D09: ZIP downloads and checksum verification.
- D10: Restartable ingestion manifest.
- D11: Raw local data-lake layout.
- D12: Incremental ingestion with dlt.
- D13: Local loading and analysis with DuckDB.
- D14: End-to-end idempotency test.

## Week 3 — Spark processing

- D15: Containerized Spark environment.
- D16: Explicit historical-candle schema.
- D17: Millisecond and microsecond timestamp normalization.
- D18: Compressed, partitioned Parquet output.
- D19: Deduplication and candle validation.
- D20: Invalid-row quarantine.
- D21: One-symbol, one-month backfill.

## Week 4 — Orchestration

- D22: Dry-run planner for the complete backfill.
- D23: Restartable three-symbol, 24-month backfill.
- D24: PostgreSQL pipeline audit records.
- D25: Kestra workflows and local services.
- D26: Orchestrated download, validation, processing, and auditing.
- D27: Scheduling, retries, parameters, and concurrency.
- D28: Failure injection and recovery demonstration.

## Week 5 — Reproducibility and cloud preparation

- D29: Architecture, provenance, and local quick start.
- D30: Clean-clone test and local `v0.1` milestone.
- D31: Terraform setup and validation.
- D32: Beginner GCP setup guide.
- D33: GCS and BigQuery infrastructure definitions.
- D34: Least-privilege service accounts.
- D35: Storage lifecycle and budget alerts.

## Week 6 — Cloud batch pipeline

- D36: Automated Terraform plan checks.
- D37: Approved infrastructure deployment and smoke tests.
- D38: Verified raw sample in GCS.
- D39: BigQuery staging load.
- D40: Partitioning, clustering, and query-cost checks.
- D41: Cloud batch orchestration.
- D42: One-month source-to-BigQuery test.

## Week 7 — Analytics engineering

- D43: dbt Core environments for DuckDB and BigQuery.
- D44: Sources and staging models.
- D45: Warehouse quality tests.
- D46: Returns, volume, and activity models.
- D47: Daily-metrics and volatility marts.
- D48: dbt documentation, lineage, and data dictionary.
- D49: BigQuery-aware dbt CI.

## Week 8 — Dashboard

- D50: Complete 24-month dbt build.
- D51: Freshness, completeness, and cost audits.
- D52: Streamlit application structure.
- D53: Filters and headline metrics.
- D54: Price, candlestick, volume, return, and volatility charts.
- D55: Caching, empty states, and read-only access.
- D56: Dashboard tests and `v0.2` milestone.

## Week 9 — Data platforms and streaming foundations

- D57: Local Bruin evaluation.
- D58: Architecture decision for the production stack.
- D59: `AggregateTradeEvent` contract.
- D60: Redpanda topics, retention, and health checks.
- D61: Reconnecting WebSocket producer.
- D62: Basic consumer and message tests.
- D63: Versioned Avro messages.

## Week 10 — Stream processing

- D64: Reproducible PyFlink environment.
- D65: Event time, watermarks, and late data.
- D66: One-minute OHLCV windows.
- D67: Idempotent PostgreSQL sink.
- D68: Dead-letter topic and replay.
- D69: Duplicate, out-of-order, and late-event tests.
- D70: Disconnection and recovery simulation.

## Week 11 — Stream-to-cloud and observability

- D71: Live aggregate synchronization to GCS and BigQuery.
- D72: Near-real-time dbt model.
- D73: Freshness-aware dashboard section.
- D74: Structured logs and correlation IDs.
- D75: Freshness objectives and operational views.
- D76: Health checks and failure notifications.
- D77: Monitoring and incident-response runbook.

## Week 12 — Production hardening

- D78: Secret and dependency scanning.
- D79: GitHub Actions validation matrix.
- D80: Versioned containers and locked dependencies.
- D81: Keyless GitHub-to-GCP authentication.
- D82: Backup, restore, and disaster recovery.
- D83: Runtime, memory, load, and cost benchmarks.
- D84: Full chaos drill.

## Week 13 — Deployment and handoff

- D85: Public Streamlit deployment.
- D86: Production refresh and freshness validation.
- D87: Clean-checkout reproduction.
- D88: Final documentation and demonstration script.
- D89: Project audit, repairs, and cost report.
- D90: Acceptance checks and `v1.0.0` release.
