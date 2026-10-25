-- 0026_session_last_processed_msg_id.sql
-- Decouple the self-improvement cursor from the coaching table.
--
-- Previously last_msg_id lived on the coaching table, so:
--   - review_memory=True + review_skills=False never advanced the cursor
--     (no coaching rows written) -> memory extraction re-processed history
--     every turn.
--   - Empty/no-signal turns (total_writes == 0) never advanced the cursor
--     -> the same messages were re-sent to the LLM every turn.
--
-- This adds a session-level cursor so it advances regardless of write count
-- and regardless of which review flags are enabled.
ALTER TABLE public.sessions
    ADD COLUMN IF NOT EXISTS last_processed_msg_id bigint DEFAULT 0;
