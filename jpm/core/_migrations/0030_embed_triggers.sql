-- 0030_embed_triggers.sql
-- pg_notify triggers that drive the real-time embed listener (embed_listener.py).
--
-- Why: embed_listener is LISTEN/NOTIFY driven. When a row is INSERTed or
-- UPDATEd with embedding IS NULL, a trigger fires pg_notify('embed_queue',
-- 'table:id') so the listener embeds that row immediately (ms latency).
-- Without these triggers the listener never hears about new data and stays
-- idle forever — a SILENT no-op, the exact footgun we've been eliminating.
--
-- The embedding rollout doc references these as
-- "part of migration 0029". Since 0029 is already applied/committed, these
-- ship as a follow-on migration (0030) so existing nodes AND fresh ones get
-- them automatically on next restart via the migration runner.
--
-- Contract (must match embed_listener.py exactly):
--   * channel:  embed_queue
--   * payload:  '<table>:<id>'  — listener partitions on the FIRST ':'.
--               id is cast to text because sessions.id is uuid while the
--               others are bigint.
--   * fire on:  INSERT or UPDATE where embedding IS NULL (only newly-added
--               rows need embedding; already-embedded rows are skipped by
--               the listener anyway, but this keeps NOTIFYs cheap).
--   * optional LOW_PRIV role 'embedder' (created below) — the listener uses
--     it if present, else falls back to the app user. Non-blocking either way.
--
-- Idempotent via IF NOT EXISTS / OR REPLACE / DROP ... IF EXISTS — safe on
-- any node, including ones that partially applied it.

-- 1. Low-privilege embedder role (optional but recommended): a role that can
--    read the embeddable columns and UPDATE the embedding columns, but nothing
--    else. The listener prefers it when present. Idempotent.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'embedder') THEN
        CREATE ROLE embedder NOLOGIN;
    END IF;
END
$$;

-- Grant read on the tables + write on the embedding columns. The app user
-- (postgres/owner) retains full control; embedder is strictly scoped.
GRANT USAGE ON SCHEMA public TO embedder;
GRANT SELECT ON TABLE public.knowledge   TO embedder;
GRANT SELECT ON TABLE public.messages    TO embedder;
GRANT SELECT ON TABLE public.sessions    TO embedder;
GRANT SELECT ON TABLE public.reflections TO embedder;
GRANT SELECT ON TABLE public.patterns    TO embedder;
GRANT UPDATE (embedding, embedding_model, embedding_updated_at)
    ON TABLE public.knowledge TO embedder;
GRANT UPDATE (embedding, embedding_model, embedding_updated_at)
    ON TABLE public.messages TO embedder;
GRANT UPDATE (embedding, embedding_model, embedding_updated_at)
    ON TABLE public.sessions TO embedder;
GRANT UPDATE (embedding, embedding_model, embedding_updated_at)
    ON TABLE public.reflections TO embedder;
GRANT UPDATE (embedding, embedding_model, embedding_updated_at)
    ON TABLE public.patterns TO embedder;

-- imgen_library / skills may not exist on every node, AND may not have the
-- embedding columns (0029 only adds them to the 5 retrieval tables). Both
-- the table and the column are guarded.
DO $$
BEGIN
    IF to_regclass('public.imgen_library') IS NOT NULL
       AND EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='imgen_library'
                     AND column_name='embedding') THEN
        EXECUTE 'GRANT SELECT ON TABLE public.imgen_library TO embedder';
        EXECUTE 'GRANT UPDATE (embedding, embedding_model, embedding_updated_at)
                 ON TABLE public.imgen_library TO embedder';
    END IF;
    IF to_regclass('public.skills') IS NOT NULL
       AND EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='skills'
                     AND column_name='embedding') THEN
        EXECUTE 'GRANT SELECT ON TABLE public.skills TO embedder';
        EXECUTE 'GRANT UPDATE (embedding, embedding_model, embedding_updated_at)
                 ON TABLE public.skills TO embedder';
    END IF;
END
$$;

-- 2. Trigger function — one shared function emits the NOTIFY.
--    Payload is '<table>:<id>' with the id cast to text (uuid or bigint both
--    work). Fires only when embedding IS NULL so we don't spam the queue for
--    rows that are already embedded.
CREATE OR REPLACE FUNCTION public.notify_embed_queue()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.embedding IS NULL THEN
        PERFORM pg_notify('embed_queue', TG_TABLE_NAME || ':' || NEW.id::text);
    END IF;
    RETURN NEW;
END;
$$;

-- 3. Triggers on every retrieval table (matching TABLE_COLUMNS in the listener).
--    imgen_library / skills may not exist on every node — guards included.

-- knowledge
DROP TRIGGER IF EXISTS trg_knowledge_embed_notify ON public.knowledge;
CREATE TRIGGER trg_knowledge_embed_notify
    AFTER INSERT OR UPDATE ON public.knowledge
    FOR EACH ROW EXECUTE FUNCTION public.notify_embed_queue();

-- messages
DROP TRIGGER IF EXISTS trg_messages_embed_notify ON public.messages;
CREATE TRIGGER trg_messages_embed_notify
    AFTER INSERT OR UPDATE ON public.messages
    FOR EACH ROW EXECUTE FUNCTION public.notify_embed_queue();

-- sessions
DROP TRIGGER IF EXISTS trg_sessions_embed_notify ON public.sessions;
CREATE TRIGGER trg_sessions_embed_notify
    AFTER INSERT OR UPDATE ON public.sessions
    FOR EACH ROW EXECUTE FUNCTION public.notify_embed_queue();

-- reflections
DROP TRIGGER IF EXISTS trg_reflections_embed_notify ON public.reflections;
CREATE TRIGGER trg_reflections_embed_notify
    AFTER INSERT OR UPDATE ON public.reflections
    FOR EACH ROW EXECUTE FUNCTION public.notify_embed_queue();

-- patterns
DROP TRIGGER IF EXISTS trg_patterns_embed_notify ON public.patterns;
CREATE TRIGGER trg_patterns_embed_notify
    AFTER INSERT OR UPDATE ON public.patterns
    FOR EACH ROW EXECUTE FUNCTION public.notify_embed_queue();

-- imgen_library (guarded — not on every node)
DO $$
BEGIN
    IF to_regclass('public.imgen_library') IS NOT NULL THEN
        EXECUTE 'DROP TRIGGER IF EXISTS trg_imgen_library_embed_notify ON public.imgen_library';
        EXECUTE 'CREATE TRIGGER trg_imgen_library_embed_notify
                 AFTER INSERT OR UPDATE ON public.imgen_library
                 FOR EACH ROW EXECUTE FUNCTION public.notify_embed_queue()';
    END IF;
END
$$;

-- skills (guarded)
DO $$
BEGIN
    IF to_regclass('public.skills') IS NOT NULL THEN
        EXECUTE 'DROP TRIGGER IF EXISTS trg_skills_embed_notify ON public.skills';
        EXECUTE 'CREATE TRIGGER trg_skills_embed_notify
                 AFTER INSERT OR UPDATE ON public.skills
                 FOR EACH ROW EXECUTE FUNCTION public.notify_embed_queue()';
    END IF;
END
$$;
