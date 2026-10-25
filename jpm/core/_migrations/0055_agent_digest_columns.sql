-- Agent-Message Digest Compressor — new columns on `messages`.
-- Compress oversized ASSISTANT message CONTENT in place so the
-- rolling window stays lean, while preserving full fidelity:
--   - content_original : untouched full text, moved here before overwrite
--   - is_digest        : marks a row whose content is a recomputed summary
--   - summarized_at    : dedup guard, so the nudge summarizer never re-chews
--                        the same block (and never fires an LLM call on it again)
-- IDs, embeddings, content_hash, and search_vector are NOT touched by the
-- compressor — identity and semantic index stay faithful.

ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS content_original text,
    ADD COLUMN IF NOT EXISTS is_digest boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS summarized_at timestamptz;

-- Index so the candidate SELECT (un-digested oversized assistant rows) stays fast.
CREATE INDEX IF NOT EXISTS messages_digest_pending_idx
    ON messages (session_id, id)
    WHERE role = 'assistant' AND is_digest IS NOT TRUE AND summarized_at IS NULL;
