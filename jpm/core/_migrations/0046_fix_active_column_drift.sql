-- Migration 0046: Fix active column drift — NULL-active rows + missing default
--
-- Schema: public
--
-- Problem:
--   The base schema (_schema_pg.sql) declares `active integer DEFAULT 1 NOT NULL`,
--   but the LIVE table has `active` as nullable with NO default. append_message()
--   never sets `active` explicitly, so every live-transcript row is written with
--   active = NULL instead of active = 1.
--
--   Every read path (get_messages, get_messages_as_conversation, get_messages_tail,
--   search_messages) filters `active = 1` by default. NULL-active rows are therefore
--   INVISIBLE to live-context loads and to search. The current live session has
--   ~220 rows, ALL active = NULL — on a gateway restart the warm-start tail would
--   return zero messages and the agent would lose its transcript.
--
--   The unique dedup index (messages_session_content_idx) is partial on
--   `active = 1`, so NULL-active rows also bypass dedup entirely.
--
-- Fix:
--   1. Backfill active for existing NULL rows:
--        - active IS NULL AND compacted = 1  -> active = 0  (archived coach rows)
--        - active IS NULL AND (compacted IS NULL OR compacted = 0) -> active = 1
--          (live transcript rows)
--   2. Set the column default to 1 and NOT NULL so future append_message writes
--      land as active = 1, matching the base schema.
--
-- Idempotent: backfill only touches rows still active IS NULL; the ALTER is
-- guarded by a DO block that checks the current default.

-- 1a. Archived rows (compacted=1) that somehow have active=NULL -> active=0.
UPDATE public.messages
SET active = 0
WHERE active IS NULL AND compacted = 1;

-- 1b. Live transcript rows (compacted=0/NULL) with active=NULL -> active=1.
--     BUT: NULL-active rows bypassed the content-hash dedup index, so there may
--     be duplicate content among them. Soft-archive the dupes first (keep lowest
--     id) so the partial unique index (active=1) lands cleanly. This mirrors
--     migration 0040's soft-archive step — nothing is hard-deleted.
UPDATE public.messages m
SET active = 0
WHERE m.active IS NULL
  AND (m.compacted IS NULL OR m.compacted = 0)
  AND m.content IS NOT NULL AND m.content != ''
  AND m.id NOT IN (
    SELECT keep_id
    FROM (
      SELECT DISTINCT ON (session_id, content_hash)
             id AS keep_id
      FROM public.messages
      WHERE active IS NULL
        AND (compacted IS NULL OR compacted = 0)
        AND content IS NOT NULL AND content != ''
      ORDER BY session_id, content_hash, id
    ) keep
  );

-- 1c. Remaining live transcript rows (compacted=0/NULL) with active=NULL -> active=1.
UPDATE public.messages
SET active = 1
WHERE active IS NULL AND (compacted IS NULL OR compacted = 0);

-- 2. Set default + NOT NULL to match the base schema, guarded so it only
--    applies when the column is still nullable / has no default.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'messages'
          AND column_name = 'active'
          AND (is_nullable = 'YES' OR column_default IS NULL)
    ) THEN
        ALTER TABLE public.messages
            ALTER COLUMN active SET DEFAULT 1,
            ALTER COLUMN active SET NOT NULL;
    END IF;
END $$;

-- Reversible: ALTER TABLE public.messages ALTER COLUMN active DROP NOT NULL,
--             ALTER COLUMN active DROP DEFAULT;
