-- 0062_session_summary.sql
-- Session summary log + derived brief — two-tier session continuity.
--
-- The agent needs a PERSISTED, queryable session summary so a
-- warm-start / cold-start / resume can immediately know "where were we" without
-- re-traversing raw messages. Two tiers, mirroring the append-then-compact pattern:
--
--   TIER 1 — append-only log (`session_summary_log`):
--     Each turn-end (or cheap interval) appends a row summarizing the span
--     `from_msg_id → to_msg_id`. NEVER destructive — this is the lossless
--     source of truth. The `compacted` flag marks rows already absorbed into
--     the derived brief so tier-2 only ever re-chews the NEW rows.
--
--   TIER 2 — derived brief (`sessions.summary`):
--     The nudge boundary reads all `compacted = false` rows for a session,
--     condenses them (plus the volatile anchor) into ONE clean pointer,
--     overwrites `sessions.summary`, and marks those rows `compacted = true`.
--     Overwriting the DERIVED brief is fine (it should track CURRENT truth);
--     the append log is the lossless source that never drifts.
--
--   READ — warm-start / resume:
--     Fetch `sessions.summary` immediately (no nudge wait) so the agent has an
--     orientation pointer on the very turn it resumes. The agent can also query
--     the vault for the log — a true summary instead of traversing messages.
--
-- Additive + idempotent; safe to re-run. The base schema (`_schema_pg.sql`) is
-- intentionally NOT edited — fresh DBs get these objects by running migrations
-- in order, matching the 0055 agent-digest precedent.

-- ── Derived brief on sessions ──────────────────────────────────────────
ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS summary text;

COMMENT ON COLUMN sessions.summary IS
    'Derived session brief (tier-2 of two-tier continuity). Condensed from '
    'session_summary_log rows (plus the volatile anchor) at the nudge boundary. '
    'Overwritten freely to track CURRENT truth; the append log is the lossless '
    'source. Fetched on warm-start / resume so the agent has an orientation '
    'pointer without re-traversing raw messages.';

-- ── Append-only summary log ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.session_summary_log (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id   text NOT NULL,
    from_msg_id  bigint,        -- messages.id the chunk starts at (provenance)
    to_msg_id    bigint,        -- messages.id the chunk ends at   (provenance)
    content      text NOT NULL, -- the appended summary of this span (tier-1)
    compacted    boolean NOT NULL DEFAULT false,  -- absorbed into sessions.summary yet?
    created_at   timestamp with time zone NOT NULL DEFAULT now()
);

-- Fast SELECT for tier-2 recompact: uncompacted rows for one session.
CREATE INDEX IF NOT EXISTS session_summary_log_pending_idx
    ON public.session_summary_log (session_id, id)
    WHERE compacted IS NOT TRUE;

-- Fast lookup for warm-start / vault reads.
CREATE INDEX IF NOT EXISTS session_summary_log_session_idx
    ON public.session_summary_log (session_id);

-- Descriptive comments so the memory-vault prompt and schema map surface
-- what each column is for (agents read these to understand the table).
COMMENT ON TABLE public.session_summary_log IS
    'Append-only session summary log: tier-1 of two-tier session continuity. '
    'Each row summarizes a message span (from_msg_id to to_msg_id); never '
    'destructive. The compacted flag marks rows already condensed into '
    'sessions.summary (tier-2) so recompact only chews new rows. The agent '
    'reads this for a true session summary instead of traversing messages.';

COMMENT ON COLUMN public.session_summary_log.id IS
    'Primary key.';
COMMENT ON COLUMN public.session_summary_log.session_id IS
    'FK to sessions(id) — the session this summary chunk belongs to.';
COMMENT ON COLUMN public.session_summary_log.from_msg_id IS
    'messages.id the summarized span starts at (provenance, not a hard FK).';
COMMENT ON COLUMN public.session_summary_log.to_msg_id IS
    'messages.id the summarized span ends at (provenance, not a hard FK).';
COMMENT ON COLUMN public.session_summary_log.content IS
    'The appended summary of this span (tier-1 write). Lossless source.';
COMMENT ON COLUMN public.session_summary_log.compacted IS
    'True once this row has been absorbed into sessions.summary (tier-2).';
COMMENT ON COLUMN public.session_summary_log.created_at IS
    'When this summary chunk was appended.';

-- Reversible:
--   ALTER TABLE sessions DROP COLUMN IF EXISTS summary;
--   DROP TABLE IF EXISTS public.session_summary_log;
