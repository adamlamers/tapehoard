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
*   **Descriptive Naming:** Always use very descriptive variable and function names. Avoid abbreviations whenever possible to maintain high readability.
*   All code must pass `pre-commit` hooks. If you generate a new file or modify an existing one, ensure it complies with `ruff` and `ruff-format`.
*   You can manually format your changes by running `just format`.

## 3. Core Architectural Rules

### Hardware & Media Lifecycle
*   **Hardware Decoupling:** Hardware configuration (like tape drive paths or general mount configurations) is global, not bound to individual media. Media represents only identity and capacity.
*   **Abstract Storage Providers:** The core archiver must never directly call `mt` or write `tar` streams. It must use the interfaces in `backend/app/providers/base.py` (Tapes, HDDs, Cloud).
*   **Pulse Checks:** Every media asset must support `check_online()` (hardware detection) and `check_existing_data()` (pre-initialization warning).
*   **Sanitization:** Initializing a drive must perform a full purge of existing TapeHoard data if the `force` flag is set.
*   **Cloud Encryption:** Cloud backups use `pycryptodome` AES-256-GCM with PBKDF2 for verifiable, authenticated client-side encryption. Credentials and passphrases are not stored in plaintext.

### Database & Performance
*   **High Concurrency:** SQLite must always run in **WAL (Write-Ahead Logging)** mode with a 30s busy timeout, memory-mapped I/O, and larger page cache to support concurrent scans and UI operations.
*   **Aggregate Intelligence:** Avoid N+1 query patterns. Use Raw SQL Aggregates for directory protection statuses, manifest generation, and dashboard statistics.
*   **Indexing:** All path-based operations must be backed by the `ix_filesystem_state_file_path` index. All foreign keys must be indexed.
*   **Search Engine:** The FTS5 index is a standalone table synchronized via triggers. Triggers must be optimized to only fire on `file_path` changes to minimize overhead during routine scans.

### Scanning & Hashing Architecture
*   **Concurrent Phasing:** Scanning is strictly decoupled into two phases: a fast Metadata Discovery (`SCAN`) running at normal priority, and a concurrent Content Hashing (`HASH`) running at idle background priority (with dynamic `iowait` throttling) to prevent host I/O starvation.
*   **Thread-Safe Metrics:** All metrics (files found, hashed, processed, byte throughput) must be explicitly protected by a `threading.Lock` to avoid race conditions.

### Archival & Recovery
*   **Multi-Part Archiving:** Files larger than media capacity must be split using `RangeFile` and archived with `.part_OFFSET_SIZE` suffixes in the tar stream.
*   **Deduplication:** Always check for existing hashes on the target media before writing to the tar stream. If a hash exists, record the new version pointing to the existing location.
*   **Recovery Manifests:** Calculations must be sequential and media-aware. The system should group all files needed from a specific tape to minimize physical hardware swaps.
*   **Local Staging:** Use the `/staging` directory for temporary file reassembly. Never perform complex I/O directly in the production data paths.

### Deployment & Environment
*   **Temporal Standard:** The backend strictly uses **UTC**. The frontend must use `parseUTCDate` from `lib/utils.ts` to convert timestamps to the browser's **Local Time** for display.
*   **Docker Portability:** Native support for `PUID`, `PGID`, `RUN_AS_ROOT` and `PORT` environment variables. The frontend uses **relative API paths** (`baseUrl: ''`) in production to remain host/port-agnostic.
*   **Job Management:** The `JobManager` must be database-driven. Never use in-memory sets for job states (like cancellation), as they will not sync across multi-worker environments.

### UI & UX Philosophy
*   **Direct Terminology:** Use simple, direct, non-dramatic language. Avoid terms like "Fleet", "Archive Command", "Telemetry", etc. Use standard technical terms like "Backup Manager", "System Status", "Manage Media".
*   **Dynamic Layout:** Use natural page scrolling (`overflow-y-auto` on the main wrapper) rather than fixed/sticky headers for a clean, professional dashboard flow.
*   **Actionable Analytics:** Space analysis relies on hierarchical/recursive treemaps with root-collapsing to present actionable insights without irrelevant root-level noise.
