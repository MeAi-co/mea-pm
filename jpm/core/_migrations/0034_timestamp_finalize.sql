-- ============================================================================
-- Migration 0034: Timestamp columns — Track A (hot path) finalize
-- ============================================================================
-- GOAL: Complete the epoch-float -> timestamp conversion started in 0033.
--       0033 added `_new` timestamp columns, backfilled them from each row's
--       OWN stored value, and the code now writes datetimes to `_new`.
--       0034 drops the old float columns and renames `_new` -> original.
--
--       The beauty of this approach: ALL reads already use the original
--       column names. The moment 0034 renames `_new` -> original, every read
--       path is automatically fixed. Zero read changes needed.
--
-- ORDERING: DROP the old float column FIRST, then RENAME `_new`
--       to the original name. The renamed column inherits the `_new` column's
--       type (timestamp), DEFAULT (CURRENT_TIMESTAMP), and NOT NULL.
--
-- INDEXES: The old float columns carry indexes that get dropped with them.
--       These MUST be recreated on the renamed timestamp columns. The exact
--       definitions were captured from pg_indexes before this migration.
--       NOTE: idx_sessions_updated_at (on sessions.updated_at) and
--       idx_tool_calls_session (on tool_calls.session_id) are NOT on migrated
--       columns — they are left untouched.
--
-- SAFETY: Each DROP/RENAME is guarded by column-existence checks so the
--       migration is idempotent. Index recreation uses IF NOT EXISTS.
--       A final verification block confirms every renamed column is now
--       `timestamp without time zone` and every expected index exists.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- messages.timestamp_new -> timestamp
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='messages'
               AND column_name='timestamp') THEN
    ALTER TABLE messages DROP COLUMN timestamp;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='messages'
               AND column_name='timestamp_new') THEN
    ALTER TABLE messages RENAME COLUMN timestamp_new TO timestamp;
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- sessions: started_at_new, ended_at_new, last_resume_marked_at_new
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='sessions'
               AND column_name='started_at') THEN
    ALTER TABLE sessions DROP COLUMN started_at;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='sessions'
               AND column_name='started_at_new') THEN
    ALTER TABLE sessions RENAME COLUMN started_at_new TO started_at;
  END IF;

  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='sessions'
               AND column_name='ended_at') THEN
    ALTER TABLE sessions DROP COLUMN ended_at;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='sessions'
               AND column_name='ended_at_new') THEN
    ALTER TABLE sessions RENAME COLUMN ended_at_new TO ended_at;
  END IF;

  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='sessions'
               AND column_name='last_resume_marked_at') THEN
    ALTER TABLE sessions DROP COLUMN last_resume_marked_at;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='sessions'
               AND column_name='last_resume_marked_at_new') THEN
    ALTER TABLE sessions RENAME COLUMN last_resume_marked_at_new TO last_resume_marked_at;
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- knowledge: created_at_new, last_referenced_new
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='knowledge'
               AND column_name='created_at') THEN
    ALTER TABLE knowledge DROP COLUMN created_at;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='knowledge'
               AND column_name='created_at_new') THEN
    ALTER TABLE knowledge RENAME COLUMN created_at_new TO created_at;
  END IF;

  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='knowledge'
               AND column_name='last_referenced') THEN
    ALTER TABLE knowledge DROP COLUMN last_referenced;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='knowledge'
               AND column_name='last_referenced_new') THEN
    ALTER TABLE knowledge RENAME COLUMN last_referenced_new TO last_referenced;
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- active.updated_at_new -> updated_at
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='active'
               AND column_name='updated_at') THEN
    ALTER TABLE active DROP COLUMN updated_at;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='active'
               AND column_name='updated_at_new') THEN
    ALTER TABLE active RENAME COLUMN updated_at_new TO updated_at;
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- loops: created_at_new, resolved_at_new
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='loops'
               AND column_name='created_at') THEN
    ALTER TABLE loops DROP COLUMN created_at;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='loops'
               AND column_name='created_at_new') THEN
    ALTER TABLE loops RENAME COLUMN created_at_new TO created_at;
  END IF;

  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='loops'
               AND column_name='resolved_at') THEN
    ALTER TABLE loops DROP COLUMN resolved_at;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='loops'
               AND column_name='resolved_at_new') THEN
    ALTER TABLE loops RENAME COLUMN resolved_at_new TO resolved_at;
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- skills.updated_at_new -> updated_at
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='skills'
               AND column_name='updated_at') THEN
    ALTER TABLE skills DROP COLUMN updated_at;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='skills'
               AND column_name='updated_at_new') THEN
    ALTER TABLE skills RENAME COLUMN updated_at_new TO updated_at;
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- capabilities.last_used_new -> last_used
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='capabilities'
               AND column_name='last_used') THEN
    ALTER TABLE capabilities DROP COLUMN last_used;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='capabilities'
               AND column_name='last_used_new') THEN
    ALTER TABLE capabilities RENAME COLUMN last_used_new TO last_used;
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- task_context.updated_at_new -> updated_at
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='task_context'
               AND column_name='updated_at') THEN
    ALTER TABLE task_context DROP COLUMN updated_at;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='task_context'
               AND column_name='updated_at_new') THEN
    ALTER TABLE task_context RENAME COLUMN updated_at_new TO updated_at;
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- tool_calls.timestamp_new -> timestamp
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='tool_calls'
               AND column_name='timestamp') THEN
    ALTER TABLE tool_calls DROP COLUMN timestamp;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='tool_calls'
               AND column_name='timestamp_new') THEN
    ALTER TABLE tool_calls RENAME COLUMN timestamp_new TO timestamp;
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- gateway_events: created_at_new, started_at_new
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='gateway_events'
               AND column_name='created_at') THEN
    ALTER TABLE gateway_events DROP COLUMN created_at;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='gateway_events'
               AND column_name='created_at_new') THEN
    ALTER TABLE gateway_events RENAME COLUMN created_at_new TO created_at;
  END IF;

  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='gateway_events'
               AND column_name='started_at') THEN
    ALTER TABLE gateway_events DROP COLUMN started_at;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='gateway_events'
               AND column_name='started_at_new') THEN
    ALTER TABLE gateway_events RENAME COLUMN started_at_new TO started_at;
  END IF;
