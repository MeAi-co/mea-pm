-- 0032_msg_key_hash_index.sql
-- Replace the integer (session_id, message_id) conflict key with a
-- deterministic content+position hash used as the idempotency index.
--
-- Problem (WSL hang / corrupted PG connection):
--   append_message serialized every write with
--   pg_advisory_xact_lock(session_id). On a connection that dies
--   mid-transaction, or when a stale backend holds the lock, the lock
--   acquisition blocks FOREVER -> the message flush never returns and the
--   agent hangs with "PG connection corrupted". The integer message_id
--   conflict key could not dedup safely without that lock (two concurrent
--   writers both compute MAX+1 and collide), so the lock was load-bearing.
--
-- Fix:
--   Add a msg_key column = md5(session_id || ':' || message_id). It is a
--   pure function of (session_id, counter), so two retries of the same
--   logical message produce the SAME key -> ON CONFLICT (session_id, msg_key)
--   DO NOTHING dedups deterministically with NO advisory lock. This lets us
--   drop the lock entirely and eliminates the hang.
--
--   The raw integer message_id is kept (callers and session-scoped counter
--   still use it) but is no longer the dedup arbiter.
--
-- Idempotent: safe to re-run.

-- 1. Add the msg_key column if missing.
ALTER TABLE public.messages
    ADD COLUMN IF NOT EXISTS msg_key text;

-- 2. Backfill for existing rows (idempotent UPDATE of NULLs only).
--    Deterministic: same formula as the code path.
UPDATE public.messages
SET msg_key = MD5(session_id || ':' || COALESCE(message_id::text, ''))
WHERE (msg_key IS NULL OR msg_key = '');

-- 3. Unique index on (session_id, msg_key) for live (active) rows only.
--    Partial predicate matches the content-hash index semantics: archived
--    copies (active=0) don't participate, so compaction/archive re-inserts
--    never collide with a soft-archived row.
CREATE UNIQUE INDEX IF NOT EXISTS messages_session_msg_key_idx
    ON public.messages (session_id, msg_key)
    WHERE active = 1;
