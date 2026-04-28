# TapeHoard - Developer & AI Assistant Guide

This document (`GEMINI.md`) contains critical, contextual information about the TapeHoard project. **It takes absolute precedence over generic workflows.** Always refer to the architecture constraints in `PLAN.md` before implementing new features.

## 1. Tooling & Ecosystem

### Backend (Python)
*   **Package Manager:** `uv`. Never use `pip` directly. Use `uv add <pkg>` and `uv sync` to manage dependencies.
*   **Framework:** FastAPI.
*   **Database:** SQLite via SQLAlchemy ORM. Migrations are strictly managed by `alembic`.
    *   *To generate migrations:* `cd backend && uv run alembic revision --autogenerate -m "message"`
    *   *To apply migrations:* `cd backend && uv run alembic upgrade head`
*   **Logging:** `loguru`. Do not use standard `logging` or print statements.
*   **Type Safety:** `ty`. All Python code must be fully type-hinted and pass `uv run ty` without errors.
*   **Configuration:** `pydantic-settings`. Define environment variables and constants in a settings schema.

### Frontend (Svelte 5 / SvelteKit)
*   **Framework:** Svelte 5 Runes (using `$props()`, `$state()`, etc.).
*   **Styling:** Tailwind CSS. All new components must use Tailwind utility classes.
*   **Component Library:** Custom library based on **shadcn-svelte** and **bits-ui**. Use existing components in `src/lib/components/ui/` or add new ones following the shadcn pattern.
*   **Package Manager:** `npm`.
*   **API Client Generation:** `@hey-api/openapi-ts`. Never manually fetch or type API responses. Ensure the backend is running, then run `just generate-client` to auto-generate the strictly typed TypeScript client from the FastAPI OpenAPI spec.
*   **Icons:** `lucide-svelte`.
*   **Notifications:** `svelte-sonner`.

### Global Task Runner
*   **`just`:** Use the `justfile` in the root directory for executing common tasks.
    *   `just dev`: Starts both backend and frontend servers.
    *   `just lint`: Runs Ruff, ty, and Svelte Check.
    *   `just format`: Auto-formats code with Ruff.

## 2. Code Quality & Pre-commit
*   **PEP 8 Compliance:** All Python code must strictly adhere to PEP 8 standards. Use explicit, idiomatic language features.
*   **Descriptive Naming:** Always use very descriptive variable and function names. Avoid abbreviations (e.g., use `file_state` instead of `fs`) to maintain high readability.
*   **Pre-commit:** All code must pass `pre-commit` hooks (ruff, ruff-format, etc.).
*   **Validation:** Fulfill the user's request thoroughly, including adding tests when adding features or fixing bugs. You must empirically reproduce failures with new test cases before applying fixes.

## 3. Core Architectural Rules

### Storage Providers & Media Lifecycle
*   **Plugin Architecture:** All storage destinations are treated as plugins implementing `AbstractStorageProvider`. Avoid hardcoding hardware logic (`tape`, `hdd`) in the API or UI.
*   **Dynamic UI:** The frontend dynamically renders registration and edit forms based on a provider's `config_schema` (fetched from `GET /inventory/providers`).
*   **Standardized Telemetry:** Providers must implement `get_live_info(force: bool)` to return unified telemetry (e.g., drive status, capacity).
*   **Sanitization:** Initializing media performs a full purge of existing TapeHoard data if the `force` flag is set.
*   **Hardware Failure:** Marking media as "Failed" triggers an automatic atomic purge of all associated `file_versions` to surface those files as "Pending" on the dashboard.

### Database & Performance
*   **High Concurrency:** SQLite must always run in **WAL (Write-Ahead Logging)** mode with a 30s busy timeout and larger page cache.
*   **Archival Intent:** `is_ignored` in `filesystem_state` is the single source of truth. The scanner indexes all files but lazily marks excluded ones as `is_ignored = 1`. Explicit user tracking policies override global exclusions.
*   **Aggregate Intelligence:** Use Raw SQL Aggregates for dashboard stats and directory protection status to avoid N+1 query patterns.
*   **FTS5 Search:** Full-text search is managed via triggers. Ensure searches filter for `has_version = 1` when browsing the Archive Index, regardless of current `is_ignored` state on disk.

