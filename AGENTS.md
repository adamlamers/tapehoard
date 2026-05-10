# Agent Development Guide

## Project Structure

```
tapehoard/
├── backend/           # FastAPI + SQLAlchemy + SQLite
│   ├── app/
│   │   ├── api/
│   │   │   ├── common.py          # Shared helpers & schemas
│   │   │   ├── system/            # System endpoints (13 modules)
│   │   │   ├── archive.py         # Archive file index
│   │   │   ├── backups.py         # Backup jobs
│   │   │   ├── inventory.py       # Media fleet
│   │   │   ├── restores.py        # Restore queue
│   │   │   └── schemas.py         # Shared Pydantic schemas
│   │   ├── db/
│   │   ├── services/              # scanner, archiver, scheduler
│   │   └── main.py                # App factory + router registration
│   └── tests/                     # 230 pytest tests
├── frontend/          # SvelteKit + TypeScript
│   ├── src/lib/api/   # Auto-generated OpenAPI SDK
│   └── tests/         # 34 Playwright tests
└── docs/
```

## Backend

### API Router Organization

System endpoints live in `app/api/system/` submodules and are registered in `main.py` with `prefix="/system"`.

| Module | Endpoints |
|--------|-----------|
| `system/jobs.py` | `/system/jobs/*`, cancel, retry, stream |
| `system/scan.py` | `/system/scan`, `/system/scan/stream`, `/system/index/hash`, `/system/scan/status` |
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

Each module defines its own `APIRouter` with `tags=["System"]` and **no prefix** in the constructor; `main.py` applies `prefix="/system"`.

Top-level domain routers (`archive`, `backups`, `inventory`, `restores`) define their own prefix (e.g., `APIRouter(prefix="/archive")`).

### Index-Only Principle

**Never read the live filesystem except during scan.** All read endpoints must use the database index only.

Filesystem access is allowed only for:
- **Scan** (`/system/scan`) — discover files, compute hashes, sync index
- **Config helpers** (`/system/ls`, `/system/browse` for paths outside roots) — help users pick source roots

Archive browse, search, and protection checks must use the index exclusively.

### Shared Helpers (`app/api/common.py`)

Available helpers (must not import any API module to avoid circular deps):
- `get_source_roots(db_session)` → `List[str]`
- `get_exclusion_spec(db_session)` → `Optional[pathspec.PathSpec]`
- `get_ignored_status(path, tracking_map, exclusion_spec)` → `bool`
- `_validate_path_within_roots(path, roots)` → `bool`
- `_active_job_exists(db_session, job_type)` → `bool`
- `_get_last_scan_time(db_session)` → `Optional[datetime]`

Shared schemas: `DashboardStatsSchema`, `JobSchema`, `JobLogSchema`, `FileItemSchema`, `BrowseResponseSchema`, `ScanStatusSchema`, `SettingSchema`, `TestNotificationRequest`, `IgnoreHardwareRequest`, `BatchTrackRequest`

### Endpoint Naming Convention

Always declare explicit `operation_id`. Never let FastAPI auto-generate it.

| Pattern | Handler | `operation_id` | Generated TS |
|---------|---------|----------------|--------------|
| GET list | `list_jobs` | `list_jobs` | `listJobs` |
| GET one | `get_job` | `get_job` | `getJob` |
| POST create | `create_media` | `create_media` | `createMedia` |
| POST action | `trigger_scan` | `trigger_scan` | `triggerScan` |
| PATCH update | `update_media` | `update_media` | `updateMedia` |
| DELETE | `delete_media` | `delete_media` | `deleteMedia` |
| Batch | `batch_track` | `batch_track` | `batchTrack` |

## Frontend

### TypeScript SDK

Regenerate OpenAPI typescript client after any backend endpoint/schema change:
```bash
just generate-client
```

The generated SDK exports camelCase functions (e.g., `getDashboardStats`, `listJobs`). After renaming handlers or `operation_id`, regenerate the SDK and update all frontend imports.

### Import Shadowing

If a Svelte component defines a local function with the same name as an SDK import, alias it:
```typescript
import { cancelJob as cancelJobApi, retryJob as retryJobApi } from '$lib/api';
```

