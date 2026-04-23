# Tape Backup Manager Implementation Plan

## 1. Overview & Objectives
This document outlines the architecture and implementation strategy for a Tape Backup Manager. The system is designed to provide robust, index-driven backups to LTO tape media, catering specifically to single-tape drive users while maintaining the scalability to support tape libraries in the future.

---

## 2. LTO Generations & Capacity Planning

The system targets the **native (raw) storage capacity** of the tapes to ensure reliable capacity planning. A safety margin (~50GB) will be reserved.

| Generation | Native Capacity | Target Fill Capacity (approx.) |
| :--- | :--- | :--- |
| **LTO-5** | 1.5 TB | ~ 1.42 TB |
| **LTO-6** | 2.5 TB | ~ 2.37 TB |
| **LTO-7** | 6.0 TB | ~ 5.70 TB |
| **LTO-8** | 12.0 TB | ~ 11.4 TB |
| **LTO-9** | 18.0 TB | ~ 17.1 TB |
| **LTO-10** | 30.0 TB | ~ 28.5 TB |

---

## 3. Itemized Features & Implementation Descriptions

### 3.1 SQLite-based Indexing Database
*   **Description:** A centralized database to act as the single source of truth for the filesystem state, backup jobs, and physical tape inventory.
*   **Implementation:** Use `sqlite3`.
    *   `filesystem_state` table: Tracks `id`, `file_path`, `size`, `mtime`, `sha256_hash`, `last_seen_timestamp`.
    *   `storage_media` table (formerly `tapes`): Tracks `id`, `media_type` (e.g., tape, hdd, cloud), `identifier` (barcode, UUID, or bucket name), `generation/tier`, `capacity`, `bytes_used`, `location`, `status`.
    *   `backups` table: Tracks `id`, `job_name`, `type` (initial/incremental), timestamps, and status.
    *   `file_versions` table: Maps a `filesystem_state_id` to a `media_id`, storing the `file_number` (e.g., tape position, or object path) and an optional `offset_in_tar`.
    *   `job_logs` table: Tracks `id`, `backup_id`, `timestamp`, `log_level`, `message` (e.g., file written, permission denied error, manual eject).

### 3.2 File Hashing & Deduplication
*   **Description:** Utilizing cryptographic hashes to identify unique files, ensuring that duplicate files across the filesystem (or over time) are recognized. This prevents writing the exact same file content to tape multiple times if it has already been stored.
*   **Implementation:**
    *   During the filesystem scan, the system checks a file's `mtime` (modification time) and `size` against the existing `filesystem_state` index. A cryptographic hash (e.g., SHA-256 or BLAKE3) is **only computed** if the file is completely new or its `mtime`/`size` indicates it has been modified since the last scan. This heavily optimizes sequential scans of large filesystems.
    *   Store this hash in the `filesystem_state` table.
    *   Before writing a file to tape during a backup, query the database by the computed hash. If the hash exists and is mapped to a valid tape location in `file_versions`, link the new file path to the existing tape location instead of writing the payload again.

