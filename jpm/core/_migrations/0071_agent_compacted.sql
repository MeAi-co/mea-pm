-- Agent-digest compressor marker — its OWN column, separate from `compacted`.
--
-- `compacted` is owned by the context compressor (archive_and_compact) and is
-- ALSO the warm-start replay gate (`active = 1 OR compacted = 1`). Overloading
-- it for the agent-digest compressor conflates two different meanings:
--   * "archived out of live context"  (compaction)
--   * "content rewritten to a gist"   (digest)
-- and stamping it on rows the digest touched re-exposes them through the OR
-- gate. This column gives the agent-digest compressor a dedicated durable
-- marker so the two subsystems stop fighting — mirrors
-- 0069_flow_summarized_at.sql for the tool-flow summarizer.
--
-- Semantics:
--   agent_compacted = 1  -> this assistant row's `content` is a recomputed
--                           gist; `content_original` holds the full text.
--                           `active` / `compacted` are NOT touched, so the
--                           row still replays (as a gist) and stays searchable.
--   agent_compacted = 0  -> untouched.
--
-- This is additive and idempotent. `is_digest` / `summarized_at` (migration
-- 0055) are retained for back-compat readers (agent_anchor, backfill script);
-- `agent_compacted` is the canonical dedup marker going forward.

ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS agent_compacted integer NOT NULL DEFAULT 0;

-- Partial index: the digest's candidate scan (un-digested live finals).
CREATE INDEX IF NOT EXISTS messages_agent_digest_pending_idx
    ON messages (session_id, id)
    WHERE role = 'assistant' AND agent_compacted = 0;
