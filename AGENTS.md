# Agent Development Guide

This file contains architectural context and conventions for AI agents (and humans) working on the TapeHoard codebase.

## Project Structure

```
tapehoard/
├── backend/           # FastAPI + SQLAlchemy + SQLite
│   ├── app/
│   │   ├── api/       # API routers
│   │   │   ├── common.py          # Shared helpers & schemas
│   │   │   ├── system/            # System endpoints (13 modules)
│   │   │   ├── archive.py         # Archive file index endpoints
│   │   │   ├── backups.py         # Backup job endpoints
│   │   │   ├── inventory.py       # Media fleet endpoints
│   │   │   ├── restores.py        # Restore queue endpoints
│   │   │   └── schemas.py         # Shared Pydantic schemas
│   │   ├── db/
│   │   ├── services/  # Business logic (scanner, archiver, scheduler)
│   │   └── main.py    # FastAPI app factory + router registration
│   └── tests/         # Pytest suite (77 tests)
├── frontend/          # SvelteKit + TypeScript
│   ├── src/lib/api/   # Auto-generated OpenAPI SDK
│   └── tests/         # Playwright E2E suite (34 tests)
└── docs/              # Additional documentation
```

## Backend Architecture

### API Router Organization

All API routes live under `app/api/`. The `system` endpoints are split into a package (`app/api/system/`) with focused submodules:

| Module | Endpoints |
|--------|-----------|
| `system/jobs.py` | `/system/jobs/*`, `/system/jobs/{id}/cancel`, `/system/jobs/{id}/retry`, `/system/jobs/stream` |
| `system/scan.py` | `/system/scan`, `/system/index/hash`, `/system/scan/status` |
| `system/filesystem.py` | `/system/browse`, `/system/search` |
| `system/tree.py` | `/system/tree` |
| `system/dashboard.py` | `/system/dashboard/stats` |
| `system/settings.py` | `/system/settings` |
| `system/hardware.py` | `/system/hardware/discover`, `/system/hardware/ignore` |
| `system/discrepancies.py` | `/system/discrepancies/*`, batch ops, tree, browse |
| `system/database.py` | `/system/database/export`, `/system/database/import` |
| `system/tracking.py` | `/system/track/batch` |
| `system/notifications.py` | `/system/notifications/test` |
| `system/host.py` | `/system/ls` |
| `system/test.py` | `/system/test/reset` |

Each module defines its own `APIRouter` with `tags=["System"]` and is registered in `main.py` with `prefix="/system"`.

### Index-Only Principle

**Never rely on the live filesystem for data, except during a scan.** All read endpoints must operate exclusively on the database index. The filesystem is only accessed during:

- **Scan operations** (`/system/scan`) — to discover files, compute hashes, and sync the index.
- **Configuration endpoints** (`/system/ls`, `/system/browse` when path is outside roots) — to help users pick source roots during setup.

Browsing the archive, searching, or checking protection status must use the index only. This guarantees consistent results even when files are temporarily inaccessible, and prevents I/O bottlenecks on network or tape-backed storage.

### Shared Helpers (`app/api/common.py`)

Cross-cutting helpers and schemas that must not create circular imports:

- `get_source_roots(db_session)` → `List[str]`
- `get_exclusion_spec(db_session)` → `Optional[pathspec.PathSpec]`
- `get_ignored_status(path, tracking_map, exclusion_spec)` → `bool`
- `_validate_path_within_roots(path, roots)` → `bool`
- `_active_job_exists(db_session, job_type)` → `bool`
- `_get_last_scan_time(db_session)` → `Optional[datetime]`
- Shared Pydantic schemas: `DashboardStatsSchema`, `JobSchema`, `JobLogSchema`, `FileItemSchema`, `BrowseResponseSchema`, `ScanStatusSchema`, `SettingSchema`, `TestNotificationRequest`, `IgnoreHardwareRequest`, `BatchTrackRequest`

**Rule:** `common.py` must NEVER import from any API module (no `app.api.system`, `app.api.archive`, etc.). Only models, database, and standard libraries.

### Endpoint Naming Convention

All FastAPI route handlers must declare explicit `operation_id` to control the generated TypeScript SDK names.

