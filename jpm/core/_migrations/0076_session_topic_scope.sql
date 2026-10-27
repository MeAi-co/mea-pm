-- 0076_session_topic_scope.sql
-- Topic/thread scope on public.sessions: the columns existed in _schema_pg.sql's
-- tail on some nodes but were never written by anything, and the mea_sessions
-- mirror's INSERT listed 9 columns only (id, source, model, title,
-- message_count, parent_session_id, started_at, chat_type, session_key), so
-- chat_id / thread_id / chat_topic arrived NULL on all 145 rows.
--
-- WHY THIS MATTERS: PG is the operational agentic memory. Core Hermes already
-- writes chat_id/thread_id/display_name and origin_json->>'chat_topic' to
-- SQLite on every session upsert; without those values in PG, recall cannot
-- scope by conversation topic and two Telegram DMs are indistinguishable.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS + CREATE ... IF NOT EXISTS are safe to
-- re-run on any node, including a fresh one where _schema_pg.sql already has
-- the columns.
--
-- NOTE: no backfill here. Data lives in SQLite, not PG, so the repair runs from
-- the plugin: mea_sessions/_backfill_topic_scope.py (wired into install.sh).

ALTER TABLE IF EXISTS public.sessions
    ADD COLUMN IF NOT EXISTS chat_id      text,
    ADD COLUMN IF NOT EXISTS thread_id    text,
    ADD COLUMN IF NOT EXISTS chat_topic   text,
    ADD COLUMN IF NOT EXISTS display_name text;

-- Scope lookup: "the session for this chat + thread", newest first.
CREATE INDEX IF NOT EXISTS sessions_chat_thread_idx
    ON public.sessions (chat_id, thread_id);

-- Topic lookup: "what was said in topic X". Partial, because the vast majority
-- of seed rows have no topic and a full index would be dead weight.
CREATE INDEX IF NOT EXISTS sessions_chat_topic_idx
    ON public.sessions (chat_topic)
    WHERE chat_topic IS NOT NULL AND chat_topic <> '';

-- Topic labels have no source column anywhere in core (SQLite has no chat_topic
-- column; the value only ever appears inside origin_json). This table is the
-- durable home for a (chat_id, thread_id) -> name mapping, so a label resolved
-- once is available to every later mirror pass and to recall filters.
CREATE TABLE IF NOT EXISTS public.session_topics (
    chat_id    text        NOT NULL,
    thread_id  text        NOT NULL DEFAULT '',
    platform   text        NOT NULL DEFAULT 'telegram',
    topic_name text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (chat_id, thread_id)
);

CREATE INDEX IF NOT EXISTS session_topics_name_idx
    ON public.session_topics (topic_name);
