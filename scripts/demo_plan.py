"""Verify the actual installed range-planning CLI without source downloads or data writes."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def demonstrate(artifacts: Path) -> dict:
    if artifacts.exists():
        raise ValueError("Use a new artifact directory; existing files are preserved")
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
    with TemporaryDirectory(prefix="marketpulse-plan-") as temporary:
        cwd = Path(temporary)
        root = cwd / "data" / "batch"
        root.mkdir(parents=True)
        (root / "current.json").write_bytes(b"synthetic trusted pointer sentinel")
        (root / "warehouse.duckdb").write_bytes(b"synthetic trusted database sentinel")

        def snapshot():
            return {p.relative_to(cwd): p.read_bytes() for p in cwd.rglob("*") if p.is_file()}

        def invoke(options):
            return subprocess.run(
                [sys.executable, "-m", "marketpulse.cli", *options],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=60,
            )

        before = snapshot()
        first = invoke(args)
        assert first.returncode == 0, first.stderr
        manifest = json.loads(first.stdout)
        repeated = invoke([*args, "--symbols", "SOLUSDT", "ETHUSDT", "BTCUSDT"])
        assert repeated.returncode == 0 and json.loads(repeated.stdout) == manifest
        assert manifest["archive_count"] == 93 and manifest["file_count"] == 186
        assert manifest["planned_max_bytes"] == 97_612_800
        assert sum(row["max_bytes"] for row in manifest["files"]) == 97_612_800
        faults = {
            "file_budget": [*args[:6], "185", *args[7:]],
            "byte_budget": [*args[:-1], "97612799"],
            "range_limit": [*args[:4], "2025-02-02", *args[5:]],
            "unsafe_symbol": [*args, "--symbols", "../BTCUSDT"],
            "canonical_date": [args[0], args[1], "20250101", *args[3:]],
        }
        rejected = {}
        for name, options in faults.items():
            result = invoke(options)
            assert result.returncode == 2 and not result.stdout and result.stderr
            rejected[name] = True
        assert snapshot() == before
    serialized = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    report = {
        "status": "passed",
        "integration": "Actual installed Python package CLI subprocesses; no CLI/plan mocks",
        "platform": platform.system(),
        "archive_count": 93,
        "file_count": 186,
        "planned_max_bytes": 97_612_800,
        "manifest_sha256": hashlib.sha256(serialized.encode()).hexdigest(),
        "repeatable_with_reordered_symbols": True,
        "rejected_cases": rejected,
        "all_existing_data_bytes_and_file_set_unchanged": True,
        "limits": (
            "Offline planning only. Source existence/sizes, actual month ingestion, "
            "retry traffic and expanded/storage output are unverified."
        ),
    }
    artifacts.mkdir(parents=True)
    (artifacts / "manifest.json").write_bytes(serialized.encode("utf-8"))
    (artifacts / "verification.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    report = demonstrate(args.artifacts.resolve())
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