### 3.3 Web-Based Explorer Interface & Search
*   **Description:** A user-friendly, web-based graphical interface that allows users to navigate the backed-up contents similarly to Windows Explorer or macOS Finder. It includes robust search functionality to locate files across all tapes.
*   **Implementation:**
    *   **Backend:** Serve a local web application using a lightweight framework (e.g., FastAPI or Flask). The backend will expose REST API endpoints that query the SQLite database.
    *   **Frontend:** Build a modern, responsive web UI utilizing Svelte 5 as the primary framework, styled with Tailwind CSS and a custom component library based on shadcn-svelte and bits-ui.
    *   **Features:**
        *   **Virtual Filesystem (Frontend Explorer):** Dynamically parse the stored `file_path`s in SQLite to generate a unified, browsable directory structure. Users can navigate this virtual filesystem in the browser exactly as if it were a single, massive mounted drive spanning all their backups. Clicking on a specific file opens a detailed metadata panel displaying its exact storage locations (e.g., "Tape BUP-001", "HDD-002"), backup dates, sizes, and file hashes—all without needing the physical media inserted.
        *   **Global Search (Full-Text Search):** Implement an advanced search bar utilizing SQLite's FTS5 (Full-Text Search) extension. File paths and names will be indexed in an FTS5 virtual table to provide instantaneous, highly optimized keyword searching across millions of files, replacing slower `LIKE` queries.
        *   **Restore Cart:** Allow users to select multiple files or folders from the web interface and "Add to Restore Queue", which then triggers the CLI/Backend to prompt for the necessary tapes.
        *   **Multi-Drive & Library Management:** The web interface will allow users to view connected tape drives and robotic libraries. The backend will spawn concurrent background processes, allowing multiple read/write operations to happen in parallel across different tape drives. The interface will also provide manual controls for sending tape library commands (e.g., load, unload, inventory).

### 3.4 Backup Strategies (Versioning & Compaction)
*   **Description:** Managing file modifications, deletions, and optimizing tape usage over time on an append-only medium.
*   **Implementation:**
    *   *Initial (Full):* Walk directories, compute hashes, populate `filesystem_state`. Group files up to the target tape capacity. Stream to tape using `tar` and update `file_versions`.
    *   *Incremental (Append-Only Versioning):* Walk directories and detect modified files via `size`/`mtime`. Because tape cannot be overwritten in place, modified files are packaged into a new `tar` stream and appended to the newest active tape. The old version remains on its original tape, providing automatic point-in-time file history. Deleted files are simply marked as `unseen_timestamp` in the database and hidden from the current Web UI view.
    *   *Tape Compaction (Grooming):* Over time, old tapes accumulate "stale" data (deleted files or old versions). The system will identify fragmented tapes. The user (or autoloader) loads the fragmented tape, the system reads *only* the current active files into the Local Staging Area, and then appends them to the newest active tape. Once migrated, the old fragmented tape is marked as "Recyclable" in the DB, allowing the physical cartridge to be formatted and reused.

### 3.5 File Splitting & Bin-Packing
*   **Description:** Intelligent packing of files to maximize tape usage without overflowing, and splitting of files that exceed a single tape's capacity.
*   **Implementation:**
    *   Implement a greedy bin-packing algorithm to group files into "Tape Sets" before writing.
    *   If a single file exceeds the tape capacity, utilize the Unix `split` command (or equivalent chunking logic in the primary language) to break the file into parts before packaging it into the `tar` stream. The database must record these as multi-part files for reassembly upon restore.

### 3.6 Optimized Storage Format (`tar` + EOF Marks)
*   **Description:** Avoiding LTFS in favor of a simpler, more performant approach for many files by using raw `tar` streams and tape file marks.
*   **Implementation:**
    *   Stream files into 100GB - 500GB `tar` archives.
    *   Write the `tar` archive to the non-rewinding tape device (e.g., `/dev/nst0`).
    *   The tape drive automatically writes an EOF mark after each archive.
    *   Record the tape file number (the index of the EOF mark) in the SQLite database for each file contained in that `tar` stream.

### 3.7 Near-Random Access Retrieval
*   **Description:** The ability to quickly retrieve a specific file without reading the entire tape.
*   **Implementation:**
    *   Query the SQLite database for the target file to find its `tape_id` and `tape_file_number`.
    *   Prompt the user to insert the correct tape (by barcode).
    *   Execute `mt -f /dev/nst0 fsf <tape_file_number>` to fast-forward the tape head directly to the start of the correct `tar` stream.
    *   Extract the specific file from the `tar` stream.

