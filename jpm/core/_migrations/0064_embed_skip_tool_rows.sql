-- 0064_embed_skip_tool_rows.sql
-- Stop embedding raw tool output and intermediate assistant narration.
-- Only user rows and completed assistant turns carry rich
-- semantic signal. Raw tool results are embedded and then DELETED by the
-- tool-flow summarizer seconds later; intermediate assistant narration is
-- similarly transient. Embedding them burns an embed call + two writes on a
-- row that is noise by design.
--
-- WHAT COUNTS AS KEEP (messages):
--   role='user'                                  -> durable, signal-rich
--   role='system'                                -> durable
--   role='assistant' AND finish_reason='stop'    -> the real final answer
-- EVERYTHING ELSE on messages is SKIPPED:
--   role='tool' (raw output AND tool_flow_summary process logs) -> noise
--   role='assistant' AND finish_reason='tool_calls' -> interstitial narration
--   role='assistant' AND finish_reason IN ('length','incomplete') -> aborted
--   role='assistant' AND finish_reason IS NULL   -> polluted bucket (44% exact
--        replay-dupes of stop rows); its unique finals are rare and the raw
--        content stays FTS-searchable, so we drop the whole bucket
--   role='session_meta'                          -> metadata, no conversation signal
--
-- (tool_flow_summary is a process log of tool calls + reasoning fragments,
-- not the answer; the final assistant stop row already carries the outcome.)
--
-- WHY A FILTER IN notify_embed_queue() AND NOT JUST A TRIGGER WHEN-CLAUSE:
-- this is the AFTER-notify trigger. A WHEN clause that excludes a row means the
-- sweep (which selects `embedding IS NULL`) would still pick it up and embed it
-- anyway. Skipping the notify only helps if the sweep ALSO skips the row, which
-- is handled by the companion code change in embed_listener.py / sweep_embeddings.py.
-- This migration is the DB half; the two Python sweeps are the other half.
--
-- NON-DESTRUCTIVE: existing embeddings are left in place. We only stop NEW
-- embeddings on the skipped surface. If the backlog should later be dropped,
-- that is a separate deliberate null-out.
--
-- SCOPE: applies to ANY table with a trigger calling notify_embed_queue()
-- (knowledge, sessions, reflections, patterns, skills, imgen_library) — those
-- have no role column, so the filter is a no-op for them. Only messages is
-- affected.

-- The runner's SQL splitter only understands $$ and $_$. Use $$ for the outer
-- body and $_$ for the inner EXECUTE string (see the pgvector-semantic-search
-- skill: a named tag like $fn$ is invisible to _split_sql_statements and the
-- migration splits mid-body on a fresh node).
CREATE OR REPLACE FUNCTION public.notify_embed_queue()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    skip boolean := false;
BEGIN
    -- Only the messages table is filtered. Every other embedded table
    -- (knowledge, sessions, reflections, patterns, skills, imgen_library) has
    -- no role/finish_reason columns and falls straight through unfiltered.
    -- Keyed on TG_TABLE_NAME, NOT an information_schema probe: this function
    -- runs once per message INSERT on the hot path, and a catalog lookup per
    -- row is pure overhead.
    IF TG_TABLE_NAME = 'messages' THEN
        IF NEW.role IN ('user', 'system') THEN
            skip := false;
        ELSIF NEW.role = 'assistant' THEN
            -- only completed final answers (finish_reason IS DISTINCT FROM
            -- 'stop' is null-safe: blank/replay rows are skipped)
            skip := (NEW.finish_reason IS DISTINCT FROM 'stop');
        ELSE
            -- tool (raw output AND tool_flow_summary process logs),
            -- session_meta, and any other role: no rich conversation signal
            skip := true;
        END IF;
    END IF;

    IF NEW.embedding IS NULL AND NOT skip THEN
        PERFORM pg_notify('embed_queue', TG_TABLE_NAME || ':' || NEW.id::text);
    END IF;
    RETURN NEW;
END;
$$;

-- Recreate the messages AFTER trigger so it picks up the new function body.
-- (CREATE OR REPLACE FUNCTION already updates all callers, but recreate the
-- trigger to be explicit and to drop the legacy duplicate trigger name.)
DROP TRIGGER IF EXISTS trg_messages_embed_notify ON public.messages;
CREATE TRIGGER trg_messages_embed_notify
    AFTER INSERT OR UPDATE ON public.messages
    FOR EACH ROW EXECUTE FUNCTION public.notify_embed_queue();
