-- Migration 0040: Restore content-hash dedup net (soft-archive, then index)
--
-- Schema: public
--
-- Context:
--   Commit b297671 re-created the content-hash unique index
--   (messages_session_content_idx) in _schema_pg.sql ONLY. Numbered
--   migration files are what actually run on an existing DB (base schema is
--   skipped once _schema_migrations exists), so the index never landed. This
--   migration applies it for real, and it also fixes the pre-existing live
--   duplicates that would otherwise make CREATE UNIQUE INDEX fail.
--
-- Why this is safe (vs 0037's original drop):
--   Migration 0037 dropped the content-hash index because a UNIQUE index can
--   raise UniqueViolationError, which run_agent.py classifies as PERMANENT
--   and uses to kill the whole session DB (_session_db = None). That crash
--   path is now NEUTRALIZED by commit b297671's write-path change: both
--   INSERT paths use TARGETLESS "ON CONFLICT DO NOTHING", which catches a
--   collision on ANY unique index (content_hash, msg_key, message_id) and
--   swallows it gracefully — never a unique_violation. So the index can come
--   back without re-introducing the silent-DB-kill.
--
--   Canned-marker caveat (documented, not fatal): the context compressor
--   rewrites DISTINCT tool messages to the SAME canned marker string
--   ("[Duplicate tool output — same content as a more recent call]"). Their
--   md5(content) collides. With DO NOTHING the second write is silently
--   dropped — which is CORRECT dedup semantics (that content IS redundant)
--   and cannot crash persistence anymore.
--
-- Changes:
--   1. Backfill content_hash for any non-empty rows missing it (idempotent).
--   2. Soft-archive (active=0) every active duplicate row, keeping exactly
--      one canonical row per (session_id, content_hash). The kept row
--      prefers finish_reason='stop' (turn boundary), then lowest id
--      (first written = preserves ordering). NOTHING is hard-deleted —
--      archived copies stay queryable and the partial index (active=1)
--      simply ignores them.
--   3. Create the partial unique index on active=1 AND content_hash IS NOT
--      NULL so it lands cleanly and matches the write-path predicate.
--
-- Idempotent: safe to re-run (backfill and index guard on state; the
-- soft-archive step re-targets only rows still active).

-- 1. Backfill content_hash for non-empty rows that don't have one.
UPDATE public.messages
SET content_hash = MD5(content)
WHERE content IS NOT NULL
  AND content != ''
  AND (content_hash IS NULL OR content_hash = '');

-- 2. Soft-archive duplicate active rows, keeping one canonical row per
--    (session_id, content_hash). Ordering: finish_reason='stop' first, then
--    lowest id (first-written wins, preserves message ordering). The rest
--    become active=0 — never deleted, so the no-hard-remove rule holds
--    and the partial index (active=1) won't see them.
UPDATE public.messages m
SET active = 0
WHERE m.active = 1
  AND m.content IS NOT NULL AND m.content != ''
  AND m.id NOT IN (
    SELECT keep_id
    FROM (
      SELECT DISTINCT ON (session_id, content_hash)
             id AS keep_id
      FROM public.messages
      WHERE active = 1
        AND content IS NOT NULL AND content != ''
      ORDER BY session_id, content_hash,
               (CASE WHEN finish_reason = 'stop' THEN 0 ELSE 1 END),
               id
    ) keep
  );

-- 3. Create the partial unique index — only ACTIVE rows with non-empty
--    content participate, matching migration 0024's original predicate and
--    the write path's "ON CONFLICT DO NOTHING". Idempotent.
CREATE UNIQUE INDEX IF NOT EXISTS messages_session_content_idx
    ON public.messages (session_id, content_hash)
    WHERE active = 1 AND content_hash IS NOT NULL;

-- Reversible (see migration 0037): DROP INDEX messages_session_content_idx;
