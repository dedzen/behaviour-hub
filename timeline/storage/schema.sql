PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    timestamp TEXT NOT NULL,

    device_source TEXT NOT NULL,

    event_kind TEXT NOT NULL,

    category TEXT,
    name TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    start_timestamp TEXT NOT NULL,
    end_timestamp TEXT NOT NULL,

    duration_seconds INTEGER NOT NULL,

    category TEXT,
    name TEXT,

    source TEXT NOT NULL,

    start_event_id INTEGER NOT NULL,
    end_event_id INTEGER NOT NULL,

    FOREIGN KEY(start_event_id) REFERENCES events(id),
    FOREIGN KEY(end_event_id) REFERENCES events(id)
);

CREATE TABLE IF NOT EXISTS points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    timestamp TEXT NOT NULL,

    category TEXT,
    name TEXT NOT NULL,

    source TEXT NOT NULL,

    event_id INTEGER,

    FOREIGN KEY(event_id) REFERENCES events(id)
);
CREATE TABLE IF NOT EXISTS annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    timestamp TEXT NOT NULL,

    text TEXT NOT NULL,

    chunk_id INTEGER,
    point_id INTEGER,

    FOREIGN KEY(chunk_id) REFERENCES chunks(id),
    FOREIGN KEY(point_id) REFERENCES points(id)
);
CREATE TABLE IF NOT EXISTS context (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    timestamp TEXT NOT NULL,

    key TEXT NOT NULL,
    value TEXT NOT NULL,

    source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS day_markers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    day TEXT NOT NULL UNIQUE,

    habits_json TEXT NOT NULL DEFAULT '{}',
    people_json TEXT NOT NULL DEFAULT '[]',
    quick_note_markdown TEXT NOT NULL DEFAULT '',
    mood REAL
);