### 3.8 Tape Handling, Barcode Tracking, & Autoloader Library Support
*   **Description:** Workflows tailored for both users manually swapping single tapes and advanced users operating robotic tape libraries (autoloaders).
*   **Implementation:**
    *   **Manual Users:** CLI and Web prompts to insert specific tapes. On new tape insertion, prompt the user to input a physical barcode label, or auto-generate one (e.g., `BUP-00001`).
    *   **Automated Libraries:** For setups with tape changers, use `mtx` (Media Changer Tools) to automatically scan the inventory of storage slots, read physical hardware barcodes, and orchestrate the loading/unloading of cartridges between slots and drives without user intervention.
    *   **Verification:** Regardless of method, write a tiny header file (tape label) at tape file number 0 (the very beginning of the tape) containing the barcode. Validate this label upon subsequent insertions to ensure physical tape contents match the database expectations.

### 3.9 Alerting for Tape Switching
*   **Description:** Notifying the user when a tape is full and needs manual replacement.
*   **Implementation:**
    *   Monitor the `bytes_used` metric for the active tape during writing.
    *   When the target fill capacity is reached, finalize the current `tar` stream and eject the tape.
    *   Trigger alerts:
        *   Standard console audio alert (Terminal bell).
        *   OS-native desktop notifications (e.g., `notify-send` or `osascript`).
        *   Configurable webhooks (e.g., Slack, Discord, Email).
    *   Pause the backup job and wait for user input confirming a new tape insertion.

### 3.10 Data Integrity & Tape Health Monitoring
*   **Description:** Ensuring long-term survival of data by verifying tape integrity and monitoring hardware metrics.
*   **Implementation:**
    *   **Tape Scrubbing:** Schedule background tasks that read a tape from start to finish, verifying the computed hashes of the payload against the SQLite database to detect bit rot or magnetic degradation.
    *   **Hardware Health (SMART/Logs):** Utilize SCSI logs (via `sg_logs` or `smartctl`) to track hardware-level metrics (e.g., soft/hard read/write error rates, load/unload counts, remaining tape life) and display warnings in the Web UI to predict failures.

### 3.11 Physical Vault & Location Tracking
*   **Description:** Managing the physical whereabouts of tapes and enforcing retention policies for offsite backups.
*   **Implementation:**
    *   **Location Management:** Add a `location` field in the `tapes` database table to track where a tape physically resides (e.g., "Bank Safe Deposit Box", "Shelf 2", "In Drive").
    *   **Rotation Policies:** Support standard backup rotations (like GFS - Grandfather-Father-Son). Allow marking a tape's data as "expired," which flags the physical tape cartridge as "Recyclable/Ready to Format" in the UI.

### 3.12 Security (Encryption) & Smart Compression
*   **Description:** Protecting sensitive data at rest and optimizing tape capacity based on file type.
*   **Implementation:**
    *   **Encryption:** Provide options for either hardware-based Application-Managed Encryption (AME) using the LTO drive's native capabilities, or software-based encryption by piping the `tar` stream through symmetric encryption (e.g., `gpg` or `age`) before writing to tape.
    *   **Smart Compression:** Allow users to toggle hardware compression. Implement logic to selectively use fast software compression (like `zstd`) for highly compressible datasets while disabling it for pre-compressed media formats (e.g., `.mkv`, `.mp4`).

### 3.14 Local Staging Area (Cache Directory)
*   **Description:** A dedicated, high-speed local storage directory (preferably NVMe/SSD) used for buffering data between the host filesystem and the tape drive.
*   **Implementation:**
    *   **Performance Buffering:** To prevent "shoe-shining" (tape drive stopping/starting due to slow data feeds), `tar` streams can be pre-built in the staging area before being flushed to tape at maximum sequential speed.
    *   **Restore Carts:** When a user queues files from multiple tapes for restoration, the files are temporarily extracted to the staging area until all requested tapes have been read, allowing the user to download a single package.
    *   **File Splitting:** Provides temporary space for chunking massive files that exceed a single tape's capacity before writing.
    *   **Docker Volume:** This must be exposed as a dedicated bind mount (e.g., `/staging`) in the Docker deployment strategy.

