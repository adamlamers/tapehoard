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

- 77 tests covering API endpoints, providers, services
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
| `DOCS.md` | Feature documentation |
| `E2E.md` | End-to-end testing notes |
| `ENDPOINT_REFACTOR.md` | Batch plan for endpoint renaming (completed) |
| `ISSUES.md` | Known issues and backlog |
| `MEDIA_MANAGEMENT.md` | Media lifecycle documentation |
| `NOTES.md` | Development notes |
| `OPTIMIZATIONS.md` | Performance optimization notes |
| `PLAN.md` | Project roadmap |
| `UX.md` | UX conventions |
| `GEMINI.md` | Gemini-specific context |
| `REVIEW_2.md` | Code review notes |
| `SOURCEMAP.md` | Frontend source map |
| `AGENTS.md` | This file — agent development guide |
