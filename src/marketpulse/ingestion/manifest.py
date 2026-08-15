"""Restartable ingestion state persisted as an atomic local JSON manifest."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

MAX_MANIFEST_BYTES = 5 * 1024 * 1024


class ManifestError(RuntimeError):
    """Base error for local manifest operations."""


class ManifestReadError(ManifestError):
    """The persisted manifest could not be read or validated."""


class ManifestWriteError(ManifestError):
    """A new manifest revision could not be published atomically."""


class ManifestConflictError(ManifestError):
    """An existing source key was planned with different immutable metadata."""


class InvalidManifestTransition(ManifestError):
    """A status change would violate the ingestion lifecycle."""


class ManifestStatus(StrEnum):
    """Durable checkpoints for one source file's ingestion lifecycle."""

    PLANNED = "planned"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    VERIFIED = "verified"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class ManifestEvent(BaseModel):
    """One timestamped status observation kept for audit and diagnosis."""

    model_config = ConfigDict(frozen=True)

    status: ManifestStatus
    occurred_at: datetime
    detail: str = Field(min_length=1, max_length=500)

    @field_validator("occurred_at")
    @classmethod
    def normalize_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(UTC)


class ManifestRecord(BaseModel):
    """Current state and evidence for one exact source URL."""

    model_config = ConfigDict(frozen=True)

    source_url: str
    checksum_url: str
    archive_path: str = Field(min_length=1)
    checksum_path: str = Field(min_length=1)
    status: ManifestStatus
    attempts: int = Field(default=0, ge=0)
    bytes_written: int | None = Field(default=None, gt=0)
    expected_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    calculated_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    rows_processed: int | None = Field(default=None, gt=0)
    last_error: str | None = Field(default=None, min_length=1, max_length=1000)
    updated_at: datetime
    history: tuple[ManifestEvent, ...] = Field(min_length=1)

    @field_validator("source_url", "checksum_url")
    @classmethod
    def require_http_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("manifest URLs must use http or https and include a host")
        return value

    @field_validator("updated_at")
    @classmethod
    def normalize_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("updated_at must include a timezone")
        return value.astimezone(UTC)