| Pattern | Example Handler | `operation_id` | Generated TS |
|---------|-----------------|----------------|--------------|
| GET list | `list_jobs` | `list_jobs` | `listJobs` |
| GET one | `get_job` | `get_job` | `getJob` |
| POST create | `create_media` | `create_media` | `createMedia` |
| POST action | `trigger_scan` | `trigger_scan` | `triggerScan` |
| PATCH update | `update_media` | `update_media` | `updateMedia` |
| DELETE | `delete_media` | `delete_media` | `deleteMedia` |
| Batch actions | `batch_track` | `batch_track` | `batchTrack` |

**Never** let FastAPI auto-generate `operationId`. The old auto-generated names looked like `getDashboardStatsSystemDashboardStatsGet` — verbose and brittle.

### Router Prefix Rules

- Top-level domain routers (`archive`, `backups`, `inventory`, `restores`) define their own prefix in the router constructor (e.g., `APIRouter(prefix="/archive")`).
- `system` submodules use **no prefix** in the router constructor; `main.py` applies `prefix="/system"` when calling `app.include_router()`.

## Frontend Architecture

### TypeScript SDK (`frontend/src/lib/api/`)

Generated from the backend OpenAPI spec using `@hey-api/openapi-ts`:

```bash
just generate-client
```

This runs the full pipeline: exports the OpenAPI spec from the running FastAPI app and regenerates the TypeScript SDK in `frontend/src/lib/api/`. Use this **after any backend change** that adds, renames, or modifies endpoints or schemas.

The generated SDK exports clean camelCase functions (e.g., `getDashboardStats`, `listJobs`, `triggerScan`).

**Rule:** After renaming any backend handler or changing an `operation_id`, regenerate the SDK and update all frontend imports. The old verbose names will cause TypeScript errors.

### Frontend Imports to Avoid Shadowing

Some Svelte components define local functions with the same name as SDK imports (e.g., `cancelJob`, `retryJob` in `jobs/+page.svelte`). When this happens, alias the SDK import:

```typescript
import { cancelJob as cancelJobApi, retryJob as retryJobApi } from '$lib/api';
```

## Testing

### Backend Tests

```bash
cd backend && uv run pytest tests/ -v
```

- 230 tests covering API endpoints, providers, services
- Uses pytest-mock for mocking filesystem/hardware
- **Important:** Mocks that patch `get_source_roots` or `get_exclusion_spec` must target `app.api.common` (not `app.api.system`), since those helpers moved to `common.py`.

### Frontend E2E Tests

```bash
cd frontend && npx playwright test
```

- 34 Playwright tests using Chromium
- Backend test server auto-starts via `playwright.config.ts` webServer config
- Tests use `requestContext` for direct API calls + `page` for UI interactions

### macOS IPv6 Gotcha

On macOS, `localhost` resolves to `::1` (IPv6) by default, but uvicorn may bind to IPv4 only. This causes `ECONNREFUSED ::1:8001` in Playwright tests.

**Fix:** Always use `127.0.0.1` instead of `localhost` for backend URLs:
- `frontend/tests/helpers.ts`: `API_URL = 'http://127.0.0.1:8001'`
- `frontend/playwright.config.ts`: `webServer.url = 'http://127.0.0.1:8001'`

## Tape Archive Correctness

### Buffer Flush Timeouts

LTO tape drives have large internal buffers (hundreds of MB). After a `dd` or `tarfile` write finishes, the drive may still be flushing data to tape for **up to 15 minutes**. Closing `/dev/nst0` triggers the driver to write the file mark, but if the buffer is still draining, the close may block.

**Old:** Explicit `weof` was used, which failed with "Device or resource busy" when the buffer was still flushing.

**Fix:** Removed explicit `weof` — the Linux SCSI tape driver writes the file mark automatically when the device is closed after writing. The close operation blocks until the buffer is fully flushed, which is the correct behavior. The user can cancel the backup job if the drive never clears.

An INFO log `"Waiting for tape drive to be available..."` is emitted once on the first busy error so the logs clearly show the job is intentionally paused.

### `bytes_used` Fallback Trap

The archiver syncs `bytes_used` to hardware-reported utilization via `_update_bytes_used_from_hardware()`. The old code checked success by comparing `bytes_used == old_bytes_used`, which is broken because it can't distinguish:

