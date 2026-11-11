"""Real archive -> dlt -> DuckDB/Parquet -> dashboard checks, without live HTTP."""

import json
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import duckdb
import pytest
from streamlit.testing.v1 import AppTest

from marketpulse import batch, cli
from marketpulse.ingestion.checksum import ChecksumError, sha256_file


def rewrite(directory, source, transform):
    path = directory / source.name
    with ZipFile(path) as archive:
        content = archive.read(source.name[:-4] + ".csv").decode()
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(source.name[:-4] + ".csv", transform(content))
    path.with_name(path.name + ".CHECKSUM").write_text(f"{sha256_file(path)}  {path.name}\n")


@pytest.mark.parametrize("value", [[], ["BTCUSDT", "BTCUSDT"], ["../ETH"], ["LTCUSDT"]])
def test_planner_rejects_unsafe_or_duplicate_symbols(value):
    with pytest.raises(batch.BatchError):
        batch.plan(date(2024, 1, 1), value)


def test_dry_run_has_explicit_six_file_three_mib_budget(capsys):
    assert cli.main(["batch-day", "--date", "2024-01-01", "--dry-run"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["max_files_including_checksums"] == 6
    assert result["max_archive_bytes"] == 3 * 1024**2
    assert len(result["archives"]) == 3
    with pytest.raises(batch.BatchError):
        batch.plan(datetime.now(UTC).date())


def test_units_are_explicit_and_preserve_microseconds():
    assert batch.source_time("1704067200000", "ms") == batch.source_time("1704067200000000", "us")
    assert batch.source_time("1735689600000001", "us").microsecond == 1
    for text, unit in [("1704067200000000", "ms"), ("1704067200000", "us"), ("1.0", "ms")]:
        with pytest.raises(batch.BatchError):
            batch.source_time(text, unit)


@pytest.mark.parametrize("day", [date(2024, 1, 1), date(2025, 1, 1)])
def test_fixture_full_round_trip_replay_and_analytics(tmp_path, day):
    fixtures, root = tmp_path / "fixture", tmp_path / "batch"
    batch.create_fixture(fixtures, day)
    first = batch.run_batch(day, root=root, fixture_dir=fixtures)
    before = batch.current_snapshot(root)
    second = batch.run_batch(day, root=root, fixture_dir=fixtures)
    assert first["stored_rows"] == second["stored_rows"] == 9
    assert second["parquet_rows"] == second["distinct_keys"] == 9
    assert all(s["duplicates"] == 1 for s in second["sources"])
    with duckdb.connect(
        str(batch.current_snapshot(root) / "warehouse.duckdb"), read_only=True
    ) as db:
        assert (
            db.execute(
                "SELECT candle_count, open, close, volume FROM "
                "marketpulse_data.daily_summary ORDER BY symbol"
            ).fetchall()
            == [(3, Decimal("100.00000001"), Decimal("103"), Decimal("7.5"))] * 3
        )
        assert (
            db.execute(
                "SELECT COUNT(*) FROM read_parquet(?, hive_partitioning=true)",
                [str(before / "parquet" / "**" / "*.parquet")],
            ).fetchone()[0]
            == 9
        )
    assert (before / "report.json").is_file()  # readers can retain old snapshots


def test_older_other_symbol_backfill_and_correction_are_not_skipped(tmp_path):
    fixtures, root = tmp_path / "fixture", tmp_path / "batch"
    batch.create_fixture(fixtures, date(2025, 1, 1))
    batch.run_batch(date(2025, 1, 1), root=root, fixture_dir=fixtures, symbols=["BTCUSDT"])
    batch.create_fixture(fixtures)
    batch.run_batch(date(2024, 1, 1), root=root, fixture_dir=fixtures, symbols=["ETHUSDT"])
    source = batch.plan(date(2024, 1, 1), ["ETHUSDT"])[0]
    rewrite(fixtures, source, lambda s: s.replace(",101,", ",102,"))
    report = batch.run_batch(date(2024, 1, 1), root=root, fixture_dir=fixtures, symbols=["ETHUSDT"])
    assert report["stored_rows"] == 6
    with duckdb.connect(
        str(batch.current_snapshot(root) / "warehouse.duckdb"), read_only=True
    ) as db:
        assert db.execute(
            "SELECT close FROM marketpulse_data.typed_candles WHERE symbol='ETHUSDT' "
            "ORDER BY open_time LIMIT 1"
        ).fetchone()[0] == Decimal("102")


@pytest.mark.parametrize(
    "fault", ["checksum", "ohlc", "wrong_date", "precision", "duplicate", "publish"]
)
def test_failed_update_keeps_previous_trusted_snapshot(tmp_path, monkeypatch, fault):
    fixtures, root = tmp_path / "fixture", tmp_path / "batch"
    batch.create_fixture(fixtures)
    batch.run_batch(date(2024, 1, 1), root=root, fixture_dir=fixtures)
    pointer = (root / "current.json").read_bytes()
    snapshot = batch.current_snapshot(root)
    digest = sha256_file(snapshot / "warehouse.duckdb")
    source = batch.plan(date(2024, 1, 1))[0]
    if fault == "checksum":
        (fixtures / source.name).write_bytes(b"corrupt")
    elif fault == "publish":

        def fail(*args):
            raise OSError("injected Parquet failure")

        monkeypatch.setattr(batch, "build_analytics", fail)
    else:
        transformations = {
            "ohlc": lambda s: s.replace(",103,99,", ",1,99,"),
            "wrong_date": lambda s: s.replace("1704067200000", "1704153600000"),
            "precision": lambda s: s.replace("100.00000001", "100.000000001"),
            "duplicate": lambda s: (
                s.rsplit("\n", 2)[0]
                + "\n"
                + s.splitlines()[-1].replace(",103,2.5,", ",102,2.5,")
                + "\n"
            ),
        }
        rewrite(fixtures, source, transformations[fault])
    with pytest.raises((batch.BatchError, ChecksumError, OSError)):
        batch.run_batch(date(2024, 1, 1), root=root, fixture_dir=fixtures)
    assert (root / "current.json").read_bytes() == pointer
    assert sha256_file(snapshot / "warehouse.duckdb") == digest
    assert len(list((root / "runs").glob("*/rejected.json"))) == 1


def test_writer_lock_rejects_other_process_and_releases_after_exit(tmp_path):
    with batch.writer_lock(tmp_path):
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "from marketpulse.batch import writer_lock; from pathlib import Path; "
                f"ctx=writer_lock(Path({str(tmp_path)!r})); ctx.__enter__()",
            ],
            capture_output=True,
        )
        assert completed.returncode != 0
        assert b"another batch writer is active" in completed.stderr
    with batch.writer_lock(tmp_path):
        pass


def test_dashboard_empty_error_and_filtered_snapshot(tmp_path, monkeypatch):
    root, fixtures = tmp_path / "batch", tmp_path / "fixture"
    monkeypatch.setenv("MARKETPULSE_BATCH_ROOT", str(root))
    script = Path(batch.__file__).with_name("dashboard.py")
    view = AppTest.from_file(str(script)).run()
    assert not view.exception and "No published batch" in view.info[0].value
    batch.create_fixture(fixtures)
    batch.run_batch(date(2024, 1, 1), root=root, fixture_dir=fixtures)
    view.run()
    assert not view.exception and len(view.dataframe[0].value) == 1
    view.selectbox[0].select("ETHUSDT").run()
    assert view.dataframe[0].value.iloc[0]["symbol"] == "ETHUSDT"
    assert "Partial historical day" in view.warning[0].value
    (root / "current.json").write_text('{"run_id":"../escape"}')
    view.run()
    assert not view.exception and "could not be read" in view.error[0].value
