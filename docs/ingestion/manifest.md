# Restartable ingestion manifest

The local manifest is a small JSON control file that answers three operational
questions: what source was planned, how far ingestion safely reached, and why a
run stopped. It is not the downloaded market data itself.

For the learning sample it lives at
`data/samples/ingestion-manifest.json`. The entire `data/` directory is ignored
by Git because the manifest describes a particular machine's local runs.

## Why a manifest exists

A process can stop after downloading a file but before parsing it. Without
durable state, the next process cannot distinguish that case from a run that
never started. The manifest publishes a new revision after each trustworthy
checkpoint, so the next invocation can make an explicit recovery decision.

Each source URL is the stable record key. Its immutable plan also stores the
checksum URL and local archive/checksum paths. Replanning that URL with different
metadata raises a conflict instead of silently changing history.

## State machine

| Status | Evidence now available | Normal next status |
| --- | --- | --- |
| `planned` | Source URL and destination paths | `downloading` |
| `downloading` | An attempt number has been allocated | `downloaded` or `failed` |
| `downloaded` | A complete bounded archive exists and its byte count is known | `verified` or `failed` |
| `verified` | Published and calculated SHA-256 values match | `processing` |
| `processing` | Parsing began from a verified archive | `processed` or `failed` |
| `processed` | Validated rows and final row count exist | Revalidate in place, or start a forced attempt |
| `failed` | The diagnosis and earlier event history remain visible | New `downloading` attempt |

Invalid jumps fail loudly. For example, `downloaded` cannot jump straight to
`processed`, because that would omit checksum and parsing evidence.

## Restart decisions

`uv run marketpulse fetch-sample --limit 5` follows these rules:

1. A missing manifest creates `planned`, starts attempt 1, and advances through
   every checkpoint.
2. `downloading` or `failed` starts a new numbered attempt. A complete bounded
   cached pair may be adopted only after checksum verification.
3. `downloaded` rechecks the archive/checksum pair and continues at `verified`.
4. `verified` or `processing` reuses the recorded calculated checksum, verifies
   the archive again during parsing, and continues at `processing`.
5. `processed` revalidates and parses the cache without changing the revision or
   attempt count. This makes an ordinary rerun observable but idempotent in its
   control history.
6. `--force` always starts a new attempt and downloads fresh candidate files.

The command reports the final manifest path, status, and attempt count. A
successful first run ends with output similar to:

```text
Manifest: data\samples\ingestion-manifest.json
Manifest status: processed (attempts: 1)
```

## Failure and integrity behavior

Download, checksum, ZIP, CSV, and contract failures move an active record to
`failed` and retain a bounded error message. A later run increments `attempts`
and keeps the complete event history instead of erasing the failed attempt.

A completed record is not blindly trusted. If its cached archive is later
modified, the next run detects the SHA-256 mismatch and records `failed` before
any row is accepted. The manifest supplements checksum validation; it never
replaces it.

## Atomic persistence

Each revision is serialized to a uniquely named temporary file in the same
directory. The writer flushes the content to disk and then atomically replaces
the public manifest path. Readers therefore see either the previous complete
revision or the next complete revision, not a half-written JSON document.

The reader rejects invalid UTF-8, malformed JSON, unsupported schemas, invalid
records, and files above 5 MiB. These boundaries turn corrupted control state
into a diagnosed failure instead of an unsafe guess.

## Current limit

The Day 10 store supports one local pipeline process at a time. Atomic replace
prevents partial files, but it is not cross-process locking: two writers could
both read the same revision and overwrite one another. Kestra concurrency
controls and database-backed audit records are scheduled later in the roadmap.
