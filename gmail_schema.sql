-- =============================================================================
--  gmail_db — Gmail Pool & Submissions
-- =============================================================================

CREATE TABLE IF NOT EXISTS gmail_pool (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    email          TEXT    UNIQUE NOT NULL,
    password       TEXT    NOT NULL,
    recovery_email TEXT,
    is_assigned    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS submissions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id     INTEGER NOT NULL,
    submission_type TEXT    NOT NULL CHECK(submission_type IN ('normal','2fa')),
    email           TEXT    UNIQUE NOT NULL,
    password        TEXT    NOT NULL,
    secret_key_2fa  TEXT,
    status          TEXT    DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
    submitted_at    TEXT    DEFAULT (datetime('now'))
);