## Testing

### Backend
```bash
cd backend && uv run pytest tests/ -v
```
- 252 tests; uses pytest-mock for filesystem/hardware mocking
- **Important:** Mocks patching `get_source_roots` or `get_exclusion_spec` must target `app.api.common` (not `app.api.system`)

### Frontend E2E
```bash
cd frontend && npx playwright test
```
- 44 Playwright tests using Chromium
- Backend test server auto-starts via `playwright.config.ts`
- Tests use `requestContext` for API calls + `page` for UI

### Playwright: Wait on a Specific Job, Not All Jobs

When a test triggers multiple backup jobs sequentially, using `jobs.find(j => j.job_type === 'BACKUP')` returns the first match — which may be an already-completed earlier job, producing a false-positive. Always extract the `job_id` from the trigger response and poll it directly:

```typescript
const resp = await requestContext.post(`${API_URL}/backups/trigger/${mediaId}`);
const { job_id } = await resp.json();

await expect(async () => {
  const jobResp = await requestContext.get(`${API_URL}/system/jobs/${job_id}`);
  expect((await jobResp.json()).status).toBe('COMPLETED');
}).toPass({ timeout: 30000 });
```

### macOS IPv6
On macOS, `localhost` resolves to `::1`, but uvicorn binds to IPv4, causing `ECONNREFUSED ::1:8001`.

**Fix:** Use `127.0.0.1` everywhere:
- `frontend/tests/helpers.ts`: `API_URL = 'http://127.0.0.1:8001'`
- `frontend/playwright.config.ts`: `webServer.url = 'http://127.0.0.1:8001'`

## Tape Archive Correctness

### Buffer Flush Timeouts
LTO drives buffer hundreds of MB. After `dd` or `tarfile` write, the drive may flush for **up to 15 minutes**. Closing `/dev/nst0` blocks until flush completes.

**Fix:** Removed explicit `weof`. The Linux SCSI tape driver (`st`) writes the file mark automatically on close. The user can cancel the job if the drive never clears.

Log pattern: one INFO `"Waiting for tape drive to be available..."` on first busy error, then WARNING per retry.

### `bytes_used` Fallback
`_update_bytes_used_from_hardware()` returns `bool`. The caller uses `if not hw_updated:` to decide whether to fallback to uncompressed size. Old code compared `bytes_used == old_bytes_used`, which falsely fell back when hardware reported `0.0` (empty tape).

### Restore Archive Sort
Tape restores read archives in `sorted(archive_groups.keys())`. String sort orders as `"1", "10", "11", "2"...`, causing catastrophic shoe-shining.

**Fix:** `_archive_sort_key` tries `int()` first, falling back to string for non-numeric IDs (HDD paths, cloud keys).

### Selective Restore from Tape
**Problem:** Old code used `dd` to read the entire archive into a pipe, then iterated through ALL tar members to find selected files. This was inefficient and extracted everything.

**Fix:**
1. `read_archive()` now opens the tape device directly (`open(device_path, "rb")`) instead of using `dd`
2. `run_restore()` creates a `normalized_map` of target files and tracks `remaining_files`
3. Iterates through tar members sequentially, extracting only matching files
4. **Stops early** once all target files are found: `if not remaining_files: break`
5. Properly handles symlinks, directories, and regular files with full metadata restoration
6. Ensures bitstream is closed in `finally` block to release the tape device

This avoids reading the entire tar when only a subset of files are needed.

### Streaming File Number Bug
`finalize_stream` used to call `_get_current_file_number()` **after** `weof`. Since `weof` advances to the next file, this returned the **next** file number. Restores would seek past the archive.

**Fix:** Capture file number **before** close. The driver writes the file mark automatically on close.

### File Stability Filter
Archiver captures `job_start_time` and skips files where `mtime > job_start_time` or the file is missing. Runs after deduplication, before all write paths.

Logs:
- `"Skipped (actively modified after job start): /path/to/file"`
- `"Skipped (missing): /path/to/file"`

### `prepare_for_write` Positioning
Old code called `identify_media()` without `allow_intrusive=False`, which could rewind a partially-used tape to BOT.