END $$;

-- ============================================================================
-- Recreate indexes on the renamed timestamp columns
-- ============================================================================

-- messages
CREATE INDEX IF NOT EXISTS idx_messages_session
  ON public.messages USING btree (session_id, "timestamp");
CREATE INDEX IF NOT EXISTS idx_messages_session_active
  ON public.messages USING btree (session_id, active, "timestamp");
CREATE INDEX IF NOT EXISTS idx_messages_timestamp
  ON public.messages USING btree ("timestamp" DESC);
CREATE INDEX IF NOT EXISTS idx_messages_role_active
  ON public.messages USING btree (role, active, compacted, "timestamp" DESC);

-- sessions (idx_sessions_updated_at is on updated_at — NOT migrated, left alone)
CREATE INDEX IF NOT EXISTS idx_sessions_started
  ON public.sessions USING btree (started_at DESC);

-- tool_calls (idx_tool_calls_session is on session_id — NOT migrated, left alone)
CREATE INDEX IF NOT EXISTS idx_tool_calls_timestamp
  ON public.tool_calls USING btree ("timestamp" DESC);
CREATE INDEX IF NOT EXISTS idx_tool_calls_user
  ON public.tool_calls USING btree (user_id, "timestamp");

-- loops
CREATE INDEX IF NOT EXISTS idx_loops_active
  ON public.loops USING btree (resolved, priority, created_at);

-- gateway_events
CREATE INDEX IF NOT EXISTS idx_gateway_events_started_at
  ON public.gateway_events USING btree (started_at DESC);

-- ============================================================================
-- Verification: every renamed column must now be `timestamp without time zone`
-- and every expected index must exist. RAISE if anything is wrong.
-- ============================================================================
DO $$
DECLARE
  bad_cols INT;
  missing_idx INT;
BEGIN
  -- All migrated columns must now be timestamp without time zone
  SELECT COUNT(*) INTO bad_cols
  FROM information_schema.columns c
  WHERE c.table_schema='public'
    AND (
      (c.table_name='messages' AND c.column_name='timestamp')
      OR (c.table_name='sessions' AND c.column_name IN ('started_at','ended_at','last_resume_marked_at'))
      OR (c.table_name='knowledge' AND c.column_name IN ('created_at','last_referenced'))
      OR (c.table_name='active' AND c.column_name='updated_at')
      OR (c.table_name='loops' AND c.column_name IN ('created_at','resolved_at'))
      OR (c.table_name='skills' AND c.column_name='updated_at')
      OR (c.table_name='capabilities' AND c.column_name='last_used')
      OR (c.table_name='task_context' AND c.column_name='updated_at')
      OR (c.table_name='tool_calls' AND c.column_name='timestamp')
      OR (c.table_name='gateway_events' AND c.column_name IN ('created_at','started_at'))
    )
    AND c.data_type <> 'timestamp without time zone';

  IF bad_cols > 0 THEN
    RAISE EXCEPTION '0034 VERIFY FAILED: % migrated columns are not timestamp without time zone', bad_cols;
  END IF;

  -- No _new columns should remain
  SELECT COUNT(*) INTO bad_cols
  FROM information_schema.columns c
  WHERE c.table_schema='public' AND c.column_name LIKE '%_new';
  IF bad_cols > 0 THEN
    RAISE EXCEPTION '0034 VERIFY FAILED: % _new columns still remain', bad_cols;
  END IF;

  -- All expected indexes must exist
  SELECT COUNT(*) INTO missing_idx
  FROM (VALUES
    ('idx_messages_session'),('idx_messages_session_active'),
    ('idx_messages_timestamp'),('idx_messages_role_active'),
    ('idx_sessions_started'),
    ('idx_tool_calls_timestamp'),('idx_tool_calls_user'),
    ('idx_loops_active'),
    ('idx_gateway_events_started_at')
  ) AS expected(idx)
  WHERE NOT EXISTS (
    SELECT 1 FROM pg_indexes i
    WHERE i.schemaname='public' AND i.indexname = expected.idx
  );

  IF missing_idx > 0 THEN
    RAISE EXCEPTION '0034 VERIFY FAILED: % expected indexes missing', missing_idx;
  END IF;

  RAISE NOTICE '0034 VERIFY OK: all columns timestamp, no _new remain, all indexes present';
END $$;
