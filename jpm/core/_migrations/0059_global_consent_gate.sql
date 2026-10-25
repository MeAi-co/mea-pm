-- Migration 0059: Global consent gate for browser access
--
-- Schema: ext_api
--
-- Changes:
--   ext_api.consent — Single-row table tracking whether the user has granted
--     the agent browser access. The extension's toggle is the ONLY thing
--     that flips this. Toggle OFF = consent revoked = agent cannot create
--     sessions, period. Toggle ON = consent granted.
--
-- Design:
--   - The old model let the agent auto-provision a token and create a fresh
--     session even after the user toggled OFF (the toggle only terminated the
--     current session + disconnected the extension). The agent tool uses a
--     different agent_name than the extension, so revoking one token never
--     blocked the other.
--   - This table is the single source of truth. /api/v1/session/create checks
--     it and refuses while revoked. Toggle OFF revokes all tokens + terminates
--     all active sessions + sets granted=false. Toggle ON sets granted=true.
--
-- ── ext_api.consent ─────────────────────────────────────────────────────────
-- Single-row consent gate (id is always 1).

CREATE TABLE IF NOT EXISTS ext_api.consent (
    id          SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    granted     BOOLEAN NOT NULL DEFAULT true,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed the single row (idempotent).
INSERT INTO ext_api.consent (id, granted)
VALUES (1, true)
ON CONFLICT (id) DO NOTHING;
