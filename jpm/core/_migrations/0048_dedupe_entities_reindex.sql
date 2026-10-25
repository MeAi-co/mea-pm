-- Migration 0048: Dedupe entities + rebuild corrupted entities_name_key index
--
-- Schema: public
--
-- Problem:
--   The `entities` table has duplicate rows for the same name. The unique
--   index `entities_name_key` is CORRUPTED — it is missing entries, so
--   exact-match lookups (`WHERE name = ?`) silently return 0 rows even though
--   the data exists. This is what `_resolve_entity` hits: the
--   `INSERT ... ON CONFLICT DO NOTHING` conflict check doesn't fire (index
--   missing the entry), a duplicate row gets inserted, then the
--   `SELECT ... WHERE name = ?` returns empty and raises
--   `RuntimeError: entity '<name>' could not be resolved after upsert`.
--
--   The corruption is data-level, not code-level, so it must be repaired in
--   the DB. This migration:
--     1. Dedupes `entities` — keeps the canonical row (lowest entity_id) per
--        name, remaps `fact_entities` links from the dup rows to the canonical
--        row, then deletes the dup rows.
--     2. REINDEXes `entities_name_key` — currently fails on the duplicate rows;
--        succeeds once the table is clean, restoring exact-match lookups.
--
--   CRITICAL: the dedupe DELETEs must target rows by `entity_id` (the PK index,
--   which is healthy), NOT by `name` (the corrupted index). A `WHERE name = ?`
--   predicate on the corrupted index returns 0 rows, so the delete silently
--   does nothing and the REINDEX still fails. This is why a naive name-based
--   dedupe fails on a genuinely corrupted index but passes on a clean one.
--
--   The whole thing runs in ONE atomic DO block (single statement) so the
--   migration runner applies it as one unit. It takes an ACCESS EXCLUSIVE lock
--   on entities + fact_entities so a concurrently-running gateway cannot slip a
--   duplicate in between the dedupe and the reindex (the race that broke a
--   naive two-step version).
--
-- Idempotent: if a node has no corruption, the dedupe loop is a no-op (no
-- duplicate names) and the REINDEX is a no-op on a valid index. Safe to run on
-- every fleet node.
--
-- NOTE: each fleet node runs its OWN local PostgreSQL (JPM_PG_HOST=127.0.0.1),
-- so this migration must run per-node.

DO $$
DECLARE
    r RECORD;
    dup_ids BIGINT[];
BEGIN
    -- Block concurrent writes so the dedupe + reindex are atomic.
    LOCK TABLE public.entities IN ACCESS EXCLUSIVE MODE;
    LOCK TABLE public.fact_entities IN ACCESS EXCLUSIVE MODE;

    -- Force seq scans for the whole block. The corrupted name index can
    -- silently miss rows (that's the bug), so any plan that touches it —
    -- including a GROUP BY that might use it for aggregation — is unsafe.
    -- Reading the heap directly is immune to the corruption.
    SET LOCAL enable_indexscan = off;
    SET LOCAL enable_bitmapscan = off;

    -- 1. Dedupe entities + remap fact_entities links.
    --    Collect dup entity_ids via a seq-scan GROUP BY (immune to the
    --    corrupted name index), then operate by entity_id (PK index).
    FOR r IN
        SELECT name, MIN(entity_id) AS keep_id,
               ARRAY_AGG(entity_id ORDER BY entity_id) AS all_ids
        FROM public.entities
        GROUP BY name
        HAVING COUNT(*) > 1
    LOOP
        -- All ids except the canonical (lowest) one are dups.
        dup_ids := ARRAY(
            SELECT x FROM unnest(r.all_ids) AS x WHERE x <> r.keep_id
        );

        IF dup_ids IS NOT NULL AND array_length(dup_ids, 1) > 0 THEN
            -- Remap links from dup rows to the canonical row, skipping facts
            -- the canonical row is already linked to (avoids duplicate
            -- fact_entities).
            UPDATE public.fact_entities fe
            SET entity_id = r.keep_id
            WHERE fe.entity_id = ANY(dup_ids)
            AND NOT EXISTS (
                SELECT 1 FROM public.fact_entities fe2
                WHERE fe2.fact_id = fe.fact_id AND fe2.entity_id = r.keep_id
            );

            -- Delete any remaining links pointing at a dup entity.
            DELETE FROM public.fact_entities fe
            WHERE fe.entity_id = ANY(dup_ids);

            -- Delete the dup entity rows (by PK, not by the corrupted name
            -- index).
            DELETE FROM public.entities e
            WHERE e.entity_id = ANY(dup_ids);
        END IF;
    END LOOP;

    -- 2. Rebuild the corrupted unique index. Atomic with the dedupe, so no
    --    concurrent write can slip a duplicate in between.
    IF EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE schemaname = 'public' AND tablename = 'entities'
          AND indexname = 'entities_name_key'
    ) THEN
        REINDEX INDEX public.entities_name_key;
    END IF;

    -- 3. Drop the redundant non-unique idx_entities_name if present. This is
    --    the index the planner actually used for exact-match lookups, and it
    --    was the corrupted one (returned 0 rows for existing data). The unique
    --    entities_name_key covers the same lookups, so idx_entities_name is
    --    pure redundancy — and a corrupted copy of it breaks _resolve_entity.
    DROP INDEX IF EXISTS public.idx_entities_name;
END $$;

-- Reversible: no — this is a destructive dedupe. A full DB backup should be
-- taken before running (see /root/db-backups/).
