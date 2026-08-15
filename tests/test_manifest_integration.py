"""End-to-end evidence that the sample pipeline resumes from its manifest."""

from __future__ import annotations

import hashlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from marketpulse import cli
from marketpulse.ingestion import (
    SAMPLE_ARCHIVE_NAME,
    SAMPLE_CHECKSUM_NAME,
    SAMPLE_CHECKSUM_URL,
    SAMPLE_URL,
    ManifestStatus,
    ManifestStore,
    SampleIntegrityError,
    fetch_sample,
)
from marketpulse.ingestion.binance_sample import SAMPLE_MEMBER_NAME

VALID_ROW = (
    "1704067200000,42283.58000000,42288.00000000,42261.02000000,"
    "42266.95000000,13.70612000,1704067259999,579426.35515540,"
    "624,6.64918000,281051.16154220,0"
)


def _write_valid_cache(directory: Path) -> tuple[Path, Path, str]:
    archive_path = directory / SAMPLE_ARCHIVE_NAME
    checksum_path = directory / SAMPLE_CHECKSUM_NAME
    with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(SAMPLE_MEMBER_NAME, VALID_ROW)
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    checksum_path.write_text(f"{digest}  {SAMPLE_ARCHIVE_NAME}\n", encoding="ascii")
    return archive_path, checksum_path, digest


def _plan(store: ManifestStore, archive_path: Path, checksum_path: Path) -> None:
    store.plan(
        source_url=SAMPLE_URL,
        checksum_url=SAMPLE_CHECKSUM_URL,
        archive_path=archive_path,
        checksum_path=checksum_path,
    )


def test_first_cached_run_reaches_audited_processed_checkpoint(tmp_path: Path) -> None:
    _write_valid_cache(tmp_path)

    batch = fetch_sample(tmp_path, limit=1)
    document = ManifestStore(batch.manifest_path).load()
    record = document.records[SAMPLE_URL]

    assert batch.manifest_status is ManifestStatus.PROCESSED
    assert batch.manifest_attempts == 1
    assert record.status is ManifestStatus.PROCESSED
    assert record.rows_processed == 1
    assert [event.status for event in record.history] == [
        ManifestStatus.PLANNED,
        ManifestStatus.DOWNLOADING,
        ManifestStatus.DOWNLOADED,
        ManifestStatus.VERIFIED,
        ManifestStatus.PROCESSING,
        ManifestStatus.PROCESSED,
    ]


def test_completed_rerun_revalidates_without_mutating_manifest(tmp_path: Path) -> None:
    _write_valid_cache(tmp_path)
    first = fetch_sample(tmp_path, limit=1)
    store = ManifestStore(first.manifest_path)
    revision = store.load().revision

    second = fetch_sample(tmp_path, limit=1)

    assert second.manifest_status is ManifestStatus.PROCESSED
    assert second.manifest_attempts == 1
    assert store.load().revision == revision


def test_verified_checkpoint_resumes_at_processing(tmp_path: Path) -> None:
    archive_path, checksum_path, digest = _write_valid_cache(tmp_path)
    store = ManifestStore(tmp_path / "ingestion-manifest.json")
    _plan(store, archive_path, checksum_path)
    store.begin_attempt(SAMPLE_URL)
    store.mark_downloaded(SAMPLE_URL, bytes_written=archive_path.stat().st_size)
    store.mark_verified(
        SAMPLE_URL,
        expected_sha256=digest,
        calculated_sha256=digest,
    )

    batch = fetch_sample(tmp_path, limit=1)
    record = store.load().records[SAMPLE_URL]

    assert batch.manifest_status is ManifestStatus.PROCESSED
    assert record.attempts == 1
    assert record.history[-2].status is ManifestStatus.PROCESSING


def test_interrupted_download_starts_a_new_attempt_then_uses_valid_cache(
    tmp_path: Path,
) -> None:
    archive_path, checksum_path, _digest = _write_valid_cache(tmp_path)
    store = ManifestStore(tmp_path / "ingestion-manifest.json")
    _plan(store, archive_path, checksum_path)
    store.begin_attempt(SAMPLE_URL)

    batch = fetch_sample(tmp_path, limit=1)
    record = store.load().records[SAMPLE_URL]

    assert batch.manifest_status is ManifestStatus.PROCESSED
    assert record.attempts == 2


def test_tampered_completed_cache_is_recorded_as_failed(tmp_path: Path) -> None:
    archive_path, _checksum_path, _digest = _write_valid_cache(tmp_path)
    fetch_sample(tmp_path, limit=1)
    archive_path.write_bytes(b"tampered")

    with pytest.raises(SampleIntegrityError, match="SHA-256 mismatch"):
        fetch_sample(tmp_path, limit=1)

    record = ManifestStore(tmp_path / "ingestion-manifest.json").load().records[SAMPLE_URL]
    assert record.status is ManifestStatus.FAILED
    assert "SHA-256 mismatch" in record.last_error


def test_cli_reports_manifest_checkpoint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_valid_cache(tmp_path)

    exit_code = cli.main(["fetch-sample", "--output-dir", str(tmp_path), "--limit", "1"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"Manifest: {tmp_path / 'ingestion-manifest.json'}" in output
    assert "Manifest status: processed (attempts: 1)" in output