1. Hardware reported `0.0` utilization (empty tape) → should **NOT** fallback
2. Hardware returned `None` (unavailable) → **should** fallback to uncompressed size

**Fix:** `_update_bytes_used_from_hardware()` now returns `bool`. The caller uses `if not hw_updated:` instead of `if bytes_used == old_bytes_used:`.

### Restore Archive Sort Order

Tape restores read archives in the order returned by `sorted(archive_groups.keys())`. With string sort, file numbers order as `"1", "10", "11", "12", "2"...` which causes the tape to seek back and forth (catastrophic shoe-shining).

**Fix:** `run_restore` uses a `_archive_sort_key` helper that tries `int()` conversion first, falling back to string sort for non-numeric IDs (HDD paths, cloud keys). Tape file numbers now read linearly: `1, 2, 3, ..., 10, 11, 12`.

### Streaming Path File Number Bug

`finalize_stream` was calling `_get_current_file_number()` **after** `weof`. Since `weof` advances the tape to the next file, this returned the **next** file number instead of the current archive's number. Restores would seek past the archive to an empty file.

**Fix:** Capture the file number **before** closing the stream (the driver writes the file mark automatically on close). Also ensure the Python stream is fully flushed/closed before `finalize_stream` is called.

### File Stability Filter

Files actively modified during a backup can be partially read and archived in an inconsistent state. The archiver now captures `job_start_time` at the beginning of `run_backup` and checks each file's actual filesystem `mtime` before writing.

- `mtime > job_start_time` → skipped with log `"Skipped (actively modified after job start): /path/to/file"`
- File missing between scan and backup → skipped with log `"Skipped (missing): /path/to/file"`

This filter runs after deduplication but before all write paths (random access, streaming tar, staging tar, binary tar).

### `prepare_for_write` Positioning

`prepare_for_write` was calling `identify_media()` without `allow_intrusive=False`, which could rewind a partially-used tape back to BOT even though the archiver had already verified identity two lines above.

**Fix:** `prepare_for_write` now passes `allow_intrusive=False` to avoid unnecessary wear. If the cache is stale, `eod` still recovers to the end of data.

### LTO Capacity Auto-Detection

During media registration, `_detect_lto_capacity_from_hardware()` queries MAM attribute `max_capacity_mib` to determine the actual physical capacity. This overrides generic LTO defaults (e.g., 1415 GB actual vs 1500 GB marketed). The backend always trusts hardware when `device_path` is provided.

**Frontend:** The register dialog pre-fills capacity with `Math.floor(max_capacity_mib * 1024 * 1024 / 1e9)` to avoid rounding up past physical capacity.

### Per-Chunk Checkpointing

`run_backup` previously committed once at job end. If a long-running tape backup failed mid-way, all already-written archives were orphaned in the database.

**Fix:** `db_session.commit()` is called after each deduplicated chunk, each random-access chunk, and each sequential tar archive. This ensures `FileVersion` records are persisted incrementally.

### File Marks Between Archives

The Linux SCSI tape driver (`st`) **automatically writes a file mark when `/dev/nst0` is closed after writing**. Explicit `weof` commands are redundant and create **double file marks**, which produces empty files between archives and breaks restore seeks.

**Old (buggy):** `write_archive` and `finalize_stream` both called explicit `weof` after `dd`/`close()`, creating two file marks per archive. 56 archives produced 113 files on tape instead of 57.

**Fix:** Removed all explicit `weof` calls from `initialize_media`, `write_archive`, and `finalize_stream`. The driver writes the file mark automatically when the device is closed. The tape layout is:

```
[File 0: Label][FM][File 1: Archive 1][FM][File 2: Archive 2][FM]...
```

### Frontend Polling for `bytes_used`

The inventory page polls `discoverHardware()` every 3 seconds for live status, but `bytes_used` (which comes from the DB, not hardware MAM) only refreshes when `listMedia` is called. After a backup job completes, the hardware status card shows updated MAM utilization while the media table still shows stale `bytes_used`.

**Fix:** The `POLL_SLOW` interval also calls `loadMedia(true, false)` (silent, no hardware refresh) to keep the DB-derived utilization current.

## Common Tasks

### Adding a New System Endpoint

