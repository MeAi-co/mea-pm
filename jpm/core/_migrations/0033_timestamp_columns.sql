-- ============================================================================
-- Migration 0033: Timestamp columns — Track A (hot path) duplicate-column dance
-- ============================================================================
-- GOAL: Convert epoch-float timestamp columns to `timestamp without time zone`
--       (MySQL DATETIME equivalent, system TZ, no TZ suffix) WITHOUT touching
--       the live column. Each hot table gets a `_new` column, backfilled from
--       its OWN stored value (row-by-row, NEVER now()), then the code writes
--       datetimes to `_new`. A later migration (0034) drops old + renames.
--
-- ORDERING: The DEFAULT CURRENT_TIMESTAMP and NOT NULL are applied
--       to the _new columns AFTER the backfill, NOT at column creation.
--       Adding a column with DEFAULT CURRENT_TIMESTAMP fires the default on
--       ALL existing rows at ALTER time (stamping 'now' on everything) and
--       makes the backfill no-op. So: add nullable no-default column ->
--       backfill from old -> THEN set default -> THEN set NOT NULL.
--
-- SAFETY: Every backfill is TYPE-AWARE. If the source column is already
--         `timestamp without time zone` (e.g. a node where 0034 already ran
--         and converted it, or a fresh schema that ships timestamps), copy
--         the value directly. Otherwise treat it as an epoch float and use
--         to_timestamp(col). This makes the migration idempotent across
--         fleet lineages and stops the "function to_timestamp(timestamp
--         without time zone) does not exist" retry loop on already-converted
--         nodes. NULLs are preserved (a NULL old value stays NULL in _new).
--         Each ADD COLUMN guarded by a column-existence check.
--
-- ERROR HANDLING: Each backfill runs inside a DO block with EXCEPTION
--         handling that RAISEs a clear, named error on failure. A final
--         verification block checks value equality (new = old or
--         to_timestamp(old), type-aware) AND NULL preservation, RAISEing
--         if any row is wrong.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- messages.timestamp (double precision epoch) -> timestamp
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name='messages'
                   AND column_name='timestamp_new') THEN
    ALTER TABLE messages ADD COLUMN timestamp_new timestamp;
  END IF;
END $$;

-- Drop NOT NULL on old messages.timestamp (new code writes timestamp_new instead)
DO $$
BEGIN
  ALTER TABLE messages ALTER COLUMN timestamp DROP NOT NULL;
EXCEPTION WHEN OTHERS THEN
  RAISE NOTICE '0033: messages.timestamp already nullable or error: %', SQLERRM;
END $$;

DO $$
DECLARE
  v_type text;
BEGIN
  SELECT data_type INTO v_type FROM information_schema.columns
  WHERE table_schema='public' AND table_name='messages' AND column_name='timestamp';
  IF v_type = 'timestamp without time zone' THEN
    UPDATE messages SET timestamp_new = timestamp WHERE timestamp IS NOT NULL;
  ELSE
    UPDATE messages SET timestamp_new = to_timestamp(timestamp) WHERE timestamp IS NOT NULL;
  END IF;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0033 backfill FAILED on messages.timestamp: %', SQLERRM;
END $$;

-- Apply default + NOT NULL AFTER backfill
DO $$
BEGIN
  ALTER TABLE messages ALTER COLUMN timestamp_new SET DEFAULT CURRENT_TIMESTAMP;
  ALTER TABLE messages ALTER COLUMN timestamp_new SET NOT NULL;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0033 post-backfill ALTER FAILED on messages.timestamp_new: %', SQLERRM;
END $$;

-- ---------------------------------------------------------------------------
-- sessions.started_at / ended_at / last_resume_marked_at (real epoch) -> timestamp
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name='sessions'
                   AND column_name='started_at_new') THEN
    ALTER TABLE sessions ADD COLUMN started_at_new timestamp;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name='sessions'
                   AND column_name='ended_at_new') THEN
    ALTER TABLE sessions ADD COLUMN ended_at_new timestamp;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name='sessions'
                   AND column_name='last_resume_marked_at_new') THEN
    ALTER TABLE sessions ADD COLUMN last_resume_marked_at_new timestamp;
  END IF;
