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

### Hardware & Media Lifecycle
*   **Hardware Decoupling:** Hardware configuration (tape drive paths, mount roots) is global. Media objects represent only identity and capacity.
*   **Identification:** Tapes use barcodes/IDs via `mtx`/SCSI. HDDs use **Filesystem UUIDs** as a hardware fingerprint to remain path-agnostic if mount points change.
*   **S3-Compatible targets:** Standardized on `s3` media type using `boto3`. Collects Endpoint URL, Bucket, and HMAC credentials during ingestion.
*   **Sanitization:** Initializing media performs a full purge of existing TapeHoard data if the `force` flag is set.
*   **Hardware Failure:** Marking media as "Failed" triggers an automatic atomic purge of all associated `file_versions` to surface those files as "Pending" on the dashboard.

### Database & Performance
*   **High Concurrency:** SQLite must always run in **WAL (Write-Ahead Logging)** mode with a 30s busy timeout and larger page cache.
*   **Aggregate Intelligence:** Use Raw SQL Aggregates for dashboard stats and directory protection status to avoid N+1 query patterns.
*   **FTS5 Search:** Full-text search is managed via triggers. Ensure searches filter for `has_version = 1` when browsing the Archive Index.

### Scanning & Hashing Architecture
*   **Concurrent Phasing:** Decoupled into `SCAN` (Metadata, Normal priority) and `HASH` (Content, Idle priority with dynamic `iowait` throttling).
*   **Thread-Safe Metrics:** All counters (files processed, bytes hashed) must be protected by a `threading.Lock`.

### Archival & Recovery
*   **Bitstream Integrity:** `RangeFile` must guarantee exact byte counts. If a file is truncated on disk during backup, it must be padded with null bytes to prevent corrupting the tar alignment.
*   **Metadata Fidelity:** The restorer must preserve original **permissions (chmod)**, **timestamps (utime)**, and **ownership (chown)** when recovering files.
*   **Seekable Restoration:** Non-tape media (HDD/S3) must use `mode="r:*"` (Seekable) for robust partial restores, while Tapes use `mode="r|*"` (Pipe).
*   **Path Normalization:** Aggressively strip leading slashes and `./` prefixes from both DB keys and tar members to ensure matches across different environments.
*   **Independence:** Force all archive members to be **Regular Files** to break fragile hard-link dependencies. Symlinks are preserved as `SYMTYPE` with relative targets.

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
*   **Non-Intrusive Polling:** Hardware status checks (e.g., tape drive identity) must prioritize non-intrusive methods like reading the MAM (Media Auxiliary Memory) Barcode (`sg_read_attr`). Intrusive operations (like `mt rewind`) should only be used as fallbacks and never during periodic status polling when the drive is busy.
*   **Last Known Good (LKG) Caching:** Implement LKG caching in hardware providers to persist the last successful hardware read. If a status poll fails because a device is temporarily busy with an archival job, return the LKG state instead of empty data to prevent UI flickering.

### Frontend Reactivity
*   **Svelte 5 State:** When mutating complex data structures like `Map` or `Set` in Svelte 5 `$state`, always explicitly reassign the variable (e.g., `myMap = new Map(myMap)`) after mutation to trigger the reactivity engine.
