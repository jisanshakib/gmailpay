-- ==========================================================================
--  Gmail Bot — Complete PostgreSQL Schema for Supabase
--  Copy-paste this entire file into Supabase SQL Editor and run once.
-- ==========================================================================

-- ==========================================================================
--  CORE TABLES
-- ==========================================================================

-- Users (Telegram bot users)
CREATE TABLE IF NOT EXISTS users (
    telegram_id            BIGINT PRIMARY KEY,
    username               TEXT,
    main_balance           DOUBLE PRECISION DEFAULT 0.0,
    pending_balance        DOUBLE PRECISION DEFAULT 0.0,
    total_completed_gmails INTEGER DEFAULT 0,
    total_strikes          INTEGER DEFAULT 0,
    is_banned              BOOLEAN DEFAULT FALSE,
    block_until            TIMESTAMPTZ,
    created_at             TIMESTAMPTZ DEFAULT NOW()
);

-- Admins (Dashboard login accounts)
CREATE TABLE IF NOT EXISTS admins (
    id            SERIAL PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK(role IN ('owner','admin'))
);

-- Bot Settings (key-value config)
CREATE TABLE IF NOT EXISTS bot_settings (
    key_name  TEXT PRIMARY KEY,
    key_value TEXT
);

-- Withdrawals
CREATE TABLE IF NOT EXISTS withdrawals (
    id               SERIAL PRIMARY KEY,
    telegram_id      BIGINT NOT NULL REFERENCES users(telegram_id),
    method           TEXT NOT NULL,
    wallet_or_number TEXT NOT NULL,
    amount           DOUBLE PRECISION NOT NULL,
    status           TEXT DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
    requested_at     TIMESTAMPTZ DEFAULT NOW()
);

-- ==========================================================================
--  GMAIL FARMING TABLES
-- ==========================================================================

-- Gmail Pool (admin uploads accounts here, bot assigns to users)
CREATE TABLE IF NOT EXISTS gmail_pool (
    id             SERIAL PRIMARY KEY,
    email          TEXT UNIQUE NOT NULL,
    password       TEXT NOT NULL,
    recovery_email TEXT,
    is_assigned    BOOLEAN DEFAULT FALSE
);

-- Submissions (users submit completed accounts for review)
CREATE TABLE IF NOT EXISTS submissions (
    id              SERIAL PRIMARY KEY,
    telegram_id     BIGINT NOT NULL REFERENCES users(telegram_id),
    submission_type TEXT NOT NULL CHECK(submission_type IN ('normal','2fa')),
    email           TEXT UNIQUE NOT NULL,
    password        TEXT NOT NULL,
    secret_key_2fa  TEXT,
    status          TEXT DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
    submitted_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ==========================================================================
--  DEFAULT SETTINGS
-- ==========================================================================

INSERT INTO bot_settings (key_name, key_value) VALUES
    ('banner_image_url', ''),
    ('bot_description', 'Welcome to Gmail Bot! Complete tasks and earn rewards.'),
    ('news_channel', ''),
    ('support_username', ''),
    ('normal_rate', '0.30'),
    ('two_fa_rate', '0.50'),
    ('ref_bonus', '0.10'),
    ('min_withdrawal', '5.00')
ON CONFLICT (key_name) DO NOTHING;

-- ==========================================================================
--  OWNER ACCOUNT (first login)
--  Username: owner
--  Password: owner123
--  bcrypt hash: $2b$12$vY/fMBtJwR5O5mXBLnVmV.OAi739jI1/ppzn0iLMxsdl4yW4r5JYi
-- ==========================================================================

INSERT INTO admins (username, password_hash, role) VALUES (
    'owner',
    '$2b$12$vY/fMBtJwR5O5mXBLnVmV.OAi739jI1/ppzn0iLMxsdl4yW4r5JYi',
    'owner'
) ON CONFLICT (username) DO NOTHING;

-- ==========================================================================
--  INDEXES (performance)
-- ==========================================================================

CREATE INDEX IF NOT EXISTS idx_submissions_status ON submissions(status);
CREATE INDEX IF NOT EXISTS idx_submissions_telegram_id ON submissions(telegram_id);
CREATE INDEX IF NOT EXISTS idx_withdrawals_status ON withdrawals(status);
CREATE INDEX IF NOT EXISTS idx_withdrawals_telegram_id ON withdrawals(telegram_id);
CREATE INDEX IF NOT EXISTS idx_gmail_pool_assigned ON gmail_pool(is_assigned);
