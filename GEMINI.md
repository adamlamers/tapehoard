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
*   All code must pass `pre-commit` hooks. If you generate a new file or modify an existing one, ensure it complies with `ruff` and `ruff-format`.
*   You can manually format your changes by running `just format`.

## 3. Core Architectural Rules
*   **Abstract Storage Providers:** The core archiver must never directly call `mt` or write `tar` streams. It must use the Abstract Storage Provider interfaces defined in `backend/app/providers/base.py` to seamlessly support Tapes, HDDs, and Cloud buckets.
*   **File Hashing & Deduplication:** Never re-hash a file if its `mtime` and `size` remain unchanged in the `filesystem_state` table.
*   **Local Staging (`/staging`):** All massive file manipulation, chunking, and restore compilations must occur in the temporary `/staging` directory before hitting the final media or user.
*   **Docker PUID/PGID:** Always account for the fact that the container will be running under a dynamic User ID. Avoid writing files to directories where the `appuser` might lack permissions.