**Fix:** Pass `allow_intrusive=False`. If the cache is stale, `eod` recovers to EOD.

### LTO Capacity Auto-Detection
Media registration queries MAM `max_capacity_mib` to override generic LTO defaults. Backend trusts hardware when `device_path` is provided.

Frontend pre-fills with `Math.floor(max_capacity_mib * 1024 * 1024 / 1e9)` to avoid rounding up past physical capacity.

### Per-Chunk Checkpointing
Old code committed once at job end. Mid-failures orphaned already-written archives.

**Fix:** `db_session.commit()` after each deduplicated chunk, random-access chunk, and sequential tar archive.

### File Marks Between Archives
The `st` driver **automatically writes a file mark when `/dev/nst0` is closed after writing**. Explicit `weof` creates double file marks, producing empty files and breaking restore seeks.

**Fix:** Removed all explicit `weof` from `initialize_media`, `write_archive`, and `finalize_stream`.

Tape layout:
```
[File 0: Label][FM][File 1: Archive 1][FM][File 2: Archive 2][FM]...
```

### Frontend Polling for `bytes_used`
`discoverHardware()` polls every 3s, but `bytes_used` is DB-derived and only updates on `listMedia`.

**Fix:** The `POLL_SLOW` interval also calls `loadMedia(true, false)` (silent, no hardware refresh).

### Empty Tar Detection
If all files in a chunk are deleted between stability filter and `_build_tar`, the resulting tar has 0 members, producing an empty tape file.

**Fix:** `_build_tar` tracks `members_added`. Logs WARNING when 0.

### Capacity Sanity Check
If `capacity` is stored in GB, `MAX_CHUNK_SIZE = capacity // 50` becomes ~20MB, creating thousands of tiny tape files.

**Fix:** Abort if `MAX_CHUNK_SIZE < 1MB`:
```
Media capacity (1000000000) produces MAX_CHUNK_SIZE of 10485760 bytes.
This looks like capacity is stored in GB instead of bytes.
```
Re-register media with capacity in bytes.

### Checkpoint Logs
Job logs include the tape file number for each committed archive:
```
Checkpoint: archive 3 committed (tape file #7)
```

### SSE Endpoints

| Endpoint | Emits | Frontend Consumers |
|----------|-------|-------------------|
| `GET /system/jobs/stream` | Active jobs array every 2s | `JobDetailModal.svelte` |
| `GET /system/scan/stream` | Scan metrics every 1s | `ScanStatusOverlay.svelte`, `+page.svelte`, `filesystem/+page.svelte` |

Use native `EventSource` (not the SDK helper):
```typescript
const eventSource = new EventSource(`${apiUrl}/system/jobs/stream`);
eventSource.onmessage = (event) => { const data = JSON.parse(event.data); };
// Close on destroy to prevent leaks
eventSource.close();
```

**SSE vs polling:**
- **SSE:** Active modals, scan overlays — sub-second updates, single visible instance
- **Polling:** Historical lists — survives navigation/refreshes without reconnection flash

### Redundancy Ratio
Based on **data volume**, not file count:
```
redundancy_ratio = (archived_size / eligible_size) * 100
```
- `archived_size` = sum of `FileVersion` byte ranges on active/full media
- `eligible_size` = `total_size - ignored_size` from `filesystem_state`

Note: this ratio reflects first-copy coverage, not redundancy depth. It does not account for the `redundancy_target` setting. See §Redundancy Tracking System for the full picture.

## Redundancy Tracking System

### Data Model

Two additions to the DB schema (migration `c2983e8729c5`):

```sql
-- Denormalized count of distinct media that hold a complete copy of this file
ALTER TABLE filesystem_state ADD COLUMN redundancy_count INTEGER DEFAULT 0;
CREATE INDEX idx_fs_redundancy ON filesystem_state(redundancy_count, is_ignored, is_deleted);

-- One row per (file, media) pair where a complete, non-split copy exists
CREATE TABLE file_media_coverage (
    file_id  INTEGER REFERENCES filesystem_state(id) ON DELETE CASCADE,
    media_id INTEGER REFERENCES storage_media(id) ON DELETE CASCADE,
    PRIMARY KEY (file_id, media_id)
);
```

