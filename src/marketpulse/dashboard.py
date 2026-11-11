"""Read-only Streamlit view of one atomically published snapshot."""

import os
from datetime import UTC, datetime
from pathlib import Path

import altair as alt
import duckdb
import streamlit as st

from marketpulse.batch import BatchError, current_snapshot

st.set_page_config(page_title="MarketPulse", layout="wide")
st.title("MarketPulse Lakehouse")
st.caption("Historical batch analytics · UTC · read-only · no investment advice")
root = Path(os.environ.get("MARKETPULSE_BATCH_ROOT", "data/batch"))
try:
    snapshot = current_snapshot(root)
    if snapshot is None:
        st.info("No published batch. Run the offline fixture quick start first.")
        st.stop()
    import json

    report = json.loads((snapshot / "report.json").read_text())
    st.caption(f"Snapshot {report['run_id']} · latest run: {report['mode']}")
    with duckdb.connect(str(snapshot / "warehouse.duckdb"), read_only=True) as connection:
        connection.execute("SET TimeZone = 'UTC'")
        options = connection.execute(
            "SELECT DISTINCT symbol FROM marketpulse_data.daily_summary ORDER BY symbol"
        ).fetchall()
        symbol = st.selectbox("Symbol", [row[0] for row in options])
        days = connection.execute(
            "SELECT trade_date FROM marketpulse_data.daily_summary WHERE symbol=? "
            "ORDER BY trade_date DESC",
            [symbol],
        ).fetchall()
        day = st.selectbox("UTC day", [row[0] for row in days])
        summary = connection.execute(
            "SELECT * FROM marketpulse_data.daily_summary WHERE symbol=? AND trade_date=?",
            [symbol, day],
        ).df()
        st.dataframe(summary, hide_index=True)
        completeness = float(summary.iloc[0]["completeness"])
        if completeness < 1:
            st.warning(
                f"Partial historical day: {completeness:.2%} of 1440 minutes. "
                "The synthetic fixture intentionally contains three minutes."
            )
        age = (datetime.now(UTC).date() - day).days
        st.info(f"Historical data: {age} days old. This is not a live market feed.")
        chart = connection.execute(
            "SELECT open_time, close FROM marketpulse_data.typed_candles "
            "WHERE symbol=? AND trade_date=? ORDER BY open_time",
            [symbol, day],
        ).df()
        st.altair_chart(
            alt.Chart(chart)
            .mark_line()
            .encode(
                x=alt.X("open_time:T", scale=alt.Scale(type="utc"), title="UTC time"),
                y=alt.Y("close:Q", scale=alt.Scale(zero=False), title="Close (USDT)"),
            ),
            width="stretch",
        )
except (BatchError, OSError, ValueError, KeyError, duckdb.Error):
    st.error("The published snapshot could not be read. Check the batch report and rerun setup.")
