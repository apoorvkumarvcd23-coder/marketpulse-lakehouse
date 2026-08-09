"""Beginner-friendly command-line entry point for MarketPulse."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from marketpulse.ingestion import (
    MAX_SAMPLE_ROWS,
    SampleDownloadError,
    SampleFormatError,
    fetch_sample,
)


def _sample_limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("limit must be a whole number") from exc
    if not 1 <= limit <= MAX_SAMPLE_ROWS:
        raise argparse.ArgumentTypeError(f"limit must be between 1 and {MAX_SAMPLE_ROWS}")
    return limit


def build_parser() -> argparse.ArgumentParser:
    """Describe the commands and options accepted by the MarketPulse CLI."""
    parser = argparse.ArgumentParser(
        prog="marketpulse",
        description="Learn and operate the MarketPulse data pipeline.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser(
        "fetch-sample",
        help="download and parse a small fixed BTCUSDT candle sample",
    )
    fetch.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/samples"),
        help="ignored local directory for the ZIP (default: data/samples)",
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the requested command and return a process exit code."""
    parser = build_parser()
    arguments = parser.parse_args(argv)

    if arguments.command == "fetch-sample":
        try:
            batch = fetch_sample(
                arguments.output_dir,
                limit=arguments.limit,
                force=arguments.force,
            )
        except (SampleDownloadError, SampleFormatError) as exc:
            parser.error(str(exc))

        first = batch.candles[0]
        print(f"Archive: {batch.archive_path}")
        print(f"Parsed: {len(batch.candles)} validated BTCUSDT 1m candle(s)")
        print(
            "First business key: "
            f"{first.symbol.value} | {first.interval.value} | {first.open_time.isoformat()}"
        )
        print(f"Archive SHA-256: {batch.archive_sha256}")
        return 0

    parser.error(f"unknown command: {arguments.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