SQLite triggers keep `redundancy_count` in sync automatically:
- `trg_coverage_insert` — increments on `INSERT INTO file_media_coverage`
- `trg_coverage_delete` — decrements on `DELETE FROM file_media_coverage`

**Never update `redundancy_count` directly.** Insert/delete from `file_media_coverage` and let the triggers do it.

### What Counts as "Coverage"

A row is inserted into `file_media_coverage` only when:
```
offset_start == 0 AND offset_end == filesystem_state.size
```
Split chunks (partial byte ranges) do **not** create coverage rows. `redundancy_count` counts complete, independently restorable copies.

### Two-Phase Batch Assembly (`assemble_backup_batch`)

Phase 1 — first-time backups:
- Selects files where `redundancy_count == 0` (never backed up)
- Uses global covered-bytes tracking to allow splits across multiple archive chunks
- Excludes files already having any `FileVersion` on the target media

Phase 2 — redundant copies:
- Selects files where `0 < redundancy_count < redundancy_target` and no `FileMediaCoverage` row on the target media
- Always starts at `offset_start = 0` (no splits — a redundant copy must be complete)
- Tagged `is_redundant_copy=True` in the batch item

### Dedup Bypass for Redundant Copies

The archiver's deduplication check (`existing_versions.get((hash, start, end))`) is skipped for items with `is_redundant_copy=True`. Without this bypass, the dedup would find the existing `FileVersion` on another media and create a pointer back to it rather than physically writing to the target — the file would never land on the new media and redundancy_count would never increment.

```python
dupe = None
if not item.get("is_redundant_copy"):
    dupe = existing_versions.get((file_state.sha256_hash, item["offset_start"], item["offset_end"]))
```

### Coverage Recording

`_record_coverage(db, items, media_id)` is called after each write batch (random-access, streaming, and staged tar paths all call it). It inserts `OR IGNORE` into `file_media_coverage` for any item where `offset_start == 0 AND offset_end == file.size`. The trigger fires and increments `redundancy_count`.

### Media Status Transitions and Coverage

| Status | Counts Toward Redundancy | Notes |
|--------|-------------------------|-------|
| `active` | ✅ Yes | Online and available for writes |
| `full` | ✅ Yes | Online but at capacity |
| `offline` | ✅ Yes | **Offline media still provides valid backups** - ejected tapes, disconnected HDDs |
| `failed` | ❌ No | Hardware failure, data presumed lost |
| `retired` | ❌ No | Intentionally decommissioned, data deleted |

| Transition | `file_versions` | `file_media_coverage` | Effect on `redundancy_count` |
|------------|----------------|----------------------|------------------------------|
| `→ FAILED` | Deleted | Deleted (trigger fires) | Decremented for all affected files |
| `→ RETIRED` | Deleted | Deleted (trigger fires) | Decremented for all affected files |
| `→ OFFLINE` | Kept | Kept | No change - still counts as valid backup |
| `initialize` (wipe) | Deleted | Deleted (trigger fires) | Decremented for all affected files |
| Delete media record | Deleted | Deleted via `ON DELETE CASCADE` (trigger fires) | Decremented |

**Important:** All queries checking for "valid" or "protected" data must include `status IN ('active', 'full', 'offline')` - excluding only `failed` and `retired`. Offline media (ejected tapes, disconnected drives) still provides protection.

### Test Mode: LTO vs HDD

`TAPEHOARD_TEST_MODE=true` (set by `playwright.config.ts` for the test server):
- **LTO tape** → replaced by `MockLTOProvider` (writes to a temp directory, has `device_path` attr)
- **HDD** → uses the real `OfflineHDDProvider` (writes to the `mount_path` on disk)

Playwright redundancy tests use real HDD media at `/tmp/tapehoard_e2e_hdd_redundancy_{a,b}`.

### `OfflineHDDProvider.device_path`

`OfflineHDDProvider` does **not** have a `device_path` attribute. The `initialize_media` API endpoint uses `getattr(storage_provider, "device_path", None)` with a guard before saving to `extra_config`. Do not add unconditional `storage_provider.device_path` access — it will raise `AttributeError` for HDD media.

