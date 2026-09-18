"""Tests for the raw data-lake path convention."""

from __future__ import annotations

from pathlib import Path

import pytest

from marketpulse.storage import RawLake, RawLakePartition, RawLakePathError


def test_partition_uses_queryable_hive_style_directories() -> None:
    partition = RawLakePartition(
        source="binance",
        dataset="klines",
        interval="1m",
        symbol="BTCUSDT",
        year=2024,
        month=1,
    )

    assert partition.relative_directory == Path(
        "source=binance/dataset=klines/interval=1m/symbol=BTCUSDT/year=2024/month=01"
    )


def test_lake_creates_partition_and_keeps_archive_inside_it(tmp_path: Path) -> None:
    lake = RawLake(tmp_path / "raw")
    partition = RawLakePartition("binance", "klines", "1m", "BTCUSDT", 2024, 1)

    directory = lake.directory_for(partition, create=True)
    archive = lake.archive_path(partition, "BTCUSDT-1m-2024-01.zip")

    assert directory.is_dir()
    assert archive.parent == directory
    assert archive.is_relative_to(lake.root)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"source": "Binance"}, "source"),
        ({"interval": "one-minute"}, "interval"),
        ({"symbol": "btc/usdt"}, "symbol"),
        ({"month": 13}, "month"),
    ],
)
def test_partition_rejects_unsafe_or_invalid_dimensions(
    kwargs: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "source": "binance",
        "dataset": "klines",
        "interval": "1m",
        "symbol": "BTCUSDT",
        "year": 2024,
        "month": 1,
    }
    values.update(kwargs)

    with pytest.raises(RawLakePathError, match=message):
        RawLakePartition(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("filename", ["../outside.zip", "nested/file.zip", "file.csv", ""])
def test_archive_path_rejects_traversal_and_non_zip_names(filename: str) -> None:
    partition = RawLakePartition("binance", "klines", "1m", "BTCUSDT", 2024, 1)

    with pytest.raises(RawLakePathError, match="filename"):
        RawLake().archive_path(partition, filename)