class ManifestDocument(BaseModel):
    """Versioned JSON document containing all local source records."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    records: dict[str, ManifestRecord] = Field(default_factory=dict)


def _now_utc(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("manifest timestamps must include a timezone")
    return current.astimezone(UTC)


class ManifestStore:
    """Load and atomically replace a local manifest after each transition."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> ManifestDocument:
        """Return an empty document when absent or a validated saved document."""
        if not self.path.exists():
            return ManifestDocument()
        try:
            with self.path.open("rb") as source:
                content = source.read(MAX_MANIFEST_BYTES + 1)
        except OSError as exc:
            raise ManifestReadError(f"could not read manifest {self.path}: {exc}") from exc
        if len(content) > MAX_MANIFEST_BYTES:
            raise ManifestReadError(f"manifest exceeds the {MAX_MANIFEST_BYTES}-byte safety limit")
        try:
            payload = json.loads(content.decode("utf-8"))
            return ManifestDocument.model_validate(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
            raise ManifestReadError(f"manifest {self.path} is invalid: {exc}") from exc

    def plan(
        self,
        *,
        source_url: str,
        checksum_url: str,
        archive_path: Path,
        checksum_path: Path,
        now: datetime | None = None,
    ) -> ManifestRecord:
        """Create one source record or return the identical existing plan."""
        document = self.load()
        existing = document.records.get(source_url)
        expected_metadata = (
            checksum_url,
            str(Path(archive_path)),
            str(Path(checksum_path)),
        )
        if existing is not None:
            observed_metadata = (
                existing.checksum_url,
                existing.archive_path,
                existing.checksum_path,
            )
            if observed_metadata != expected_metadata:
                raise ManifestConflictError(
                    f"source {source_url} is already planned with different paths or checksum URL"
                )
            return existing

        occurred_at = _now_utc(now)
        record = ManifestRecord(
            source_url=source_url,
            checksum_url=checksum_url,
            archive_path=expected_metadata[1],
            checksum_path=expected_metadata[2],
            status=ManifestStatus.PLANNED,
            updated_at=occurred_at,
            history=(
                ManifestEvent(
                    status=ManifestStatus.PLANNED,
                    occurred_at=occurred_at,
                    detail="source ingestion planned",
                ),
            ),
        )
        return self._publish_record(document, record)

    def begin_attempt(self, source_url: str, *, now: datetime | None = None) -> ManifestRecord:
        """Start or restart acquisition and increment the pipeline attempt count."""
        record, document = self._get(source_url)
        allowed = {
            ManifestStatus.PLANNED,
            ManifestStatus.DOWNLOADING,
            ManifestStatus.FAILED,
            ManifestStatus.PROCESSED,
        }
        if record.status not in allowed:
            self._invalid(record.status, ManifestStatus.DOWNLOADING)
        return self._transition(
            document,
            record,
            status=ManifestStatus.DOWNLOADING,
            detail="ingestion attempt started",
            now=now,
            attempts=record.attempts + 1,
            bytes_written=None,
            expected_sha256=None,
            calculated_sha256=None,
            rows_processed=None,
            last_error=None,
        )

    def mark_downloaded(
        self,
        source_url: str,
        *,
        bytes_written: int,
        now: datetime | None = None,
    ) -> ManifestRecord:
        """Record that a complete bounded archive response was published."""
        if bytes_written <= 0:
            raise ValueError("bytes_written must be positive")
        record, document = self._require(
            source_url,
            required=ManifestStatus.DOWNLOADING,
            target=ManifestStatus.DOWNLOADED,
        )
        return self._transition(
            document,
            record,
            status=ManifestStatus.DOWNLOADED,
            detail=f"downloaded {bytes_written} archive bytes",
            now=now,
            bytes_written=bytes_written,
        )

    def mark_verified(
        self,
        source_url: str,
        *,
        expected_sha256: str,
        calculated_sha256: str,
        now: datetime | None = None,
    ) -> ManifestRecord:
        """Record successful source-integrity comparison."""
        expected = expected_sha256.lower()
        calculated = calculated_sha256.lower()
        if expected != calculated:
            raise ValueError("verified checksums must match")
        if len(expected) != 64 or any(
            character not in "0123456789abcdef" for character in expected
        ):
            raise ValueError("verified checksum must be 64 lowercase hexadecimal characters")
        record, document = self._require(
            source_url,
            required=ManifestStatus.DOWNLOADED,
            target=ManifestStatus.VERIFIED,
        )
        return self._transition(
            document,
            record,
            status=ManifestStatus.VERIFIED,
            detail="published and calculated SHA-256 matched",
            now=now,
            expected_sha256=expected,
            calculated_sha256=calculated,
        )

    def mark_processing(
        self,
        source_url: str,
        *,
        now: datetime | None = None,
    ) -> ManifestRecord:
        """Record parsing start or restart from a verified checkpoint."""
        record, document = self._get(source_url)
        if record.status not in {ManifestStatus.VERIFIED, ManifestStatus.PROCESSING}:
            self._invalid(record.status, ManifestStatus.PROCESSING)
        return self._transition(
            document,
            record,
            status=ManifestStatus.PROCESSING,
            detail="verified archive processing started",
            now=now,
            rows_processed=None,
            last_error=None,
        )

    def mark_processed(
        self,
        source_url: str,
        *,
        rows_processed: int,
        now: datetime | None = None,
    ) -> ManifestRecord:
        """Record successful completion and its accepted row count."""
        if rows_processed <= 0:
            raise ValueError("rows_processed must be positive")
        record, document = self._require(
            source_url,
            required=ManifestStatus.PROCESSING,
            target=ManifestStatus.PROCESSED,
        )
        return self._transition(
            document,
            record,
            status=ManifestStatus.PROCESSED,
            detail=f"processed {rows_processed} validated rows",
            now=now,
            rows_processed=rows_processed,
            last_error=None,
        )

    def mark_failed(
        self,
        source_url: str,
        *,
        error: str,
        now: datetime | None = None,
    ) -> ManifestRecord:
        """Persist a diagnosed failure without deleting earlier event evidence."""
        detail = error.strip()
        if not detail:
            raise ValueError("error must not be empty")
        record, document = self._get(source_url)
        if record.status in {ManifestStatus.PLANNED, ManifestStatus.PROCESSED}:
            self._invalid(record.status, ManifestStatus.FAILED)
        return self._transition(
            document,
            record,
            status=ManifestStatus.FAILED,
            detail="ingestion failed",
            now=now,
            last_error=detail[:1000],
        )

    def _get(self, source_url: str) -> tuple[ManifestRecord, ManifestDocument]:
        document = self.load()
        record = document.records.get(source_url)
        if record is None:
            raise ManifestConflictError(f"source {source_url} has not been planned")
        return record, document

    def _require(
        self,
        source_url: str,
        *,
        required: ManifestStatus,
        target: ManifestStatus,
    ) -> tuple[ManifestRecord, ManifestDocument]:
        record, document = self._get(source_url)
        if record.status is not required:
            self._invalid(record.status, target)
        return record, document

    @staticmethod
    def _invalid(current: ManifestStatus, target: ManifestStatus) -> None:
        raise InvalidManifestTransition(
            f"cannot transition manifest from {current.value} to {target.value}"
        )

    def _transition(
        self,
        document: ManifestDocument,
        record: ManifestRecord,
        *,
        status: ManifestStatus,
        detail: str,
        now: datetime | None,
        **updates: object,
    ) -> ManifestRecord:
        occurred_at = _now_utc(now)
        event = ManifestEvent(status=status, occurred_at=occurred_at, detail=detail)
        values = record.model_dump()
        values.update(
            {
                **updates,
                "status": status,
                "updated_at": occurred_at,
                "history": (*record.history, event),
            }
        )
        updated = ManifestRecord.model_validate(values)
        return self._publish_record(document, updated)

    def _publish_record(
        self,
        document: ManifestDocument,
        record: ManifestRecord,
    ) -> ManifestRecord:
        records = dict(document.records)
        records[record.source_url] = record
        updated = ManifestDocument(
            revision=document.revision + 1,
            records=records,
        )
        self._save(updated)
        return record

    def _save(self, document: ManifestDocument) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        payload = json.dumps(
            document.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
        )
        try:
            with temporary_path.open("x", encoding="utf-8", newline="\n") as target:
                target.write(f"{payload}\n")
                target.flush()
                os.fsync(target.fileno())
            temporary_path.replace(self.path)
        except OSError as exc:
            raise ManifestWriteError(f"could not publish manifest {self.path}: {exc}") from exc
        finally:
            temporary_path.unlink(missing_ok=True)


__all__ = [
    "MAX_MANIFEST_BYTES",
    "InvalidManifestTransition",
    "ManifestConflictError",
    "ManifestDocument",
    "ManifestError",
    "ManifestEvent",
    "ManifestReadError",
    "ManifestRecord",
    "ManifestStatus",
    "ManifestStore",
    "ManifestWriteError",
]
