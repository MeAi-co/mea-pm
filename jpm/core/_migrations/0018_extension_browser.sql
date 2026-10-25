-- Migration 0018: Extension & Browser Orchestration schema (v2)
--
-- Schema: ext_api (dedicated namespace for extension/bridge tables)
--
-- Tables:
--   ext_api.tokens            — WebSocket auth tokens tied to specific agents
--   ext_api.domain_whitelist  — Per-token domain allowlist (deny by default)
--   ext_api.sessions          — Active browser session tracking
--   ext_api.tabs              — Multi-tab support per session
--   ext_api.credentials       — Encrypted credentials per domain
--   ext_api.session_log       — Every action with timestamps, results, errors
--   ext_api.user_confirmations — Pending user confirmation requests
--
-- Design principles:
--   - Deny by default: no domain whitelisted = no navigation allowed
--   - Encrypted credentials: passwords never in plaintext in DB or agent context
--   - Immutable audit trail: session_log is append-only
--   - Multi-tenant: tokens scoped to agents, sessions scoped to tokens

-- ── ext_api schema ──────────────────────────────────────────────────────

CREATE SCHEMA IF NOT EXISTS ext_api;

-- ── ext_api.tokens ──────────────────────────────────────────────────────
-- WebSocket auth tokens. One token per extension instance.
-- Tokens are hashed in storage; the raw token is returned once on creation.

CREATE TABLE IF NOT EXISTS ext_api.tokens (
    id              BIGSERIAL PRIMARY KEY,
    token_hash      TEXT NOT NULL UNIQUE,
    label           TEXT NOT NULL DEFAULT '',
    agent_name      TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at    TIMESTAMPTZ,
    revoked         BOOLEAN NOT NULL DEFAULT false,
    max_sessions    INTEGER NOT NULL DEFAULT 5
);

CREATE INDEX IF NOT EXISTS idx_ext_tokens_active
    ON ext_api.tokens (token_hash)
    WHERE revoked = false;

CREATE INDEX IF NOT EXISTS idx_ext_tokens_agent
    ON ext_api.tokens (agent_name)
    WHERE revoked = false;

-- ── ext_api.domain_whitelist ─────────────────────────────────────────────
-- Per-token domain allowlist. Only these domains can be navigated to.
-- Patterns: "canva.com", "*.google.com", "sheets.google.com"
-- Empty list = no domains allowed (deny by default).

CREATE TABLE IF NOT EXISTS ext_api.domain_whitelist (
    id              BIGSERIAL PRIMARY KEY,
    token_id        BIGINT NOT NULL REFERENCES ext_api.tokens(id) ON DELETE CASCADE,
    domain_pattern  TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by      TEXT NOT NULL DEFAULT 'agent'
);

CREATE INDEX IF NOT EXISTS idx_ext_whitelist_token
    ON ext_api.domain_whitelist (token_id);

-- ── ext_api.sessions ────────────────────────────────────────────────────
-- Active browser sessions. One session = one browser context (window).
-- A session can own multiple tabs.

CREATE TABLE IF NOT EXISTS ext_api.sessions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_id            BIGINT NOT NULL REFERENCES ext_api.tokens(id) ON DELETE CASCADE,
    agent_name          TEXT NOT NULL,
    ws_token_hash       TEXT NOT NULL UNIQUE,
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'terminated', 'timed_out', 'error')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_activity_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    terminated_at       TIMESTAMPTZ,
    termination_reason  TEXT NOT NULL DEFAULT '',
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_ext_sessions_active
    ON ext_api.sessions (agent_name, status)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_ext_sessions_ws_token
    ON ext_api.sessions (ws_token_hash);

CREATE INDEX IF NOT EXISTS idx_ext_sessions_token
    ON ext_api.sessions (token_id);

-- ── ext_api.tabs ─────────────────────────────────────────────────────────
-- Tabs within a session. The agent targets actions at a specific tab.

CREATE TABLE IF NOT EXISTS ext_api.tabs (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID NOT NULL REFERENCES ext_api.sessions(id) ON DELETE CASCADE,
    tab_index       INTEGER NOT NULL DEFAULT 0,
    label           TEXT NOT NULL DEFAULT '',
    url             TEXT NOT NULL DEFAULT '',
    title           TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'navigating', 'loading', 'idle', 'closed')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ext_tabs_session
    ON ext_api.tabs (session_id, tab_index);

-- ── ext_api.credentials ─────────────────────────────────────────────────
-- Encrypted credentials per domain. Passwords are encrypted at rest.
-- The agent never sees the raw password — it tells the orchestrator
-- "use credentials for canva.com" and the orchestrator decrypts + injects.

CREATE TABLE IF NOT EXISTS ext_api.credentials (
    id              BIGSERIAL PRIMARY KEY,
    domain          TEXT NOT NULL,
    username        TEXT NOT NULL DEFAULT '',
    username_field  TEXT NOT NULL DEFAULT 'email',
    password_field  TEXT NOT NULL DEFAULT 'password',
    encrypted_data  BYTEA NOT NULL,  -- AES-256-GCM encrypted JSON: {"password": "..."}
    encryption_kid  TEXT NOT NULL DEFAULT 'primary',  -- key identifier for rotation
    totp_secret     TEXT NOT NULL DEFAULT '',          -- base32 TOTP secret for 2FA
    label           TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (domain, username)
);

CREATE INDEX IF NOT EXISTS idx_ext_credentials_domain
    ON ext_api.credentials (domain);

-- ── ext_api.session_log ─────────────────────────────────────────────────
-- Immutable audit trail. Every action the agent commands and every result
-- the extension streams back. Append-only.

CREATE TABLE IF NOT EXISTS ext_api.session_log (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID NOT NULL REFERENCES ext_api.sessions(id) ON DELETE CASCADE,
    tab_id          BIGINT REFERENCES ext_api.tabs(id),
    action          TEXT NOT NULL,
    params          JSONB NOT NULL DEFAULT '{}'::jsonb,
    result          JSONB NOT NULL DEFAULT '{}'::jsonb,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'completed', 'failed', 'terminated', 'rate_limited')),
    error_message   TEXT NOT NULL DEFAULT '',
    page_url        TEXT NOT NULL DEFAULT '',
    page_title      TEXT NOT NULL DEFAULT '',
    duration_ms     INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ext_log_session
    ON ext_api.session_log (session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ext_log_status
    ON ext_api.session_log (status)
    WHERE status IN ('pending', 'running');

-- ── ext_api.user_confirmations ──────────────────────────────────────────
-- Pending user confirmation requests. When the agent wants to do something
-- sensitive (submit form, send message, make purchase), it creates a
-- confirmation request. The extension pops up a dialog. User approves/denies.

CREATE TABLE IF NOT EXISTS ext_api.user_confirmations (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID NOT NULL REFERENCES ext_api.sessions(id) ON DELETE CASCADE,
    action_id       BIGINT NOT NULL REFERENCES ext_api.session_log(id) ON DELETE CASCADE,
    action          TEXT NOT NULL,
    summary         TEXT NOT NULL,
    page_url        TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'denied', 'expired')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    responded_at    TIMESTAMPTZ,
    response_note   TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_ext_confirmations_pending
    ON ext_api.user_confirmations (session_id, status)
    WHERE status = 'pending';