END $$;

-- Drop NOT NULL on old sessions.started_at (new code writes started_at_new instead)
DO $$
BEGIN
  ALTER TABLE sessions ALTER COLUMN started_at DROP NOT NULL;
EXCEPTION WHEN OTHERS THEN
  RAISE NOTICE '0033: sessions.started_at already nullable or error: %', SQLERRM;
END $$;

DO $$
DECLARE
  v_type text;
BEGIN
  SELECT data_type INTO v_type FROM information_schema.columns
  WHERE table_schema='public' AND table_name='sessions' AND column_name='started_at';
  IF v_type = 'timestamp without time zone' THEN
    UPDATE sessions SET started_at_new = started_at WHERE started_at IS NOT NULL;
  ELSE
    UPDATE sessions SET started_at_new = to_timestamp(started_at) WHERE started_at IS NOT NULL;
  END IF;
  SELECT data_type INTO v_type FROM information_schema.columns
  WHERE table_schema='public' AND table_name='sessions' AND column_name='ended_at';
  IF v_type = 'timestamp without time zone' THEN
    UPDATE sessions SET ended_at_new = ended_at WHERE ended_at IS NOT NULL;
  ELSE
    UPDATE sessions SET ended_at_new = to_timestamp(ended_at) WHERE ended_at IS NOT NULL;
  END IF;
  SELECT data_type INTO v_type FROM information_schema.columns
  WHERE table_schema='public' AND table_name='sessions' AND column_name='last_resume_marked_at';
  IF v_type = 'timestamp without time zone' THEN
    UPDATE sessions SET last_resume_marked_at_new = last_resume_marked_at WHERE last_resume_marked_at IS NOT NULL;
  ELSE
    UPDATE sessions SET last_resume_marked_at_new = to_timestamp(last_resume_marked_at) WHERE last_resume_marked_at IS NOT NULL;
  END IF;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0033 backfill FAILED on sessions.*: %', SQLERRM;
END $$;

-- Apply default + NOT NULL AFTER backfill (only started_at_new is NOT NULL)
DO $$
BEGIN
  ALTER TABLE sessions ALTER COLUMN started_at_new SET DEFAULT CURRENT_TIMESTAMP;
  ALTER TABLE sessions ALTER COLUMN started_at_new SET NOT NULL;
  ALTER TABLE sessions ALTER COLUMN ended_at_new SET DEFAULT CURRENT_TIMESTAMP;
  ALTER TABLE sessions ALTER COLUMN last_resume_marked_at_new SET DEFAULT CURRENT_TIMESTAMP;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0033 post-backfill ALTER FAILED on sessions.*_new: %', SQLERRM;
END $$;

-- ---------------------------------------------------------------------------
-- knowledge.created_at (real epoch) / last_referenced (double precision epoch)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name='knowledge'
                   AND column_name='created_at_new') THEN
    ALTER TABLE knowledge ADD COLUMN created_at_new timestamp;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name='knowledge'
                   AND column_name='last_referenced_new') THEN
    ALTER TABLE knowledge ADD COLUMN last_referenced_new timestamp;
  END IF;
END $$;

DO $$
DECLARE
  v_type text;
BEGIN
  -- knowledge.created_at may not exist on older fleet schema lineages
  -- (fleet nodes predate this column). Guard the backfill on column
  -- existence so the migration is fleet-compatible.
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='knowledge'
               AND column_name='created_at') THEN
    SELECT data_type INTO v_type FROM information_schema.columns
    WHERE table_schema='public' AND table_name='knowledge' AND column_name='created_at';
    IF v_type = 'timestamp without time zone' THEN
      UPDATE knowledge SET created_at_new = created_at WHERE created_at IS NOT NULL;
    ELSE
      UPDATE knowledge SET created_at_new = to_timestamp(created_at) WHERE created_at IS NOT NULL;
    END IF;
  END IF;
  SELECT data_type INTO v_type FROM information_schema.columns
  WHERE table_schema='public' AND table_name='knowledge' AND column_name='last_referenced';
  IF v_type = 'timestamp without time zone' THEN
    UPDATE knowledge SET last_referenced_new = last_referenced WHERE last_referenced IS NOT NULL;
  ELSE
    UPDATE knowledge SET last_referenced_new = to_timestamp(last_referenced) WHERE last_referenced IS NOT NULL;
  END IF;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0033 backfill FAILED on knowledge.*: %', SQLERRM;