### 3.15 Quality of Life & Ecosystem Integration
*   **Description:** Features tailored for homelabs and data hoarders to seamlessly integrate the backup manager into their existing infrastructure.
*   **Implementation:**
    *   **Metrics Exporter:** Provide a `/metrics` Prometheus endpoint exposing data about the backup system (e.g., total bytes backed up, tape drive status, last backup duration, active tapes) for Grafana dashboards.
    *   **Automated Scheduling:** Implement a built-in scheduler (e.g., using `APScheduler`) to trigger backups automatically at specific intervals, pausing and alerting if a tape swap is needed.
    *   **Metadata & Proxy Caching:** During the initial scan of large media libraries, extract and store tiny metadata footprints (e.g., video resolution, EXIF data, or highly compressed thumbnails) in the SQLite DB. This allows users to browse and preview file contents in the Web UI without needing to load the physical tape.

### 3.16 Source Management & Tracking UX
*   **Description:** A clear, interactive way for users to define exactly which folders and files should be backed up within the Web UI, handling complex inclusion and exclusion rules.
*   **Implementation:**
    *   **Visual File Tree:** Under a "Backup Jobs" or "Sources" tab, the frontend will render a live, interactive tree-view of the host's `/source_data` directory.
    *   **Checkbox Tracking:** Users can click checkboxes next to folders or files to explicitly "Track" (include) or "Untrack" (exclude) them from a backup job.
    *   **Exclusion Rules (Gitignore Style):** Provide an advanced text input where users can define global or job-specific exclusion patterns (e.g., `*.tmp`, `node_modules/`, `cache/`) mimicking `.gitignore` behavior. These rules are stored in the SQLite database and evaluated during the filesystem scan.

### 3.17 Abstract Storage Providers (Tape, HDD, Cloud)
*   **Description:** Making the backup manager generic enough to handle not just sequential LTO tapes, but also random-access offline HDDs (e.g., in a USB dock) and remote Cloud Storage (e.g., AWS S3, Backblaze B2).
*   **Implementation:** Introduce a "Storage Provider" backend interface.
    *   **Tape Provider:** The default implementation utilizing `mt`, block devices (`/dev/nst0`), physical barcodes, and sequential EOF file marks.
    *   **Offline HDD Provider:** Treats an external hard drive like a tape. It writes `tar` streams or raw files to a mounted path (e.g., `/mnt/usb`). It tracks the specific HDD by writing a hidden identifier file (e.g., `.tapehoard_id=HDD-001`) to the root of the drive. The UI still prompts the user: *"Please insert HDD-001 into the dock to continue."*
    *   **Cloud Storage Provider:** Uses cloud APIs (e.g., `boto3` for S3). It chunks data into manageable, multipart-upload friendly blocks. Instead of "inserting media," the provider authenticates and streams encrypted chunks directly to a designated bucket, logging the bucket path as the "Media ID" in the database.

### 3.18 Global Inventory & Credential Management
*   **Description:** A dedicated interface and backend subsystem to manage the entire fleet of available storage media, their capacities, hardware types, and authentication credentials for cloud providers.
*   **Implementation:**
    *   **Inventory Dashboard:** The Web UI will feature an "Inventory" tab displaying a comprehensive, filterable list of all registered media (e.g., "LTO-6 Tape BUP-001", "8TB WD Red HDD-002", "AWS S3 Bucket `my-backups`").
    *   **Capacity Forecasting:** The dashboard aggregates the total `capacity` and `bytes_used` across all registered media, providing users with a global view of their available "Storage Pool" before they initiate massive backup jobs.
    *   **Media Provisioning:** Users can manually register new media through the UI (e.g., pre-registering a box of 10 new LTO-8 tapes, or adding a new 16TB external drive), defining their expected capacities and physical locations.
    *   **Credential Manager (Vault):** A secure subsystem within the backend (storing encrypted keys in SQLite or utilizing environment variables) to manage Cloud Provider credentials (e.g., AWS Access Keys, Backblaze B2 Application Keys). This allows the system to seamlessly connect to different cloud buckets without prompting the user for passwords during automated backup jobs.

