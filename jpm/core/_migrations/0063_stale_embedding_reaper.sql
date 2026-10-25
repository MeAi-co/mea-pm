-- 0063_stale_embedding_reaper.sql
-- Make stale-embedding self-healing across all nodes, without swarming the embedder.
--
-- Follow-on to the skills `_upsert_skill` fix (5148b4d). That
-- fix clears the vector in ONE write path (the skills upsert). Every OTHER write
-- path to an embedded table still leaves a stale-but-non-null vector that never
-- self-heals, because BOTH existing mechanisms are null-only:
--
--   * the AFTER trigger notify_embed_queue() opens with `IF NEW.embedding IS
--     NULL THEN pg_notify(...)` — a non-null-but-stale vector never notifies;
--   * the listener sweep predicate is `WHERE embedding IS NULL AND <ts> IS NULL`
--     — it only ever heals NULL, so stale-in-place rows are invisible to it.
--
-- The failure mode is STALE-BUT-NOT-NULL: undetectable by a null count. The
-- detection query is `updated_at > embedding_updated_at` (see the
-- pgvector-semantic-search skill). On skills this was 134/178 rows on Aug-7
-- vectors while bodies had been edited as recently as that morning.
--
-- FIX — the row-precise layer. A BEFORE UPDATE trigger that clears the three
-- embedding columns ONLY when the embedded text surface actually changed.
-- Clearing is a plain column write (no re-embed on the way in), so it cannot
-- swarm; it just makes the row NULL, which fires the EXISTING AFTER trigger,
-- which notifies, and the listener embeds that ONE row in ms.
--
-- CRITICAL: the trigger must NOT fire on counter-only writes. `skill_usage.
-- _upsert_record` runs `UPDATE public.skills SET use_count/view_count/
-- last_used_at ...` on EVERY successful skill_view. A naive
-- `updated_at > embedding_updated_at` lag sweep would mark every viewed skill
-- stale and re-embed it on every sweep — the exact swarm this migration avoids.
-- `IS DISTINCT FROM` on the TEXT columns (never a counter, never a timestamp)
-- is immune to that: it only fires when the text the embedding was built from
-- actually differs.
--
-- Deliberately scoped to skills and knowledge:
--   * skills    — the stale-drift case that keeps recurring (upsert + patch).
--   * knowledge — 4604 rows, the core retrieval surface, and its write path
--                 (`_upsert_knowledge`) is the same class of bug as skills'.
-- messages / reflections / patterns are effectively insert-only (their text is
-- never re-written in place — reflections: 0 rows differ from their embedding
-- timestamp), so a text-change guard adds nothing there. sessions is excluded
-- on purpose: title updates churn and its embedding is dominated by the
-- first-exchange subquery, so a title-only guard risks needless re-embeds.
--
-- DETECTION (run on any node, no null count can see this):
--   SELECT count(*) FROM skills WHERE updated_at > embedding_updated_at;
--
-- Additive + idempotent; safe to re-run. Fresh DBs get these objects by running
-- migrations in order (0061 precedent). Table + column existence is guarded so
-- a node missing an optional table is unaffected.
--
-- Tag note: the migration runner's statement splitter tracks exactly `$$` and
-- `$_$` — it does NOT understand named tags like `$fn$`. Use `$_$` for DO
-- bodies and `$$` for inner EXECUTE strings, or the runner splits mid-body.
--
-- ROLLBACK: DROP TRIGGER trg_<table>_clear_stale_embedding ON <table>; the
-- function clear_embedding_on_text_change() is harmless if left in place.

-- ── BEFORE UPDATE trigger function (shared) ──────────────────────────────
-- Each trigger carries its own WHEN clause naming the exact text surface.
CREATE OR REPLACE FUNCTION public.clear_embedding_on_text_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    -- Plain column writes: no embed here, no notify loop. Nulling the vector
    -- is what lets the existing AFTER trigger fire notify_embed_queue().
    NEW.embedding := NULL;
    NEW.embedding_model := NULL;
    NEW.embedding_updated_at := NULL;
    RETURN NEW;
END;
$$;

-- ── skills: text surface = name + description + content ──────────────────
-- (mirrors _upsert_skill's CASE and the listener's text_builder; fires on the
-- curator's patch path too, which the upsert CASE alone never covered)
DO $_$
BEGIN
    IF to_regclass('public.skills') IS NOT NULL
       AND EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='skills'
                     AND column_name='embedding') THEN
        EXECUTE 'DROP TRIGGER IF EXISTS trg_skills_clear_stale_embedding ON public.skills';
        EXECUTE $$
            CREATE TRIGGER trg_skills_clear_stale_embedding
            BEFORE UPDATE ON public.skills
            FOR EACH ROW
            WHEN ((OLD.name, OLD.description, OLD.content)
                  IS DISTINCT FROM (NEW.name, NEW.description, NEW.content))
            EXECUTE FUNCTION public.clear_embedding_on_text_change()
        $$;
    END IF;
END
$_$;

-- ── knowledge: text surface = name + description ─────────────────────────
DO $_$
BEGIN
    IF to_regclass('public.knowledge') IS NOT NULL
       AND EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='knowledge'
                     AND column_name='embedding') THEN
        EXECUTE 'DROP TRIGGER IF EXISTS trg_knowledge_clear_stale_embedding ON public.knowledge';
        EXECUTE $$
            CREATE TRIGGER trg_knowledge_clear_stale_embedding
            BEFORE UPDATE ON public.knowledge
            FOR EACH ROW
            WHEN ((OLD.name, OLD.description) IS DISTINCT FROM (NEW.name, NEW.description))
            EXECUTE FUNCTION public.clear_embedding_on_text_change()
        $$;
    END IF;
END
$_$;
