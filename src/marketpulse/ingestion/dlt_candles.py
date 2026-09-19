"""Small local dlt pipeline for incrementally loading trusted candle records."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import dlt

from marketpulse.contracts import MarketCandle

DEFAULT_DLT_DESTINATION = Path("data/dlt/marketpulse.duckdb")
DLT_PIPELINE_NAME = "marketpulse_local_candles"
DLT_DATASET_NAME = "marketpulse_data"
DLT_TABLE_NAME = "market_candles"


@dlt.resource(
    name=DLT_TABLE_NAME,
    primary_key=["symbol", "interval", "open_time"],
    write_disposition="merge",
    incremental=dlt.sources.incremental("open_time"),
)
def incremental_candles(candles: Iterable[MarketCandle]) -> Iterable[dict[str, object]]:
    """Yield trusted candles for dlt's cursor-aware incremental extraction."""
    for candle in candles:
        yield candle.model_dump(mode="json")


@dataclass(frozen=True, slots=True)
class DltCandleLoad:
    """Evidence from one local dlt load attempt."""

    destination_path: Path
    submitted_rows: int
    load_ids: tuple[str, ...]


def load_incremental_candles(
    candles: Iterable[MarketCandle],
    *,
    destination_path: Path = DEFAULT_DLT_DESTINATION,
) -> DltCandleLoad:
    """Merge new candle business keys into a local DuckDB destination.

    dlt stores its own extraction cursor state beside the ignored local database.
    Later runs skip candle rows older than the saved open_time cursor; the
    business key is also configured as a merge key to make overlap safe.
    """
    prepared_candles = tuple(candles)
    destination_path = Path(destination_path)
    pipeline = dlt.pipeline(
        pipeline_name=DLT_PIPELINE_NAME,
        pipelines_dir=str(destination_path.parent / ".dlt"),
        destination=dlt.destinations.duckdb(str(destination_path)),
        dataset_name=DLT_DATASET_NAME,
    )
    load_info = pipeline.run(incremental_candles(prepared_candles))
    return DltCandleLoad(
        destination_path=destination_path,
        submitted_rows=len(prepared_candles),
        load_ids=tuple(str(load_id) for load_id in load_info.loads_ids),
    )