### 3.19 Disaster Recovery (Index Bootstrap)
*   **Description:** The ability to recover the SQLite database index in the event of complete host system failure.
*   **Implementation:**
    *   **Self-Hosting the DB:** Automatically write a compressed copy of the current SQLite database to the beginning (Tape File 1) or end of the tape every time a tape is finalized or ejected.
    *   **Cloud Sync:** An option to automatically push the SQLite DB to an S3 bucket or email it to the user after every successful backup job.
    *   **Recovery UI:** A "Recover Index from Media" button on first boot that reads the DB from an inserted tape or HDD, instantly restoring the system to a working state without manually rebuilding the index.

### 3.20 Parallel Hashing & Performance
*   **Description:** Dramatically speeding up the filesystem scan by utilizing all available CPU cores.
*   **Implementation:** The filesystem scanner must use Python's `multiprocessing` module (or thread pools). While one process walks directories reading `mtime`/`size` from the disk, a pool of worker processes aggressively computes cryptographic hashes (e.g., BLAKE3) in parallel, maximizing local read throughput.

### 3.21 Checkpointing & Job Resumption
*   **Description:** Ensuring massive, multi-hour backup jobs can be resumed after a power outage or hardware failure without starting over.
*   **Implementation:** Implement aggressive checkpointing. As each `tar` block (e.g., 100GB chunks) finishes writing and the EOF mark is successfully placed on the media, the SQLite database immediately commits those `file_versions` as "Written." If the system crashes, the next run will detect the partially completed job, fast-forward the media to the last known good EOF mark, and resume exactly where it left off.

### 3.22 Symlinks & Hardlinks Configuration
*   **Description:** Preventing infinite loops and storage bloat when backing up Unix/Linux filesystems containing symbolic links.
*   **Implementation:** Add a configuration toggle in the UI for **"Follow Symlinks"**.
    *   *Disabled (Default):* The backup simply records the link path and its target, taking up almost zero space.
    *   *Enabled:* The system treats the symlink as a real directory/file and copies the underlying data.

### 3.23 Audit Logging & Job History
*   **Description:** Providing a clear, filterable history of what succeeded, what failed, and why.
*   **Implementation:** The newly added `job_logs` table tracks every file written, "Permission Denied" errors during scans, hardware read/write retries, and media ejects. The Web UI will feature a "Logs" tab where users can filter by date, log level (INFO/WARN/ERROR), or specific backup jobs.

### 3.24 Premium UX & Interactive Workflows
*   **Description:** Elevating the software to an enterprise-grade experience by making long-running operations visible, safe, and intuitive.
*   **Implementation:**
    *   **Real-Time Progress (WebSockets/SSE):** The Svelte frontend and backend will communicate via WebSockets or Server-Sent Events. The UI provides a persistent dashboard showing the active job, live progress bars ("Writing to Tape BUP-001 (45% Full)"), transfer speeds, and ETAs. This persists across browser refreshes.
    *   **"Dry Run" / Simulation Mode:** Before committing to a multi-day backup job, users can click "Simulate Job". The system walks the filesystem, runs the bin-packing algorithm, and generates a report detailing exactly how many new files will be backed up, how many were excluded, and how much media (e.g., number of tapes) will be required.
    *   **Restore Wizard:** When executing a multi-tape restore, the UI launches a step-by-step wizard. It prompts the user for the first tape, extracts the necessary files to the Staging Area, and then prompts for the next tape, ultimately presenting the user with a single cohesive download or directory.
    *   **Visualizing Media Fragmentation:** The Inventory dashboard displays a stacked bar chart for each media showing Active Data (Green), Stale/Deleted Data (Yellow), and Free Space (Gray). If a tape is highly fragmented, it displays a recommended "Groom Tape" (Compaction) button.
    *   **Interactive Error Handling:** If the backend catches a hardware I/O error, it halts the job and triggers an alert. The UI presents actionable prompts instead of failing silently: *"Hardware Error. Please clean the tape drive head. [Retry Last Block] | [Mark Tape as Bad & Prompt for New] | [Abort Job]"*.