### Scanning & Hashing Architecture
*   **Concurrent Phasing:** Decoupled into `SCAN` (Metadata, Normal priority) and `HASH` (Content, Idle priority with dynamic `iowait` throttling).
*   **Thread-Safe Metrics:** All counters (files processed, bytes hashed) must be protected by a `threading.Lock`.
*   **Hashing Progress:** Hashing jobs calculate progress against a dynamically updating snapshot of total `is_indexed = 0 AND is_ignored = 0` files.

### Archival & Recovery
*   **Format Negotiation:** The Archiver adapts formats based on provider capabilities (`supports_random_access`).
    *   *Sequential (Tape):* Uses `.tar` streams to maintain drive streaming.
    *   *Random Access (HDD/Cloud):* Uses native direct file copying/objects to enable instant seekless restores without unpacking gigabytes of data.
*   **Bitstream Integrity:** `RangeFile` must guarantee exact byte counts for tar alignment.
*   **Metadata Fidelity:** The restorer must preserve original **permissions (chmod)**, **timestamps (utime)**, and **ownership (chown)** when recovering files natively or via tar.
*   **Independence:** Force all tar archive members to be **Regular Files** to break fragile hard-link dependencies. Symlinks are preserved as `SYMTYPE` (or `.symlink` stub objects for native format).

### Deployment & Testing
*   **Temporal Standard:** Backend uses **UTC**. Frontend uses `parseUTCDate` to convert to browser **Local Time**.
*   **Unsaved Changes Guard:** UI must use `beforeNavigate` and `beforeunload` listeners to warn users if they leave the Settings or Media registration forms with uncommitted changes.
*   **Testing Protocol:** Use **Alembic-driven file-based SQLite** for tests to ensure 100% schema fidelity (including FTS5 and triggers) and reliable cross-thread data visibility. Atomic truncation must occur between tests.

### UI & UX Philosophy
*   **Direct Terminology:** Use technical terms like "Backup Manager", "System Status", "Archive Index". Avoid marketing fluff.
*   **Layout:** Natural page scrolling only. No sticky headers.
*   **Navigation:** The FileBrowser must maintain internal back/forward history separate from browser page navigation.

### API & Type Safety
*   **Explicit Response Models:** All FastAPI endpoints MUST explicitly declare a `response_model`. This is critical for generating accurate OpenAPI specs and strictly typed TypeScript SDKs for the frontend.
*   **Centralized Schemas:** Define shared Pydantic models in `app.api.schemas` to avoid circular dependencies when importing across different routers.

### Hardware Polling & Stability
*   **Non-Intrusive Polling:** Hardware status checks must prioritize non-intrusive methods (e.g., reading MAM via `sg_read_attr`). Intrusive operations (`mt rewind`) are strictly fallbacks. Always verify device path existence (`os.path.exists`) before issuing SCSI/CLI commands to prevent log spam on disconnected drives.
*   **Last Known Good (LKG) Caching:** Implement LKG caching in both backend hardware providers and frontend UI state. If a status poll fails or returns empty because a device is temporarily busy with an archival job, preserve and return the LKG state to prevent UI flickering.
*   **Forced Refreshes:** Hardware polling defaults to throttled (e.g., 2 seconds) intervals. Use `force=True` on provider calls and `?refresh=true` on API endpoints to bypass throttling when the user explicitly requests a live update or upon initial page loads.

### Frontend Reactivity
*   **Svelte 5 State:** When mutating complex data structures like `Map` or `Set` in Svelte 5 `$state`, always explicitly reassign the variable (e.g., `myMap = new Map(myMap)`) after mutation to trigger the reactivity engine.

## 4. Pending Feature Implementations
*   **Media Pools & Sets:** Transition from targeting individual media to targeting logical `MediaPool` entities. Archiver logic should resolve a pool to its active appendable member. Requires a new DB model and UI management.
*   **Location & Custody Tracking:** Implement a formalized check-in/out ledger (`MediaCustodyLog`) for physical offline media.
*   **Barcode & Label Generation:** Add a feature using `reportlab` or `weasyprint` to generate printable Avery-format PDF sheets containing Code 39 barcodes for tapes and QR codes for HDDs.
*   **Lifecycle Policies:** Implement background tasks in `scheduler.py` to flag expired data for pruning based on user-defined retention rules. Add physical wear alerts to the dashboard based on tape `load_count` and `lifetime_mib_written`.