END $$;

DO $$
BEGIN
  ALTER TABLE knowledge ALTER COLUMN created_at_new SET DEFAULT CURRENT_TIMESTAMP;
  ALTER TABLE knowledge ALTER COLUMN last_referenced_new SET DEFAULT CURRENT_TIMESTAMP;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0033 post-backfill ALTER FAILED on knowledge.*_new: %', SQLERRM;
END $$;

-- ---------------------------------------------------------------------------
-- active.updated_at (double precision epoch)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name='active'
                   AND column_name='updated_at_new') THEN
    ALTER TABLE active ADD COLUMN updated_at_new timestamp;
  END IF;
END $$;

DO $$
DECLARE
  v_type text;
BEGIN
  SELECT data_type INTO v_type FROM information_schema.columns
  WHERE table_schema='public' AND table_name='active' AND column_name='updated_at';
  IF v_type = 'timestamp without time zone' THEN
    UPDATE active SET updated_at_new = updated_at WHERE updated_at IS NOT NULL;
  ELSE
    UPDATE active SET updated_at_new = to_timestamp(updated_at) WHERE updated_at IS NOT NULL;
  END IF;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0033 backfill FAILED on active.updated_at: %', SQLERRM;
END $$;

DO $$
BEGIN
  ALTER TABLE active ALTER COLUMN updated_at_new SET DEFAULT CURRENT_TIMESTAMP;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0033 post-backfill ALTER FAILED on active.updated_at_new: %', SQLERRM;
END $$;

-- ---------------------------------------------------------------------------
-- loops.created_at / resolved_at (double precision epoch)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name='loops'
                   AND column_name='created_at_new') THEN
    ALTER TABLE loops ADD COLUMN created_at_new timestamp;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name='loops'
                   AND column_name='resolved_at_new') THEN
    ALTER TABLE loops ADD COLUMN resolved_at_new timestamp;
  END IF;
END $$;

DO $$
DECLARE
  v_type text;
BEGIN
  SELECT data_type INTO v_type FROM information_schema.columns
  WHERE table_schema='public' AND table_name='loops' AND column_name='created_at';
  IF v_type = 'timestamp without time zone' THEN
    UPDATE loops SET created_at_new = created_at WHERE created_at IS NOT NULL;
  ELSE
    UPDATE loops SET created_at_new = to_timestamp(created_at) WHERE created_at IS NOT NULL;
  END IF;
  SELECT data_type INTO v_type FROM information_schema.columns
  WHERE table_schema='public' AND table_name='loops' AND column_name='resolved_at';
  IF v_type = 'timestamp without time zone' THEN
    UPDATE loops SET resolved_at_new = resolved_at WHERE resolved_at IS NOT NULL;
  ELSE
    UPDATE loops SET resolved_at_new = to_timestamp(resolved_at) WHERE resolved_at IS NOT NULL;
  END IF;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0033 backfill FAILED on loops.*: %', SQLERRM;
END $$;

DO $$
BEGIN
  ALTER TABLE loops ALTER COLUMN created_at_new SET DEFAULT CURRENT_TIMESTAMP;
  ALTER TABLE loops ALTER COLUMN resolved_at_new SET DEFAULT CURRENT_TIMESTAMP;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0033 post-backfill ALTER FAILED on loops.*_new: %', SQLERRM;
END $$;

-- ---------------------------------------------------------------------------
-- skills.updated_at (double precision epoch)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name='skills'
                   AND column_name='updated_at_new') THEN
    ALTER TABLE skills ADD COLUMN updated_at_new timestamp;
  END IF;
END $$;

DO $$
DECLARE
  v_type text;
BEGIN
  SELECT data_type INTO v_type FROM information_schema.columns
  WHERE table_schema='public' AND table_name='skills' AND column_name='updated_at';
  IF v_type = 'timestamp without time zone' THEN
    UPDATE skills SET updated_at_new = updated_at WHERE updated_at IS NOT NULL;
  ELSE
    UPDATE skills SET updated_at_new = to_timestamp(updated_at) WHERE updated_at IS NOT NULL;
  END IF;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0033 backfill FAILED on skills.updated_at: %', SQLERRM;
