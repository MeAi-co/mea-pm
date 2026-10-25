-- Tool-flow summarizer marker — separate from `compacted`.
--
-- `compacted` is owned by archive_and_compact (the context compressor) and means
-- "archived out of live context". The tool-flow summarizer previously reused it to
-- mean "collapsed into a summary", so once the compressor fired, the summarizer's
-- boundary/range queries (both gated on `compacted NOT IN (1)`) returned nothing and
-- it silently collapsed 0 rows — the missing 🧰 icon on nodes that compress every
-- turn (observed: 141k-146k tokens vs 131k context at threshold 0.9).
--
-- This column gives the summarizer its own dedup marker so the two subsystems stop
-- fighting. `summarized_at` is NOT reused: it belongs to the agent-digest compressor
-- (migration 0055_agent_digest_columns.sql).

ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS flow_summarized_at timestamptz;

-- Partial index: the summarizer's candidate scan (un-collapsed, live rows).
CREATE INDEX IF NOT EXISTS messages_flow_pending_idx
    ON messages (session_id, id)
    WHERE flow_summarized_at IS NULL AND active = 1;
