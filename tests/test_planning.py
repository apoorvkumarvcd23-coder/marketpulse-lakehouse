"""Bounded range planning is deterministic and does not access source or warehouse data."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import PurePosixPath
from urllib.parse import urlsplit

import pytest

from marketpulse import cli
from marketpulse.batch import ARCHIVE_LIMIT, BatchError
from marketpulse.ingestion.checksum import MAX_CHECKSUM_FILE_BYTES
from marketpulse.ingestion.http_client import HttpClient
from marketpulse.planning import plan_range

PAIR_BYTES = ARCHIVE_LIMIT + MAX_CHECKSUM_FILE_BYTES


def request(start=date(2025, 1, 1), end=date(2025, 2, 1), **kwargs):
    return plan_range(start, end, max_files=186, max_bytes=100_000_000, **kwargs)


@pytest.mark.parametrize(
    ("start", "end", "days"),
    [
        (date(2025, 1, 1), date(2025, 2, 1), 31),
        (date(2024, 2, 1), date(2024, 3, 1), 29),
        (date(2025, 2, 1), date(2025, 3, 1), 28),
    ],
)
def test_month_end_and_leap_year_enumerate_every_day_pair_and_checksum(start, end, days):
    report = request(start, end)
    assert report["days"] == days and report["archive_count"] == days * 3
    assert report["file_count"] == len(report["files"]) == days * 6
    assert report["planned_max_bytes"] == sum(item["max_bytes"] for item in report["files"])
    assert report["planned_max_bytes"] == days * 3 * PAIR_BYTES
    expected = {
        (str(start + timedelta(days=i)), symbol)
        for i in range(days)
        for symbol in report["symbols"]
    }
    for kind in ("archive", "checksum"):
        assert {
            (item["date"], item["symbol"]) for item in report["files"] if item["kind"] == kind
        } == expected
    assert len({item["url"] for item in report["files"]}) == days * 6
    assert report["files"][0]["date"] == start.isoformat()
    assert report["files"][-1]["date"] == (end - timedelta(days=1)).isoformat()
    for item in report["files"]:
        url, path = urlsplit(item["url"]), PurePosixPath(item["relative_path"])
        assert url.scheme == "https" and url.hostname == "data.binance.vision"
        assert url.username is None and url.password is None and not url.query and not url.fragment
        assert not path.is_absolute() and ".." not in path.parts
        assert "\\" not in str(path) and ":" not in str(path)
        assert path.parts[:2] == ("raw", "source=binance")
        assert path.name == PurePosixPath(url.path).name


def test_budget_boundary_includes_checksums_and_rejects_one_byte_or_file_short():
    start, end = date(2025, 1, 1), date(2025, 2, 1)
    exact = plan_range(start, end, max_files=186, max_bytes=93 * PAIR_BYTES)
    assert exact["planned_max_bytes"] == 97_612_800
    with pytest.raises(BatchError, match="file budget exceeded"):
        plan_range(start, end, max_files=185, max_bytes=100_000_000)
    with pytest.raises(BatchError, match="byte budget exceeded"):
        plan_range(start, end, max_files=186, max_bytes=93 * PAIR_BYTES - 1)
    one = plan_range(
        start, start + timedelta(days=1), ["SOLUSDT"], max_files=2, max_bytes=PAIR_BYTES
    )
    assert one["archive_count"] == 1 and one["file_count"] == 2


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "186", None])
@pytest.mark.parametrize("field", ["max_files", "max_bytes"])
def test_programmatic_budgets_require_positive_integers(field, value):
    budgets = {"max_files": 186, "max_bytes": 100_000_000, field: value}
    with pytest.raises(BatchError, match="positive whole"):
        plan_range(date(2025, 1, 1), date(2025, 2, 1), **budgets)


@pytest.mark.parametrize(
    "symbols",
    [
        [],
        ["BTCUSDT", "BTCUSDT"],
        ["LTCUSDT"],
        ["../BTCUSDT"],
        ["C:\\BTCUSDT"],
        ["BTC%2F.."],
        ["btcusdt"],
        ["https://example.com"],
    ],
)
def test_range_rejects_unsupported_or_path_like_symbols(symbols):
    with pytest.raises(BatchError):
        request(symbols=symbols)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2025, 1, 1), date(2025, 1, 1)),
        (date(2025, 1, 2), date(2025, 1, 1)),
        (date(2025, 1, 1), date(2025, 2, 2)),
        (date(2019, 12, 31), date(2020, 1, 1)),
        (datetime(2025, 1, 1, tzinfo=UTC), date(2025, 1, 2)),
        ("2025-01-01", date(2025, 1, 2)),
    ],
)
def test_invalid_or_unbounded_ranges_fail_before_source_enumeration(start, end):
    with pytest.raises(BatchError):
        request(start, end)


def test_completed_utc_boundary_and_archive_unit_change_are_explicit():
    today = datetime.now(UTC).date()
    assert request(today - timedelta(days=1), today)["days"] == 1
    with pytest.raises(BatchError, match="completed UTC"):
        request(today, today + timedelta(days=2))
    report = request(date(2024, 12, 31), date(2025, 1, 2))
    assert {item["timestamp_unit"] for item in report["files"] if item["date"] == "2024-12-31"} == {
        "ms"
    }
    assert {item["timestamp_unit"] for item in report["files"] if item["date"] == "2025-01-01"} == {
        "us"
    }


def test_cli_is_read_only_offline_repeatable_and_never_prints_partial_failed_plan(
    tmp_path, monkeypatch, capsys
):
    def forbidden(*args, **kwargs):
        raise AssertionError("A dry-run attempted an HTTP download")

    monkeypatch.setattr(HttpClient, "download", forbidden)
    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "data" / "batch"
    root.mkdir(parents=True)
    (root / "current.json").write_bytes(b"trusted pointer sentinel")
    (root / "warehouse.duckdb").write_bytes(b"trusted warehouse sentinel")
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    args = [
        "plan-range",
        "--start",
        "2025-01-01",
        "--end",
        "2025-02-01",
        "--max-files",
        "186",
        "--max-bytes",
        "100000000",
    ]
    assert cli.main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert cli.main([*args, "--symbols", "SOLUSDT", "ETHUSDT", "BTCUSDT"]) == 0
    assert json.loads(capsys.readouterr().out) == first
    with pytest.raises(SystemExit) as failure:
        cli.main([*args[:-1], "1"])
    assert failure.value.code == 2 and capsys.readouterr().out == ""
    assert {
        p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
    } == before


@pytest.mark.parametrize(
    "value", ["2025-02-29", "20250101", "2025-W01-1", "../2025-01-01", "2025-01-01T00:00:00Z"]
)
def test_cli_dates_are_canonical_calendar_dates(value, capsys):
    with pytest.raises(SystemExit) as failure:
        cli.main(
            [
                "plan-range",
                "--start",
                value,
                "--end",
                "2025-02-01",
                "--max-files",
                "186",
                "--max-bytes",
                "100000000",
            ]
        )
    assert failure.value.code == 2 and capsys.readouterr().out == ""


@pytest.mark.parametrize("field", ["--max-files", "--max-bytes"])
def test_cli_requires_each_explicit_budget(field, capsys):
    with pytest.raises(SystemExit) as failure:
        cli.main(["plan-range", "--start", "2025-01-01", "--end", "2025-02-01", field, "186"])
    assert failure.value.code == 2 and capsys.readouterr().out == ""