END $$;

DO $$
BEGIN
  ALTER TABLE skills ALTER COLUMN updated_at_new SET DEFAULT CURRENT_TIMESTAMP;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0033 post-backfill ALTER FAILED on skills.updated_at_new: %', SQLERRM;
END $$;

-- ---------------------------------------------------------------------------
-- capabilities.last_used (double precision epoch)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name='capabilities'
                   AND column_name='last_used_new') THEN
    ALTER TABLE capabilities ADD COLUMN last_used_new timestamp;
  END IF;
END $$;

DO $$
DECLARE
  v_type text;
BEGIN
  SELECT data_type INTO v_type FROM information_schema.columns
  WHERE table_schema='public' AND table_name='capabilities' AND column_name='last_used';
  IF v_type = 'timestamp without time zone' THEN
    UPDATE capabilities SET last_used_new = last_used WHERE last_used IS NOT NULL;
  ELSE
    UPDATE capabilities SET last_used_new = to_timestamp(last_used) WHERE last_used IS NOT NULL;
  END IF;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0033 backfill FAILED on capabilities.last_used: %', SQLERRM;
END $$;

DO $$
BEGIN
  ALTER TABLE capabilities ALTER COLUMN last_used_new SET DEFAULT CURRENT_TIMESTAMP;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0033 post-backfill ALTER FAILED on capabilities.last_used_new: %', SQLERRM;
END $$;

-- ---------------------------------------------------------------------------
-- task_context.updated_at (double precision epoch)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name='task_context'
                   AND column_name='updated_at_new') THEN
    ALTER TABLE task_context ADD COLUMN updated_at_new timestamp;
  END IF;
END $$;

DO $$
DECLARE
  v_type text;
BEGIN
  SELECT data_type INTO v_type FROM information_schema.columns
  WHERE table_schema='public' AND table_name='task_context' AND column_name='updated_at';
  IF v_type = 'timestamp without time zone' THEN
    UPDATE task_context SET updated_at_new = updated_at WHERE updated_at IS NOT NULL;
  ELSE
    UPDATE task_context SET updated_at_new = to_timestamp(updated_at) WHERE updated_at IS NOT NULL;
  END IF;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0033 backfill FAILED on task_context.updated_at: %', SQLERRM;
END $$;

DO $$
BEGIN
  ALTER TABLE task_context ALTER COLUMN updated_at_new SET DEFAULT CURRENT_TIMESTAMP;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0033 post-backfill ALTER FAILED on task_context.updated_at_new: %', SQLERRM;
END $$;

-- ---------------------------------------------------------------------------
-- tool_calls.timestamp (double precision epoch)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name='tool_calls'
                   AND column_name='timestamp_new') THEN
    ALTER TABLE tool_calls ADD COLUMN timestamp_new timestamp;
  END IF;
END $$;

-- Drop NOT NULL on old tool_calls.timestamp (new code writes timestamp_new instead)
DO $$
BEGIN
  ALTER TABLE tool_calls ALTER COLUMN timestamp DROP NOT NULL;
EXCEPTION WHEN OTHERS THEN
  RAISE NOTICE '0033: tool_calls.timestamp already nullable or error: %', SQLERRM;
END $$;

DO $$
DECLARE
  v_type text;
BEGIN
  SELECT data_type INTO v_type FROM information_schema.columns
  WHERE table_schema='public' AND table_name='tool_calls' AND column_name='timestamp';
  IF v_type = 'timestamp without time zone' THEN
    UPDATE tool_calls SET timestamp_new = timestamp WHERE timestamp IS NOT NULL;
  ELSE
    UPDATE tool_calls SET timestamp_new = to_timestamp(timestamp) WHERE timestamp IS NOT NULL;
  END IF;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0033 backfill FAILED on tool_calls.timestamp: %', SQLERRM;
END $$;

