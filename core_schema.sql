-- =============================================================================
--  core_db — Users, Admins, Bot Settings, Withdrawals, Notifications
-- =============================================================================

CREATE TABLE IF NOT EXISTS users (
    telegram_id            INTEGER PRIMARY KEY,
    username               TEXT,
    main_balance           REAL    DEFAULT 0.0,
    pending_balance        REAL    DEFAULT 0.0,
    total_completed_gmails INTEGER DEFAULT 0,
    total_strikes          INTEGER DEFAULT 0,
    is_banned              INTEGER DEFAULT 0,
    block_until            TEXT,
    created_at             TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS admins (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    UNIQUE NOT NULL,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL CHECK(role IN ('owner','admin'))
);

CREATE TABLE IF NOT EXISTS bot_settings (
    key_name  TEXT PRIMARY KEY,
    key_value TEXT
);

CREATE TABLE IF NOT EXISTS withdrawals (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id      INTEGER NOT NULL,
    method           TEXT    NOT NULL,
    wallet_or_number TEXT    NOT NULL,
    amount           REAL    NOT NULL,
    status           TEXT    DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
    requested_at     TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER,
    message     TEXT    NOT NULL,
    is_read     INTEGER DEFAULT 0,
    created_at  TEXT    DEFAULT (datetime('now'))
);

INSERT OR IGNORE INTO bot_settings (key_name, key_value) VALUES ('banner_image_url', '');
INSERT OR IGNORE INTO bot_settings (key_name, key_value) VALUES ('bot_description', 'Welcome to Gmail Bot! Complete tasks and earn rewards.');
INSERT OR IGNORE INTO bot_settings (key_name, key_value) VALUES ('news_channel', '');
INSERT OR IGNORE INTO bot_settings (key_name, key_value) VALUES ('support_username', '');
INSERT OR IGNORE INTO bot_settings (key_name, key_value) VALUES ('normal_rate', '0.30');
INSERT OR IGNORE INTO bot_settings (key_name, key_value) VALUES ('two_fa_rate', '0.50');
INSERT OR IGNORE INTO bot_settings (key_name, key_value) VALUES ('ref_bonus', '0.10');
INSERT OR IGNORE INTO bot_settings (key_name, key_value) VALUES ('min_withdrawal', '5.00');

-- Owner Account → Username: owner | Password: owner123
INSERT OR IGNORE INTO admins (username, password_hash, role)
VALUES ('owner', '$2b$12$vY/fMBtJwR5O5mXBLnVmV.OAi739jI1/ppzn0iLMxsdl4yW4r5JYi', 'owner');
