"""Actual CLI/DuckDB/Parquet/Chromium walkthrough; optional bounded public run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZIP_DEFLATED, ZipFile

import duckdb
from playwright.sync_api import expect, sync_playwright

from marketpulse.batch import current_snapshot, plan
from marketpulse.ingestion.checksum import sha256_file

ROOT = Path(__file__).resolve().parents[1]


def cli(*args: str, success: bool = True) -> dict | str:
    result = subprocess.run(
        [sys.executable, "-m", "marketpulse.cli", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if not success:
        assert result.returncode != 0, "Invalid input unexpectedly published"
        return result.stderr.splitlines()[-1]
    if result.returncode:
        raise RuntimeError("CLI failed: " + result.stderr[-2000:])
    try:
        return json.loads(result.stdout)
    except ValueError:
        return result.stdout.strip()


def inspect(root: Path) -> dict:
    snapshot = current_snapshot(root)
    assert snapshot is not None
    with duckdb.connect(str(snapshot / "warehouse.duckdb"), read_only=True) as db:
        db.execute("SET TimeZone = 'UTC'")
        rows = db.execute(
            "SELECT symbol, interval, open_time, close_time, open, high, low, close, "
            "volume, quote_volume, trade_count FROM marketpulse_data.typed_candles "
            "ORDER BY symbol, interval, open_time"
        ).fetchall()
        distinct = db.execute(
            "SELECT COUNT(DISTINCT (symbol, interval, open_time)) "
            "FROM marketpulse_data.typed_candles"
        ).fetchone()[0]
        parquet_rows = db.execute(
            "SELECT COUNT(*) FROM read_parquet(?, hive_partitioning=true)",
            [str(snapshot / "parquet" / "**" / "*.parquet")],
        ).fetchone()[0]
        summaries = db.execute(
            "SELECT symbol, trade_date, candle_count, expected_minutes, completeness, "
            "open, high, low, close, volume FROM marketpulse_data.daily_summary ORDER BY symbol"
        ).fetchall()
    assert len(rows) == distinct == parquet_rows
    return {
        "rows": len(rows),
        "distinct_keys": distinct,
        "parquet_rows": parquet_rows,
        "business_content_sha256": hashlib.sha256(
            json.dumps(rows, default=str, separators=(",", ":")).encode()
        ).hexdigest(),
        "per_symbol_summaries": [
            dict(
                zip(
                    [
                        "symbol",
                        "utc_day",
                        "candles",
                        "expected_minutes",
                        "completeness",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                    ],
                    row,
                    strict=True,
                )
            )
            for row in summaries
        ],
    }


def trusted_bytes(root: Path) -> dict:
    snapshot = current_snapshot(root)
    assert snapshot is not None
    return {
        "pointer": sha256_file(root / "current.json"),
        "snapshot_files": {
            str(path.relative_to(snapshot)).replace("\\", "/"): sha256_file(path)
            for path in sorted(snapshot.rglob("*"))
            if path.is_file()
        },
    }


@contextmanager
def dashboard(root: Path, log: Path):
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    with log.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(ROOT / "src/marketpulse/dashboard.py"),
                "--server.address",
                "127.0.0.1",
                "--server.port",
                str(port),
                "--server.headless",
                "true",
                "--browser.gatherUsageStats",
                "false",
            ],
            cwd=ROOT,
            env={**os.environ, "MARKETPULSE_BATCH_ROOT": str(root)},
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 45
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Owned dashboard exited before readiness")
                try:
                    with urlopen(base + "/_stcore/health", timeout=2) as response:
                        if response.status == 200:
                            break
                except OSError:
                    if time.monotonic() > deadline:
                        raise RuntimeError("Owned dashboard did not become ready") from None
                    time.sleep(0.1)
            yield base
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def view(browser, root: Path, out: Path, name: str, state: str) -> dict:
    before = trusted_bytes(root) if state in {"fixture", "public"} else None
    with dashboard(root, out / (name + ".log")) as base:
        page = browser.new_page(viewport={"width": 1440, "height": 1050})
        try:
            page.goto(base)
            expect(page.get_by_role("heading", name="MarketPulse Lakehouse")).to_be_visible()
            if state == "empty":
                expect(page.get_by_text("No published batch", exact=False)).to_be_visible()
            elif state == "error":
                expect(
                    page.get_by_text("The published snapshot could not be read", exact=False)
                ).to_be_visible()
            else:
                mode = "synthetic-fixture" if state == "fixture" else "public-source"
                expect(page.get_by_text("latest run: " + mode, exact=False)).to_be_visible()
                expect(page.get_by_text("Historical data:", exact=False)).to_be_visible()
                if state == "fixture":
                    expect(page.get_by_text("Partial historical day:", exact=False)).to_be_visible()
                else:
                    expect(page.get_by_text("Partial historical day:", exact=False)).to_have_count(
                        0
                    )
                page.get_by_role("combobox").first.click()
                page.get_by_role("option", name="ETHUSDT", exact=True).click()
                expect(page.get_by_role("combobox", name="Symbol", exact=True)).to_have_value(
                    "ETHUSDT"
                )
                expect(
                    page.get_by_test_id("stVegaLiteChart").locator("canvas, svg.marks").first
                ).to_be_visible(timeout=45000)
                expect(
                    page.get_by_test_id("stDataFrame").locator("canvas, table, [role='grid']").first
                ).to_be_visible(timeout=45000)
            expect(page.get_by_test_id("stException")).to_have_count(0)
            page.screenshot(path=str(out / (name + ".png")), full_page=True)
        finally:
            page.close()
    if before is not None:
        assert trusted_bytes(root) == before, "Dashboard changed trusted snapshot bytes"
    return {
        "state": state,
        "screenshot": name + ".png",
        "read_only_bytes_verified": before is not None,
    }


def replay(day: date, root: Path, fixture: Path | None) -> dict:
    arguments = ["batch-day", "--date", str(day), "--root", str(root)]
    if fixture is not None:
        arguments += ["--fixture-dir", str(fixture)]
    first = cli(*arguments)
    first_state, old_bytes = inspect(root), trusted_bytes(root)
    old_snapshot = current_snapshot(root)
    second = cli(*arguments)
    second_state = inspect(root)
    assert first_state == second_state
    assert old_snapshot is not None
    assert all(
        sha256_file(old_snapshot / name) == digest
        for name, digest in old_bytes["snapshot_files"].items()
    )
    expected = 9 if fixture is not None else 4320
    assert first["stored_rows"] == second["stored_rows"] == expected
    assert all(s["candles"] == expected // 3 for s in second_state["per_symbol_summaries"])
    return {
        "first": first,
        "replay": second,
        "reconciled": second_state,
        "old_snapshot_unchanged": True,
    }


def demonstrate(out: Path, public_day: date | None) -> dict:
    out.mkdir(parents=True, exist_ok=False)
    data = out / "data"
    data.mkdir()
    fixtures = []
    for day in [date(2024, 1, 1), date(2025, 1, 1)]:
        fixture, root = data / ("fixture-" + str(day)), data / ("batch-" + str(day))
        cli("make-fixture", "--date", str(day), "--output-dir", str(fixture))
        result = replay(day, root, fixture)
        assert all(s["duplicates"] == 1 for s in result["replay"]["sources"])
        assert all(
            str(s["open"]) == "100.00000001" and str(s["volume"]) == "7.50000000"
            for s in result["reconciled"]["per_symbol_summaries"]
        )
        fixtures.append(result)
    root, fixture = data / "batch-2024-01-01", data / "fixture-2024-01-01"
    source = plan(date(2024, 1, 1))[0]
    target = fixture / source.name
    original = target.read_bytes()
    before = trusted_bytes(root)
    target.write_bytes(b"actual-corrupted-fixture-archive")
    checksum_reason = cli(
        "batch-day",
        "--date",
        "2024-01-01",
        "--root",
        str(root),
        "--fixture-dir",
        str(fixture),
        success=False,
    )
    assert trusted_bytes(root) == before
    target.write_bytes(original)
    with ZipFile(target) as archive:
        text = archive.read(source.name[:-4] + ".csv").decode()
    with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(source.name[:-4] + ".csv", text.replace(",103,99,", ",1,99,"))
    target.with_name(target.name + ".CHECKSUM").write_text(
        f"{sha256_file(target)}  {target.name}\n"
    )
    row_reason = cli(
        "batch-day",
        "--date",
        "2024-01-01",
        "--root",
        str(root),
        "--fixture-dir",
        str(fixture),
        success=False,
    )
    assert trusted_bytes(root) == before
    failures = {
        "bad_checksum": checksum_reason,
        "valid_checksum_bad_ohlc": row_reason,
        "pointer_and_all_trusted_snapshot_bytes_unchanged": True,
        "rejected_runs": len(list((root / "runs").glob("*/rejected.json"))),
    }
    assert failures["rejected_runs"] == 2
    public = replay(public_day, data / "public", None) if public_day else None
    error_root = data / "invalid-pointer"
    error_root.mkdir()
    (error_root / "current.json").write_text('{"run_id":"../escape"}')
    with sync_playwright() as api:
        browser = api.chromium.launch()
        try:
            views = [
                view(browser, data / "empty", out, "empty", "empty"),
                view(browser, error_root, out, "invalid-pointer", "error"),
                view(browser, root, out, "fixture-eth", "fixture"),
            ]
            if public:
                views.append(view(browser, data / "public", out, "public-eth", "public"))
        finally:
            browser.close()
    return {
        "status": "passed",
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "integration": (
            "Actual package CLI processes, dlt, DuckDB, Parquet, Streamlit and Chromium; "
            "no API/browser/data-service mocks"
        ),
        "platform": platform.system(),
        "python": platform.python_version(),
        "fixtures_ms_and_us": fixtures,
        "failure_drills": failures,
        "public_source": public,
        "browser": views,
        "limits": (
            "Tiny fixture plus optionally one public UTC day; not throughput, investment advice, "
            "dbt/month-scale completion or a release claim."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True, help="New output directory only")
    parser.add_argument("--public-date", type=date.fromisoformat)
    args = parser.parse_args()
    report = demonstrate(args.artifacts.resolve(), args.public_date)
    (args.artifacts / "integration.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n"
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "public_run": report["public_source"] is not None,
                "browser_views": len(report["browser"]),
            }
        )
    )


if __name__ == "__main__":
    main()