---

## 4. Software Dependency List

Assuming implementation in **Python** (a strong fit for CLI tools, SQLite integration, and web backends).

**System-Level Dependencies:**
*   `tar`: For archiving and streaming files.
*   `mt-st` (or standard `mt`): Magnetic Tape control utility for issuing commands like `fsf`, `rewind`, `eject`.
*   `mtx`: Media Changer Tools for controlling robotic tape libraries.
*   `smartmontools` & `sg3-utils`: For querying tape drive health and SCSI metrics (`smartctl` and `sg_logs`).
*   `zstd` / `gpg` / `age`: (Optional) System-level binaries for fast compression and encryption.
*   Tape Drive Drivers: Appropriate SAS/FC HBA drivers, the `st` (SCSI tape), and `sg` (SCSI generic) kernel modules (Linux/Unix).

**Language/Application Dependencies (Python):**
*   `sqlite3`: Built-in Python library for database management.
*   `click` or `argparse`: For building the robust Command Line Interface.
*   `hashlib` / `blake3`: For generating fast cryptographic file hashes to handle deduplication.
*   `subprocess`: Built-in for interacting with `tar`, `mt`, and `split`.
*   `FastAPI` & `uvicorn` (or `Flask`): For serving the local web application and API endpoints for the web interface.
*   `prometheus_client`: For exposing the `/metrics` endpoint to Grafana.
*   `APScheduler`: For managing automated background backup scheduling and tape scrubbing tasks.
*   `apprise` (Optional): A robust Python library for sending push notifications (Desktop, Slack, Discord, Email, etc.) for the alerting feature.
*   `tqdm` (Optional): For displaying progress bars during file scanning and writing.
*   `Pillow` / `ffmpeg-python`: (Optional) For generating image thumbnails and extracting video metadata during scans.

**Frontend Dependencies:**
*   Standard HTML/CSS/JS.
*   **Svelte 5:** For rendering the Windows Explorer style tree-view, reactive components, and handling search interactions.

---

## 5. Docker Deployment Strategy

To ensure seamless deployment on NAS operating systems (such as TrueNAS SCALE, Unraid) and standard Linux servers, the application will be packaged as a robust Docker container.

### 5.1 Configurable User and Group IDs (PUID / PGID)
*   **Description:** The container will be designed to run its internal processes as a specific user mapped to the host system. This prevents permission errors when accessing mounted source files, configuration directories, and the tape block device.
*   **Implementation:**
    *   Use an entrypoint script (e.g., via `s6-overlay` or a custom shell script) that reads `PUID` and `PGID` environment variables.
    *   On container startup, the script will create or modify a local non-root user (e.g., `appuser`) to match the provided host IDs.
    *   The backend processes and web server will be launched using `su-exec` or `gosu` under this dynamic user.
    *   **Hardware Access:** The dynamically created user will be automatically added to the container's `tape` or `disk` group to ensure it has read/write permissions for the passed-through tape drive device (`/dev/nst0`).

### 5.2 Container Architecture & Bind Mounts
*   **Base Image:** A lightweight Linux base image (e.g., Debian slim or Alpine) that includes system-level dependencies (`mt-st`, `tar`, SCSI drivers) and Python.
*   **Volumes:**
    *   `/source_data`: Bind mount for the directories the user wants to back up (Mounted as Read-Only).
    *   `/config`: Bind mount for persistent storage of the SQLite database and application settings.
    *   `/staging`: Bind mount to a high-speed local disk (NVMe/SSD) for buffering `tar` streams, chunking large files, and caching restore operations.