DO $$
BEGIN
  ALTER TABLE tool_calls ALTER COLUMN timestamp_new SET DEFAULT CURRENT_TIMESTAMP;
  ALTER TABLE tool_calls ALTER COLUMN timestamp_new SET NOT NULL;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0033 post-backfill ALTER FAILED on tool_calls.timestamp_new: %', SQLERRM;
END $$;

-- ---------------------------------------------------------------------------
-- gateway_events.created_at / started_at (real epoch, DB-default populated)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name='gateway_events'
                   AND column_name='created_at_new') THEN
    ALTER TABLE gateway_events ADD COLUMN created_at_new timestamp;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name='gateway_events'
                   AND column_name='started_at_new') THEN
    ALTER TABLE gateway_events ADD COLUMN started_at_new timestamp;
  END IF;
END $$;

DO $$
DECLARE
  v_type text;
BEGIN
  SELECT data_type INTO v_type FROM information_schema.columns
  WHERE table_schema='public' AND table_name='gateway_events' AND column_name='created_at';
  IF v_type = 'timestamp without time zone' THEN
    UPDATE gateway_events SET created_at_new = created_at WHERE created_at IS NOT NULL;
  ELSE
    UPDATE gateway_events SET created_at_new = to_timestamp(created_at) WHERE created_at IS NOT NULL;
  END IF;
  SELECT data_type INTO v_type FROM information_schema.columns
  WHERE table_schema='public' AND table_name='gateway_events' AND column_name='started_at';
  IF v_type = 'timestamp without time zone' THEN
    UPDATE gateway_events SET started_at_new = started_at WHERE started_at IS NOT NULL;
  ELSE
    UPDATE gateway_events SET started_at_new = to_timestamp(started_at) WHERE started_at IS NOT NULL;
  END IF;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0033 backfill FAILED on gateway_events.*: %', SQLERRM;
END $$;

DO $$
BEGIN
  ALTER TABLE gateway_events ALTER COLUMN created_at_new SET DEFAULT CURRENT_TIMESTAMP;
  ALTER TABLE gateway_events ALTER COLUMN started_at_new SET DEFAULT CURRENT_TIMESTAMP;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0033 post-backfill ALTER FAILED on gateway_events.*_new: %', SQLERRM;
END $$;

-- ============================================================================
-- FINAL VERIFICATION — STRICT, TYPE-AWARE: every _new value must EQUAL the
-- source (direct copy if already timestamp, to_timestamp(old) if epoch float)
-- for non-NULL old values, and must be NULL where old is NULL. This catches
-- both the DEFAULT pre-fill bug and the NULL-stamping bug, and is safe on
-- already-converted nodes (no to_timestamp() on a timestamp column).
-- ============================================================================
DO $$
DECLARE
  v_bad int;
  v_ts text;