## Common Tasks

### Add a New System Endpoint
1. Pick or create `app/api/system/<module>.py`
2. Add handler with explicit `operation_id`
3. Import shared helpers from `app.api.common` if needed
4. Register router in `app/main.py` with `prefix="/system"`
5. Regenerate TypeScript SDK (`just generate-client`)
6. Update frontend imports
7. Add backend tests in `backend/tests/test_api_system.py`
8. Run `just lint`

### Regenerate SDK
```bash
just generate-client
```
Or manually:
```bash
cd backend && uv run python -c "import json; from app.main import app; json.dump(app.openapi(), open('openapi.json', 'w'), indent=2)"
cd ../frontend && npx @hey-api/openapi-ts -i ../backend/openapi.json -o src/lib/api
```

### Verify No Auto-Generated operationIds
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
just lint       # ruff (Python) + svelte-check (TS/Svelte)
```

Pre-commit hooks are configured but may stash unstaged changes.

## Environment

- **Backend:** Python 3.13, FastAPI, SQLAlchemy 2.x, SQLite, uv
- **Frontend:** SvelteKit, TypeScript, Tailwind CSS, shadcn-svelte
- **Test server:** `TAPEHOARD_TEST_MODE=true` enables `/system/test/reset` and mock providers

## Documentation Files

| File | Contents |
|------|----------|
| `README.md` | Human-facing project overview |
| `AGENTS.md` | This file — agent development guide |
| `MULTIPLE_REDUNDANCY.md` | Redundancy feature — what's implemented, what's remaining (restore manifest set cover, dashboard under-protected count, insights query, metadata API) |

## Known Migration Issues

### Migration c2983e8729c5 - Offline Media Coverage

**Bug:** The original migration only backfilled `file_media_coverage` for media with status `'active'` or `'full'`, excluding `'offline'` media.

**Impact:** Files on offline tapes have `redundancy_count = 0` even though valid copies exist. The Archive Browser (after the fix to use `file_media_coverage`) won't show offline media locations.

**Fix:** Run the fix script for existing databases:
```bash
cd backend
uv run python scripts/fix_offline_coverage.py --apply
```

**Migration Updated:** The migration file has been updated to include `'offline'` status for new deployments.

## Critical Context for Tape Operations

### `_run_mt` Retry Strategy
Never use `max_retries` (count-based) for tape commands after large writes. Use `timeout_seconds` (time-based) instead.

- Backoff: `0.2 * (2 ** attempt)` seconds, capped at **15s**
- Total timeout: **900 seconds** (15 minutes)
- Log pattern: one INFO `"Waiting for tape drive..."` then WARNING per retry

### Streaming vs Staging
Selected by `tape_write_strategy` system setting:

| Mode | How | When |
|------|-----|------|
| `stage` (default) | Build tar on disk, then `dd` to tape | Safe, any disk speed |
| `stream` | `tarfile` writes directly to `/dev/nst0` | Faster, requires disk sustaining tape streaming speed |

Streaming uses `open("/dev/nst0", "wb", buffering=256*1024)`. The caller must close the stream before `finalize_stream()`.

### Tape File Number Lifecycle
- File 0: Label
- File 1+: Archives
- Each archive followed by a file mark (driver writes on close)
- **`finalize_stream`:** read file number **after** close, subtract 1
- **`write_archive`:** read file number **after** `dd` exits, subtract 1

**Critical:** Reading `mt status` while `/dev/nst0` is open returns stale data. Always close/wait for `dd` before `_get_current_file_number()`.

### Hardware Utilization Sync
`bytes_used` is DB-derived, not live hardware. Updated:
- During backup: `_update_bytes_used_from_hardware()` after each chunk
- Frontend polling: `loadMedia(true, false)` on `POLL_SLOW`
- Never during restore or idle

### Testing Tape Code
When mocking `_run_mt` or `subprocess.run`:
- Simulate busy: `subprocess.CalledProcessError(1, cmd, stderr=b"...busy...")`
- Mock `time.time` with an iterator for long timeout tests
- See `test_provider_tape.py` for `busy_then_ok` and `always_busy` examples