*   **Devices:**
    *   `--device=/dev/nst0:/dev/nst0`: Passthrough of the non-rewinding SCSI tape device (extendable to `/dev/nst1`, etc., for multiple drives).
    *   `--device=/dev/sgX:/dev/sgX`: (Optional) Passthrough of the SCSI Generic device for communicating with the robotic tape changer/library.
*   **Ports:** Expose the web interface port (e.g., `8080`) to the host network for user access.

---

## 6. Project Directory Structure

To maintain a clean separation of concerns, the repository will be structured as a monorepo containing both the Python backend and the Svelte frontend. This ensures synchronized development and simplifies the Docker build process.

```text
tapehoard/
├── backend/                  # Python/FastAPI Backend
│   ├── app/                  # Main application package
│   │   ├── api/              # FastAPI route definitions (routers)
│   │   │   ├── backups.py
│   │   │   ├── inventory.py
│   │   │   └── system.py
│   │   ├── core/             # Configuration, logging, dependencies
│   │   ├── db/               # SQLite connection, migrations (Alembic), schema
│   │   │   ├── schema.sql
│   │   │   └── models.py     # SQLAlchemy or raw dataclasses
│   │   ├── providers/        # Abstract Storage Providers
│   │   │   ├── base.py       # Provider interface
│   │   │   ├── tape.py       # LTO `mt` / `mtx` implementation
│   │   │   ├── hdd.py        # Offline HDD implementation
│   │   │   └── cloud.py      # Cloud API implementation
│   │   ├── services/         # Core business logic
│   │   │   ├── scanner.py    # Multiprocessing filesystem walker
│   │   │   ├── archiver.py   # Tar streaming, chunking, and EOF marks
│   │   │   └── scheduler.py  # APScheduler background tasks
│   │   └── main.py           # FastAPI application entry point
│   ├── tests/                # Backend unit and integration tests
│   ├── pyproject.toml        # Python dependencies (Poetry or similar)
│   └── requirements.txt
├── frontend/                 # Svelte 5 Frontend
│   ├── src/
│   │   ├── lib/              # Shared components, stores, utilities
│   │   │   ├── components/   # UI components (Tree View, Modals, Progress)
│   │   │   ├── stores/       # Svelte stores for global state (WebSockets)
│   │   │   └── utils/        # API clients, formatting functions
│   │   ├── routes/           # SvelteKit routing (pages)
│   │   │   ├── +page.svelte  # Dashboard / Active Jobs
│   │   │   ├── inventory/    # Media management
│   │   │   ├── sources/      # Directory tree and tracking config
│   │   │   └── restores/     # Restore Wizard
│   │   ├── app.html          # HTML template
│   │   └── app.css           # Global styles
│   ├── static/               # Static assets (images, favicons)
│   ├── package.json          # Node dependencies
│   ├── svelte.config.js
│   └── vite.config.js        # Vite build configuration
├── docker/                   # Docker build and deployment files
│   ├── Dockerfile            # Multi-stage build (builds frontend, then backend)
│   ├── entrypoint.sh         # s6-overlay/su-exec script for PUID/PGID handling
│   └── docker-compose.yml    # Example compose file for users
├── docs/                     # Project documentation
├── .gitignore
├── .dockerignore
└── README.md                 # Project overview and quickstart guide
```

### 6.1 Directory Highlights
*   **`backend/app/providers/`:** This is where the core abstraction lives. The `scanner.py` and `archiver.py` talk to `base.py`, allowing the system to swap between `tape.py`, `hdd.py`, or `cloud.py` seamlessly based on the job.
*   **`backend/app/services/scanner.py`:** Contains the heavily optimized, multiprocessing directory traversal and hashing logic.
*   **`frontend/src/lib/stores/`:** Will handle the persistent WebSocket/SSE connections for live progress bars across the application.
*   **`docker/`:** Contains the multi-stage `Dockerfile`. It will first use a Node image to build the Svelte frontend into static HTML/JS/CSS files, and then copy those static files into the final Python backend image so FastAPI can serve both the API and the Web UI from a single container.