1. Choose the appropriate `app/api/system/<module>.py` file (or create a new one if it doesn't fit existing categories).
2. Add the route handler with an explicit `operation_id`.
3. Import shared helpers from `app.api.common` if needed.
4. Register the new router in `app/main.py` with `prefix="/system"`.
5. Regenerate the TypeScript SDK.
6. Update frontend imports if using the new endpoint.
7. Add backend tests in `backend/tests/test_api_system.py` (or a new test file if it's a new domain).
8. Run `just lint` before finishing.

### Regenerating the OpenAPI Spec / TypeScript SDK

Use the convenience command:

```bash
just generate-client
```

Or run the steps manually:

```bash
cd backend && uv run python -c "import json; from app.main import app; json.dump(app.openapi(), open('openapi.json', 'w'), indent=2)"
cd ../frontend && npx @hey-api/openapi-ts -i ../backend/openapi.json -o src/lib/api
```

### Verifying No Auto-Generated operationIds

```bash
cd backend && uv run python -c "
from app.main import app
import re
for path, methods in app.openapi()['paths'].items():
    for method, info in methods.items():
        op_id = info.get('operationId', '')
        if re.search(r'_(get|post|put|patch|delete)$', op_id):
            print(f'DIRTY: {method.upper()} {path} = {op_id}')
print('Check complete')
"
```

## Lint & Format

```bash
just lint       # Runs ruff (Python) + svelte-check (TypeScript/Svelte)
```

Pre-commit hooks are configured but may stash unstaged changes.

## Environment

- **Backend:** Python 3.13, FastAPI, SQLAlchemy 2.x, SQLite, uv for package management
- **Frontend:** SvelteKit, TypeScript, Tailwind CSS, shadcn-svelte components
- **Test server:** `TAPEHOARD_TEST_MODE=true` enables `/system/test/reset` and mock providers

## Documentation Files

| File | Contents |
|------|----------|
| `README.md` | Human-facing project overview |
| `AGENTS.md` | This file — agent development guide |

## Critical Context for Tape Operations

### `_run_mt` Retry Strategy

Never use `max_retries` (count-based) for tape commands that follow large writes. Use `timeout_seconds` (time-based) instead, because the required wait depends on buffer size, not attempt count.

- Exponential backoff: `0.2 * (2 ** attempt)` seconds
- Cap per attempt: **15 seconds**
- Total timeout for tape commands after writes: **900 seconds** (15 minutes)
- Log pattern: one INFO `"Waiting for tape drive..."` then WARNING per retry

### Streaming vs Staging Tape Writes

The archiver supports two tape write paths, selected by the `tape_write_strategy` system setting:

| Mode | How it works | When to use |
|------|-------------|-------------|
| `stage` (default) | Builds tar on disk, then `dd` to tape | Safe, works with any source disk speed |
| `stream` | `tarfile` writes directly to `/dev/nst0` | Faster, but requires source disk that can sustain tape's minimum streaming speed |

The streaming path uses `open("/dev/nst0", "wb", buffering=256*1024)` for LTO-optimal block size. The caller must close the stream before `finalize_stream()` is called.

### Tape File Number Lifecycle

- File 0: Label (written by `initialize_media`)
- File 1+: Archives (written by `write_archive` or `finalize_stream`)
- Each archive is followed by a file mark (written automatically when the device is closed)
- `finalize_stream` reads the file number **after** close, subtracts 1
- `write_archive` reads the file number **after** `dd` exits, subtracts 1

### Hardware Utilization Sync

`bytes_used` on `StorageMedia` is DB-derived, not live hardware. It is updated:
- During backup: via `_update_bytes_used_from_hardware()` after each chunk
- Via frontend polling: `loadMedia(true, false)` on `POLL_SLOW` interval
- Never during restore or idle periods (to avoid unnecessary MAM reads)

### Testing Tape-Related Code

When mocking `_run_mt` or `subprocess.run` in tests:
- Simulate busy errors by raising `subprocess.CalledProcessError(1, cmd, stderr=b"...busy...")`
- Mock `time.time` with an iterator when testing long timeouts, or tests will hang or run out of mock values
- `test_provider_tape.py` has examples of both success (`busy_then_ok`) and timeout (`always_busy`) mocks
