"""Read-only bounded source manifests; no network or data-root operations."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from marketpulse.batch import ARCHIVE_LIMIT, BatchError, Source, plan
from marketpulse.ingestion.checksum import MAX_CHECKSUM_FILE_BYTES

MAX_PLAN_DAYS = 31


def plan_range(
    start: date,
    end: date,
    symbols: list[str] | None = None,
    *,
    max_files: int,
    max_bytes: int,
) -> dict:
    """Plan [start, end), checking caps before enumerating at most 186 files.

    Bytes bound accepted file payloads, including checksums. They are not observed
    source sizes, retry traffic, expanded CSV or resulting warehouse disk usage.
    """
    if type(start) is not date or type(end) is not date:
        raise BatchError("start and end must be calendar dates")
    days = (end - start).days
    if not 1 <= days <= MAX_PLAN_DAYS:
        raise BatchError("choose an inclusive start/exclusive end spanning 1–31 UTC days")
    if end > datetime.now(UTC).date():
        raise BatchError("the range must contain only completed UTC days")
    if any(type(value) is not int or value < 1 for value in (max_files, max_bytes)):
        raise BatchError("file and byte budgets must be positive whole numbers")
    first = plan(start, symbols)  # Reuse the daily historical-date/pair allowlist.
    archive_count = days * len(first)
    file_count = archive_count * 2
    planned_bytes = archive_count * (ARCHIVE_LIMIT + MAX_CHECKSUM_FILE_BYTES)
    if file_count > max_files:
        raise BatchError(f"file budget exceeded: plan needs {file_count}, supplied {max_files}")
    if planned_bytes > max_bytes:
        raise BatchError(f"byte budget exceeded: plan needs {planned_bytes}, supplied {max_bytes}")
    files = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        for selected in first:
            source = Source(selected.symbol, day)
            relative = f"raw/source=binance/symbol={source.symbol}/date={day}/{source.name}"
            for kind, suffix, limit in (
                ("archive", "", ARCHIVE_LIMIT),
                ("checksum", ".CHECKSUM", MAX_CHECKSUM_FILE_BYTES),
            ):
                files.append(
                    {
                        "kind": kind,
                        "symbol": source.symbol,
                        "date": day.isoformat(),
                        "timestamp_unit": source.unit,
                        "url": source.url + suffix,
                        "relative_path": relative + suffix,
                        "max_bytes": limit,
                    }
                )
    return {
        "format_version": 1,
        "mode": "dry-run",
        "start": start.isoformat(),
        "end_exclusive": end.isoformat(),
        "days": days,
        "symbols": [source.symbol for source in first],
        "interval": "1m",
        "archive_count": archive_count,
        "file_count": file_count,
        "planned_max_bytes": planned_bytes,
        "budget": {"max_files": max_files, "max_bytes": max_bytes},
        "byte_budget_basis": "per-file payload caps; excludes retries and expanded/storage output",
        "source_availability": "not checked",
        "files": files,
    }
