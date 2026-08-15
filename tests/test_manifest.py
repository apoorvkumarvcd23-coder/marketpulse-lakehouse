"""Tests for restartable, versioned, atomic local ingestion state."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from marketpulse.ingestion.manifest import (
    MAX_MANIFEST_BYTES,
    InvalidManifestTransition,
    ManifestConflictError,
    ManifestDocument,
    ManifestReadError,
    ManifestStatus,
    ManifestStore,
    ManifestWriteError,
)

SOURCE_URL = "https://example.test/data/BTCUSDT-1m-2024-01-01.zip"
CHECKSUM_URL = f"{SOURCE_URL}.CHECKSUM"
EXPECTED_SHA256 = "a" * 64
STARTED_AT = datetime(2026, 8, 15, 13, 30, tzinfo=UTC)


def _plan(store: ManifestStore, root: Path, *, now: datetime = STARTED_AT):
    return store.plan(
        source_url=SOURCE_URL,
        checksum_url=CHECKSUM_URL,
        archive_path=root / "archive.zip",
        checksum_path=root / "archive.zip.CHECKSUM",
        now=now,
    )


def test_missing_manifest_loads_as_an_empty_versioned_document(tmp_path: Path) -> None:
    store = ManifestStore(tmp_path / "manifest.json")

    assert store.load() == ManifestDocument()


def test_plan_is_persisted_and_identical_replanning_is_idempotent(tmp_path: Path) -> None:
    store = ManifestStore(tmp_path / "manifest.json")

    first = _plan(store, tmp_path)
    second = _plan(store, tmp_path, now=STARTED_AT + timedelta(minutes=1))

    assert first == second
    assert first.status is ManifestStatus.PLANNED
    assert first.attempts == 0
    assert store.load().revision == 1
    assert len(first.history) == 1


def test_replanning_same_source_with_different_metadata_fails(tmp_path: Path) -> None:
    store = ManifestStore(tmp_path / "manifest.json")
    _plan(store, tmp_path)

    with pytest.raises(ManifestConflictError, match="different paths"):
        store.plan(
            source_url=SOURCE_URL,
            checksum_url=CHECKSUM_URL,
            archive_path=tmp_path / "different.zip",
            checksum_path=tmp_path / "archive.zip.CHECKSUM",
            now=STARTED_AT,
        )


def test_complete_lifecycle_survives_reload_with_audit_history(tmp_path: Path) -> None:
    store = ManifestStore(tmp_path / "manifest.json")
    _plan(store, tmp_path)
    store.begin_attempt(SOURCE_URL, now=STARTED_AT + timedelta(seconds=1))
    store.mark_downloaded(
        SOURCE_URL,
        bytes_written=123,
        now=STARTED_AT + timedelta(seconds=2),
    )
    store.mark_verified(
        SOURCE_URL,
        expected_sha256=EXPECTED_SHA256,
        calculated_sha256=EXPECTED_SHA256,
        now=STARTED_AT + timedelta(seconds=3),
    )
    store.mark_processing(SOURCE_URL, now=STARTED_AT + timedelta(seconds=4))
    completed = store.mark_processed(
        SOURCE_URL,
        rows_processed=5,
        now=STARTED_AT + timedelta(seconds=5),
    )

    reloaded = ManifestStore(store.path).load()
    assert reloaded.revision == 6
    assert reloaded.records[SOURCE_URL] == completed
    assert completed.status is ManifestStatus.PROCESSED
    assert completed.attempts == 1
    assert completed.bytes_written == 123
    assert completed.expected_sha256 == completed.calculated_sha256 == EXPECTED_SHA256
    assert completed.rows_processed == 5
    assert [event.status for event in completed.history] == list(ManifestStatus)[:-1]


def test_invalid_transition_is_rejected_without_changing_revision(tmp_path: Path) -> None:
    store = ManifestStore(tmp_path / "manifest.json")
    _plan(store, tmp_path)

    with pytest.raises(InvalidManifestTransition, match="planned to verified"):
        store.mark_verified(
            SOURCE_URL,
            expected_sha256=EXPECTED_SHA256,
            calculated_sha256=EXPECTED_SHA256,
        )

    assert store.load().revision == 1


def test_failed_attempt_can_restart_and_increments_attempt_count(tmp_path: Path) -> None:
    store = ManifestStore(tmp_path / "manifest.json")
    _plan(store, tmp_path)
    store.begin_attempt(SOURCE_URL, now=STARTED_AT + timedelta(seconds=1))
    failed = store.mark_failed(
        SOURCE_URL,
        error="temporary source outage",
        now=STARTED_AT + timedelta(seconds=2),
    )
    restarted = store.begin_attempt(SOURCE_URL, now=STARTED_AT + timedelta(seconds=3))

    assert failed.status is ManifestStatus.FAILED
    assert failed.last_error == "temporary source outage"
    assert restarted.status is ManifestStatus.DOWNLOADING
    assert restarted.attempts == 2
    assert restarted.last_error is None


def test_interrupted_downloading_attempt_can_restart(tmp_path: Path) -> None:
    store = ManifestStore(tmp_path / "manifest.json")
    _plan(store, tmp_path)
    store.begin_attempt(SOURCE_URL, now=STARTED_AT + timedelta(seconds=1))

    restarted = store.begin_attempt(SOURCE_URL, now=STARTED_AT + timedelta(seconds=2))

    assert restarted.attempts == 2
    assert [event.status for event in restarted.history][-2:] == [
        ManifestStatus.DOWNLOADING,
        ManifestStatus.DOWNLOADING,
    ]


@pytest.mark.parametrize(
    "content",
    [
        b"not json",
        json.dumps({"schema_version": 2, "revision": 0, "records": {}}).encode(),
        b"\xff",
    ],
)
def test_invalid_manifest_content_fails_loudly(tmp_path: Path, content: bytes) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(content)

    with pytest.raises(ManifestReadError, match="is invalid"):
        ManifestStore(manifest_path).load()


def test_manifest_size_is_bounded_before_json_parsing(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(b" " * (MAX_MANIFEST_BYTES + 1))

    with pytest.raises(ManifestReadError, match="safety limit"):
        ManifestStore(manifest_path).load()


def test_atomic_publication_failure_leaves_no_manifest_or_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ManifestStore(tmp_path / "manifest.json")

    def fail_replace(_source: Path, _destination: Path) -> Path:
        raise OSError("simulated publish failure")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(ManifestWriteError, match="simulated publish failure"):
        _plan(store, tmp_path)

    assert not store.path.exists()
    assert list(tmp_path.glob("*.tmp")) == []
