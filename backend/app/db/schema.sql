CREATE TABLE filesystem_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE,
    size BIGINT,
    mtime FLOAT,
    sha256_hash TEXT,
    is_ignored BOOLEAN DEFAULT 0,
    last_seen_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE storage_media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    media_type TEXT,
    identifier TEXT UNIQUE,
    generation_tier TEXT,
    capacity BIGINT,
    bytes_used BIGINT DEFAULT 0,
    location TEXT,
    status TEXT DEFAULT 'active',
    extra_config TEXT,
    priority_index INTEGER DEFAULT 0,
    last_seen DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE file_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filesystem_state_id INTEGER,
    media_id INTEGER,
    file_number TEXT,
    offset_in_tar INTEGER,
    is_split BOOLEAN DEFAULT 0,
    split_id TEXT,
    offset_start BIGINT DEFAULT 0,
    offset_end BIGINT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(filesystem_state_id) REFERENCES filesystem_state(id),
    FOREIGN KEY(media_id) REFERENCES storage_media(id)
);

CREATE TABLE tracked_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE,
    is_directory BOOLEAN DEFAULT 1,
    action TEXT DEFAULT 'include',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE restore_cart (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filesystem_state_id INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(filesystem_state_id) REFERENCES filesystem_state(id)
);

CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type TEXT,
    status TEXT DEFAULT 'PENDING',
    progress FLOAT DEFAULT 0.0,
    current_task TEXT,
    error_message TEXT,
    started_at DATETIME,
    completed_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE system_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- FTS5 Virtual Table for Instant Search
CREATE VIRTUAL TABLE filesystem_fts USING fts5(
    file_path,
    content='filesystem_state',
    content_rowid='id'
);

-- Trigger to keep FTS5 synchronized with real state
CREATE TRIGGER filesystem_fts_insert AFTER INSERT ON filesystem_state BEGIN
    INSERT INTO filesystem_fts(rowid, file_path) VALUES (new.id, new.file_path);
END;

CREATE TRIGGER filesystem_fts_delete AFTER DELETE ON filesystem_state BEGIN
    INSERT INTO filesystem_fts(filesystem_fts, rowid, file_path) VALUES('delete', old.id, old.file_path);
END;

CREATE TRIGGER filesystem_fts_update AFTER UPDATE ON filesystem_state BEGIN
    INSERT INTO filesystem_fts(filesystem_fts, rowid, file_path) VALUES('delete', old.id, old.file_path);
    INSERT INTO filesystem_fts(rowid, file_path) VALUES (new.id, new.file_path);
END;
