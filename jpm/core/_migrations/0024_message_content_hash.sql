-- Migration 0024: Content-hash dedup for messages
--
-- Schema: public
--
-- Changes:
--   public.messages.content_hash  — md5(content) for idempotent dedup
--   public.messages_session_content_idx — UNIQUE (session_id, content_hash)
--
-- Design:
--   - Warm-start replay stamps the DB's real message_id back onto loaded
--     messages (fix in joshaico_state.get_messages_tail), so the existing
--     (session_id, message_id) index catches re-inserts. But if a message is
--     genuinely re-persisted with a NEW message_id (e.g. a flush path that
--     didn't stamp _msg_id), content-hash is the authoritative signal.
--   - content_hash is NULL when content is NULL/empty so the unique index
--     only guards non-empty rows (empty streaming placeholders must never
--     collide — matches the empty-assistant guard in append_message).
--   - Postgres treats NULLs as distinct in unique indexes by default, so a
--     plain UNIQUE (session_id, content_hash) ignores empty/NULL content.
--
-- Idempotent: safe to re-run (dedup + index creation both guard on state).

-- 1. Add the content_hash column if missing.
ALTER TABLE public.messages
    ADD COLUMN IF NOT EXISTS content_hash text;

-- 2. Backfill for existing non-empty rows (idempotent UPDATE of NULLs only).
UPDATE public.messages
SET content_hash = MD5(content)
WHERE content IS NOT NULL
  AND content != ''
  AND (content_hash IS NULL OR content_hash = '');

-- 3. Dedup BEFORE creating the unique index — otherwise the index creation
--    fails on existing duplicate (session_id, content_hash) groups. Keep the
--    lowest id per group (first written = the "real" row), matching the
--    strategy of scripts/dedup_messages.py. Scope to non-empty, ACTIVE rows
--    only — mirroring the partial index predicate. This guarantees the kept
--    row is always the canonical live message (never deletes a live copy in
--    favor of an archived one), and archived copies (active=0) are left alone
--    since they don't participate in the unique index anyway.
DELETE FROM public.messages
WHERE active = 1
  AND content IS NOT NULL AND content != ''
  AND id NOT IN (
    SELECT MIN(id)
    FROM public.messages
    WHERE active = 1
      AND content IS NOT NULL AND content != ''
    GROUP BY session_id, content_hash
);

-- 4. Unique index on (session_id, content_hash) for non-empty content.
--    Partial predicate: only ACTIVE (active=1) rows participate. Compaction /
--    archive paths soft-archive rows (active=0) but keep them; re-inserting
--    the same content later must NOT collide with an archived copy. Deduping
--    only live rows is the correct semantic — a real duplicate is always
--    active, and archived rows aren't candidates for re-insertion conflicts.
CREATE UNIQUE INDEX IF NOT EXISTS messages_session_content_idx
    ON public.messages (session_id, content_hash)
    WHERE active = 1;