BEGIN
  SELECT data_type INTO v_ts FROM information_schema.columns
  WHERE table_schema='public' AND table_name='messages' AND column_name='timestamp';
  IF v_ts = 'timestamp without time zone' THEN
    SELECT count(*) INTO v_bad FROM messages
      WHERE (timestamp IS NOT NULL AND timestamp_new IS DISTINCT FROM timestamp)
         OR (timestamp IS NULL AND timestamp_new IS NOT NULL);
  ELSE
    SELECT count(*) INTO v_bad FROM messages
      WHERE (timestamp IS NOT NULL AND timestamp_new IS DISTINCT FROM to_timestamp(timestamp))
         OR (timestamp IS NULL AND timestamp_new IS NOT NULL);
  END IF;
  IF v_bad > 0 THEN RAISE EXCEPTION '0033 VERIFY FAILED: % messages rows wrong', v_bad; END IF;

  SELECT data_type INTO v_ts FROM information_schema.columns
  WHERE table_schema='public' AND table_name='sessions' AND column_name='started_at';
  IF v_ts = 'timestamp without time zone' THEN
    SELECT count(*) INTO v_bad FROM sessions
      WHERE (started_at IS NOT NULL AND started_at_new IS DISTINCT FROM started_at)
         OR (started_at IS NULL AND started_at_new IS NOT NULL);
  ELSE
    SELECT count(*) INTO v_bad FROM sessions
      WHERE (started_at IS NOT NULL AND started_at_new IS DISTINCT FROM to_timestamp(started_at))
         OR (started_at IS NULL AND started_at_new IS NOT NULL);
  END IF;
  IF v_bad > 0 THEN RAISE EXCEPTION '0033 VERIFY FAILED: % sessions.started_at rows wrong', v_bad; END IF;

  SELECT data_type INTO v_ts FROM information_schema.columns
  WHERE table_schema='public' AND table_name='sessions' AND column_name='ended_at';
  IF v_ts = 'timestamp without time zone' THEN
    SELECT count(*) INTO v_bad FROM sessions
      WHERE (ended_at IS NOT NULL AND ended_at_new IS DISTINCT FROM ended_at)
         OR (ended_at IS NULL AND ended_at_new IS NOT NULL);
  ELSE
    SELECT count(*) INTO v_bad FROM sessions
      WHERE (ended_at IS NOT NULL AND ended_at_new IS DISTINCT FROM to_timestamp(ended_at))
         OR (ended_at IS NULL AND ended_at_new IS NOT NULL);
  END IF;
  IF v_bad > 0 THEN RAISE EXCEPTION '0033 VERIFY FAILED: % sessions.ended_at rows wrong', v_bad; END IF;

  SELECT data_type INTO v_ts FROM information_schema.columns
  WHERE table_schema='public' AND table_name='sessions' AND column_name='last_resume_marked_at';
  IF v_ts = 'timestamp without time zone' THEN
    SELECT count(*) INTO v_bad FROM sessions
      WHERE (last_resume_marked_at IS NOT NULL AND last_resume_marked_at_new IS DISTINCT FROM last_resume_marked_at)
         OR (last_resume_marked_at IS NULL AND last_resume_marked_at_new IS NOT NULL);
  ELSE
    SELECT count(*) INTO v_bad FROM sessions
      WHERE (last_resume_marked_at IS NOT NULL AND last_resume_marked_at_new IS DISTINCT FROM to_timestamp(last_resume_marked_at))
         OR (last_resume_marked_at IS NULL AND last_resume_marked_at_new IS NOT NULL);
  END IF;
  IF v_bad > 0 THEN RAISE EXCEPTION '0033 VERIFY FAILED: % sessions.last_resume_marked_at rows wrong', v_bad; END IF;

  SELECT data_type INTO v_ts FROM information_schema.columns
  WHERE table_schema='public' AND table_name='knowledge' AND column_name='last_referenced';
  IF v_ts = 'timestamp without time zone' THEN
    SELECT count(*) INTO v_bad FROM knowledge
      WHERE (last_referenced IS NOT NULL AND last_referenced_new IS DISTINCT FROM last_referenced)
         OR (last_referenced IS NULL AND last_referenced_new IS NOT NULL);
  ELSE
    SELECT count(*) INTO v_bad FROM knowledge
      WHERE (last_referenced IS NOT NULL AND last_referenced_new IS DISTINCT FROM to_timestamp(last_referenced))
         OR (last_referenced IS NULL AND last_referenced_new IS NOT NULL);
  END IF;
  IF v_bad > 0 THEN RAISE EXCEPTION '0033 VERIFY FAILED: % knowledge.last_referenced rows wrong', v_bad; END IF;

  -- knowledge.created_at may not exist on fleet lineage — only verify if present
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='knowledge'
               AND column_name='created_at') THEN
    SELECT data_type INTO v_ts FROM information_schema.columns
    WHERE table_schema='public' AND table_name='knowledge' AND column_name='created_at';
    IF v_ts = 'timestamp without time zone' THEN
      SELECT count(*) INTO v_bad FROM knowledge
        WHERE (created_at IS NOT NULL AND created_at_new IS DISTINCT FROM created_at)
           OR (created_at IS NULL AND created_at_new IS NOT NULL);
    ELSE
      SELECT count(*) INTO v_bad FROM knowledge
        WHERE (created_at IS NOT NULL AND created_at_new IS DISTINCT FROM to_timestamp(created_at))
           OR (created_at IS NULL AND created_at_new IS NOT NULL);
    END IF;
    IF v_bad > 0 THEN RAISE EXCEPTION '0033 VERIFY FAILED: % knowledge.created_at rows wrong', v_bad; END IF;
  END IF;

  SELECT data_type INTO v_ts FROM information_schema.columns
  WHERE table_schema='public' AND table_name='active' AND column_name='updated_at';
  IF v_ts = 'timestamp without time zone' THEN
    SELECT count(*) INTO v_bad FROM active
      WHERE (updated_at IS NOT NULL AND updated_at_new IS DISTINCT FROM updated_at)
         OR (updated_at IS NULL AND updated_at_new IS NOT NULL);
  ELSE
    SELECT count(*) INTO v_bad FROM active
      WHERE (updated_at IS NOT NULL AND updated_at_new IS DISTINCT FROM to_timestamp(updated_at))
         OR (updated_at IS NULL AND updated_at_new IS NOT NULL);
  END IF;
  IF v_bad > 0 THEN RAISE EXCEPTION '0033 VERIFY FAILED: % active rows wrong', v_bad; END IF;

  SELECT data_type INTO v_ts FROM information_schema.columns
  WHERE table_schema='public' AND table_name='loops' AND column_name='created_at';
  IF v_ts = 'timestamp without time zone' THEN
    SELECT count(*) INTO v_bad FROM loops
      WHERE (created_at IS NOT NULL AND created_at_new IS DISTINCT FROM created_at)
         OR (created_at IS NULL AND created_at_new IS NOT NULL);
  ELSE
    SELECT count(*) INTO v_bad FROM loops
      WHERE (created_at IS NOT NULL AND created_at_new IS DISTINCT FROM to_timestamp(created_at))
         OR (created_at IS NULL AND created_at_new IS NOT NULL);
  END IF;
  IF v_bad > 0 THEN RAISE EXCEPTION '0033 VERIFY FAILED: % loops.created_at rows wrong', v_bad; END IF;

  SELECT data_type INTO v_ts FROM information_schema.columns
  WHERE table_schema='public' AND table_name='loops' AND column_name='resolved_at';
  IF v_ts = 'timestamp without time zone' THEN
    SELECT count(*) INTO v_bad FROM loops
      WHERE (resolved_at IS NOT NULL AND resolved_at_new IS DISTINCT FROM resolved_at)
         OR (resolved_at IS NULL AND resolved_at_new IS NOT NULL);
  ELSE
    SELECT count(*) INTO v_bad FROM loops
      WHERE (resolved_at IS NOT NULL AND resolved_at_new IS DISTINCT FROM to_timestamp(resolved_at))
         OR (resolved_at IS NULL AND resolved_at_new IS NOT NULL);
  END IF;
  IF v_bad > 0 THEN RAISE EXCEPTION '0033 VERIFY FAILED: % loops.resolved_at rows wrong', v_bad; END IF;

  SELECT data_type INTO v_ts FROM information_schema.columns
  WHERE table_schema='public' AND table_name='skills' AND column_name='updated_at';
  IF v_ts = 'timestamp without time zone' THEN
    SELECT count(*) INTO v_bad FROM skills
      WHERE (updated_at IS NOT NULL AND updated_at_new IS DISTINCT FROM updated_at)
         OR (updated_at IS NULL AND updated_at_new IS NOT NULL);
  ELSE
    SELECT count(*) INTO v_bad FROM skills
      WHERE (updated_at IS NOT NULL AND updated_at_new IS DISTINCT FROM to_timestamp(updated_at))
         OR (updated_at IS NULL AND updated_at_new IS NOT NULL);
  END IF;
  IF v_bad > 0 THEN RAISE EXCEPTION '0033 VERIFY FAILED: % skills rows wrong', v_bad; END IF;

  SELECT data_type INTO v_ts FROM information_schema.columns
  WHERE table_schema='public' AND table_name='capabilities' AND column_name='last_used';
  IF v_ts = 'timestamp without time zone' THEN
    SELECT count(*) INTO v_bad FROM capabilities
      WHERE (last_used IS NOT NULL AND last_used_new IS DISTINCT FROM last_used)
         OR (last_used IS NULL AND last_used_new IS NOT NULL);
  ELSE
    SELECT count(*) INTO v_bad FROM capabilities
      WHERE (last_used IS NOT NULL AND last_used_new IS DISTINCT FROM to_timestamp(last_used))
         OR (last_used IS NULL AND last_used_new IS NOT NULL);
  END IF;
  IF v_bad > 0 THEN RAISE EXCEPTION '0033 VERIFY FAILED: % capabilities rows wrong', v_bad; END IF;

  SELECT data_type INTO v_ts FROM information_schema.columns
  WHERE table_schema='public' AND table_name='task_context' AND column_name='updated_at';
  IF v_ts = 'timestamp without time zone' THEN
    SELECT count(*) INTO v_bad FROM task_context
      WHERE (updated_at IS NOT NULL AND updated_at_new IS DISTINCT FROM updated_at)
         OR (updated_at IS NULL AND updated_at_new IS NOT NULL);
  ELSE
    SELECT count(*) INTO v_bad FROM task_context
      WHERE (updated_at IS NOT NULL AND updated_at_new IS DISTINCT FROM to_timestamp(updated_at))
         OR (updated_at IS NULL AND updated_at_new IS NOT NULL);
  END IF;
  IF v_bad > 0 THEN RAISE EXCEPTION '0033 VERIFY FAILED: % task_context rows wrong', v_bad; END IF;

  SELECT data_type INTO v_ts FROM information_schema.columns
  WHERE table_schema='public' AND table_name='tool_calls' AND column_name='timestamp';
  IF v_ts = 'timestamp without time zone' THEN
    SELECT count(*) INTO v_bad FROM tool_calls
      WHERE (timestamp IS NOT NULL AND timestamp_new IS DISTINCT FROM timestamp)
         OR (timestamp IS NULL AND timestamp_new IS NOT NULL);
  ELSE
    SELECT count(*) INTO v_bad FROM tool_calls
      WHERE (timestamp IS NOT NULL AND timestamp_new IS DISTINCT FROM to_timestamp(timestamp))
         OR (timestamp IS NULL AND timestamp_new IS NOT NULL);
  END IF;
  IF v_bad > 0 THEN RAISE EXCEPTION '0033 VERIFY FAILED: % tool_calls rows wrong', v_bad; END IF;

  SELECT data_type INTO v_ts FROM information_schema.columns
  WHERE table_schema='public' AND table_name='gateway_events' AND column_name='created_at';
  IF v_ts = 'timestamp without time zone' THEN
    SELECT count(*) INTO v_bad FROM gateway_events
      WHERE (created_at IS NOT NULL AND created_at_new IS DISTINCT FROM created_at)
         OR (created_at IS NULL AND created_at_new IS NOT NULL);
  ELSE
    SELECT count(*) INTO v_bad FROM gateway_events
      WHERE (created_at IS NOT NULL AND created_at_new IS DISTINCT FROM to_timestamp(created_at))
         OR (created_at IS NULL AND created_at_new IS NOT NULL);
  END IF;
  IF v_bad > 0 THEN RAISE EXCEPTION '0033 VERIFY FAILED: % gateway_events.created_at rows wrong', v_bad; END IF;

  SELECT data_type INTO v_ts FROM information_schema.columns
  WHERE table_schema='public' AND table_name='gateway_events' AND column_name='started_at';
  IF v_ts = 'timestamp without time zone' THEN
    SELECT count(*) INTO v_bad FROM gateway_events
      WHERE (started_at IS NOT NULL AND started_at_new IS DISTINCT FROM started_at)
         OR (started_at IS NULL AND started_at_new IS NOT NULL);
  ELSE
    SELECT count(*) INTO v_bad FROM gateway_events
      WHERE (started_at IS NOT NULL AND started_at_new IS DISTINCT FROM to_timestamp(started_at))
         OR (started_at IS NULL AND started_at_new IS NOT NULL);
  END IF;
  IF v_bad > 0 THEN RAISE EXCEPTION '0033 VERIFY FAILED: % gateway_events.started_at rows wrong', v_bad; END IF;

  RAISE NOTICE '0033 VERIFY PASSED: all _new columns surgical (value match + NULL preserved)';
END $$;

-- ============================================================================
-- END migration 0033 (Track A hot-path duplicate columns + surgical backfill)
-- ============================================================================
