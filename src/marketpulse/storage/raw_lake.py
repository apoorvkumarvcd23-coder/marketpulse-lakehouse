"""Safe, predictable paths for raw market files kept on the local data lake."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SOURCE_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
_DATASET_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
_INTERVAL_PATTERN = re.compile(r"^[1-9][0-9]*[mhdwM]$")
_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{5,20}$")


class RawLakePathError(ValueError):
    """A raw-lake path part would be unsafe or ambiguous."""


def _validated(value: str, *, label: str, pattern: re.Pattern[str]) -> str:
    if not pattern.fullmatch(value):
        raise RawLakePathError(f"{label} has an invalid value: {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class RawLakePartition:
    """The business dimensions that identify one raw-file partition."""

    source: str
    dataset: str
    interval: str
    symbol: str
    year: int
    month: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source", _validated(self.source, label="source", pattern=_SOURCE_PATTERN)
        )
        object.__setattr__(
            self, "dataset", _validated(self.dataset, label="dataset", pattern=_DATASET_PATTERN)
        )
        object.__setattr__(
            self, "interval", _validated(self.interval, label="interval", pattern=_INTERVAL_PATTERN)
        )
        object.__setattr__(
            self, "symbol", _validated(self.symbol, label="symbol", pattern=_SYMBOL_PATTERN)
        )
        if not 2000 <= self.year <= 2100:
            raise RawLakePathError("year must be between 2000 and 2100")
        if not 1 <= self.month <= 12:
            raise RawLakePathError("month must be between 1 and 12")

    @property
    def relative_directory(self) -> Path:
        """Return the durable Hive-style directory layout, relative to the lake root."""
        return Path(
            f"source={self.source}",
            f"dataset={self.dataset}",
            f"interval={self.interval}",
            f"symbol={self.symbol}",
            f"year={self.year:04d}",
            f"month={self.month:02d}",
        )


@dataclass(frozen=True, slots=True)
class RawLake:
    """A local raw zone that refuses files outside its configured root."""

    root: Path = Path("data/raw")

    def directory_for(self, partition: RawLakePartition, *, create: bool = False) -> Path:
        """Return one partition directory and optionally create it."""
        directory = self.root / partition.relative_directory
        if create:
            directory.mkdir(parents=True, exist_ok=True)
        return directory

    def archive_path(self, partition: RawLakePartition, filename: str) -> Path:
        """Return a safe archive path within one partition."""
        candidate_name = Path(filename)
        if (
            candidate_name.name != filename
            or filename in {"", ".", ".."}
            or not filename.endswith(".zip")
        ):
            raise RawLakePathError("filename must be a single .zip filename")
        return self.directory_for(partition) / candidate_name
