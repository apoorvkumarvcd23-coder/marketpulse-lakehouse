"""Beginner-friendly command-line entry point for MarketPulse."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from marketpulse.analysis import DuckDbAnalysisError, summarize_candles
from marketpulse.contracts import MarketSymbol
from marketpulse.doctor import format_doctor_report, run_doctor
from marketpulse.ingestion import (
    DEFAULT_DLT_DESTINATION,
    DEFAULT_SAMPLE_DIRECTORY,
    MAX_SAMPLE_ROWS,
    DltCandleLoad,
    ManifestError,
    SampleDownloadError,
    SampleFormatError,
    SampleIntegrityError,
    fetch_sample,
    load_incremental_candles,
)


def _sample_limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("limit must be a whole number") from exc
    if not 1 <= limit <= MAX_SAMPLE_ROWS:
        raise argparse.ArgumentTypeError(f"limit must be between 1 and {MAX_SAMPLE_ROWS}")
    return limit


def _utc_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and require an explicit timezone."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timestamp must use ISO-8601 format") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone, such as +00:00")
    return parsed.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    """Describe the commands and options accepted by the MarketPulse CLI."""
    parser = argparse.ArgumentParser(
        prog="marketpulse",
        description="Learn and operate the MarketPulse data pipeline.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "doctor",
        help="explain and verify the basic local project setup",
    )
    fetch = commands.add_parser(
        "fetch-sample",
        help="download and parse a small fixed BTCUSDT candle sample",
    )
    fetch.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_SAMPLE_DIRECTORY,
        help=(
            "ignored local directory for the ZIP; default is the partitioned "
            "data/raw Binance BTCUSDT 1m January-2024 location"
        ),
    )
    fetch.add_argument(
        "--limit",
        type=_sample_limit,
        default=5,
        help=f"number of candle rows to parse, from 1 to {MAX_SAMPLE_ROWS} (default: 5)",
    )
    fetch.add_argument(
        "--force",
        action="store_true",
        help="replace an existing local copy with one fresh download",
    )
    load_sample = commands.add_parser(
        "load-sample",
        help="incrementally merge the trusted learning sample into local DuckDB",
    )
    load_sample.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_SAMPLE_DIRECTORY,
        help="raw sample directory to read before loading",
    )
    load_sample.add_argument(
        "--destination",
        type=Path,
        default=DEFAULT_DLT_DESTINATION,
        help="ignored local DuckDB destination for the incremental table",
    )
    load_sample.add_argument(
        "--limit",
        type=_sample_limit,
        default=5,
        help=f"number of trusted sample candles to load, from 1 to {MAX_SAMPLE_ROWS}",
    )
    analyze = commands.add_parser(
        "analyze-local",
        help="summarize trusted candles in the local DuckDB destination",
    )
    analyze.add_argument(
        "--symbol",
        choices=[symbol.value for symbol in MarketSymbol],
        default=MarketSymbol.BTC_USDT.value,
        help="trading pair to summarize (default: BTCUSDT)",
    )
    analyze.add_argument(
        "--start",
        type=_utc_timestamp,
        help="inclusive ISO-8601 UTC window start, for example 2024-01-01T00:00:00Z",
    )
    analyze.add_argument(
        "--end",
        type=_utc_timestamp,
        help="exclusive ISO-8601 UTC window end, for example 2024-01-02T00:00:00Z",
    )
    analyze.add_argument(
        "--destination",
        type=Path,
        default=DEFAULT_DLT_DESTINATION,
        help="ignored local DuckDB destination to query",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the requested command and return a process exit code."""
    parser = build_parser()
    arguments = parser.parse_args(argv)

    if arguments.command == "doctor":
        report = run_doctor(Path.cwd())
        print(format_doctor_report(report))
        return 0 if report.passed else 1

    if arguments.command == "fetch-sample":
        try:
            batch = fetch_sample(
                arguments.output_dir,
                limit=arguments.limit,
                force=arguments.force,
            )
        except (
            ManifestError,
            SampleDownloadError,
            SampleFormatError,
            SampleIntegrityError,
        ) as exc:
            parser.error(str(exc))

        first = batch.candles[0]
        print(f"Archive: {batch.archive_path}")
        print(f"Parsed: {len(batch.candles)} validated BTCUSDT 1m candle(s)")
        print(
            "First business key: "
            f"{first.symbol.value} | {first.interval.value} | {first.open_time.isoformat()}"
        )
        print(f"Archive SHA-256: {batch.archive_sha256}")
        verification = "verified" if batch.official_checksum_verified else "not verified"
        print(f"Official checksum: {verification}")
        print(f"Manifest: {batch.manifest_path}")
        print(
            f"Manifest status: {batch.manifest_status.value} (attempts: {batch.manifest_attempts})"
        )
        return 0

    if arguments.command == "load-sample":
        try:
            batch = fetch_sample(arguments.output_dir, limit=arguments.limit)
            result: DltCandleLoad = load_incremental_candles(
                batch.candles,
                destination_path=arguments.destination,
            )
        except (
            ManifestError,
            SampleDownloadError,
            SampleFormatError,
            SampleIntegrityError,
        ) as exc:
            parser.error(str(exc))

        print(f"Loaded: {result.submitted_rows} trusted candle(s)")
        print(f"DuckDB: {result.destination_path}")
        print(f"dlt load ID(s): {', '.join(result.load_ids) or '<none>'}")
        return 0

    if arguments.command == "analyze-local":
        try:
            summary = summarize_candles(
                symbol=MarketSymbol(arguments.symbol),
                start=arguments.start,
                end=arguments.end,
                destination_path=arguments.destination,
            )
        except (DuckDbAnalysisError, ValueError) as exc:
            parser.error(str(exc))

        first_open = summary.first_open_time.isoformat() if summary.first_open_time else "<none>"
        last_open = summary.last_open_time.isoformat() if summary.last_open_time else "<none>"
        lowest_price = summary.lowest_price if summary.lowest_price is not None else "<none>"
        highest_price = summary.highest_price if summary.highest_price is not None else "<none>"
        print(f"Symbol: {summary.symbol.value}")
        print(f"Interval: {summary.interval.value}")
        print(f"Candles: {summary.candle_count}")
        print(f"First open: {first_open}")
        print(f"Last open: {last_open}")
        print(f"Lowest price: {lowest_price}")
        print(f"Highest price: {highest_price}")
        print(f"Total volume: {summary.total_volume}")
        return 0

    parser.error(f"unknown command: {arguments.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
