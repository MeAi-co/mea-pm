-- ============================================================================
-- Migration 0036: Timestamp columns — Track B (oracle/analytics) finalize
-- ============================================================================
-- GOAL: Complete the epoch-float -> timestamp conversion started in 0035 for
--        the four Track B tables (_recent_sync, llm_calls, oracle_diagnostics,
--        oracle_log). 0035 added `_new` timestamp columns, backfilled them from
--        each row's OWN stored value, and the code now writes datetimes to
--        `_new`. 0036 drops the old float columns and renames `_new` -> original.
--
--       The beauty of this approach: ALL reads already use the original column
--       names. The moment 0036 renames `_new` -> original, every read path is
--       automatically fixed. Zero read changes needed.
--
-- ORDERING: DROP the old float column FIRST, then RENAME `_new` to
--       the original name. The renamed column inherits the `_new` column's
--       type (timestamp), DEFAULT (CURRENT_TIMESTAMP), and NOT NULL.
--
-- INDEXES: oracle_log carries several indexes on timestamp that get dropped
--       with the column. These MUST be recreated on the renamed timestamp
--       column. Captured from pg_indexes before this migration.
--       NOTE: llm_calls has idx_llm_calls_timestamp (DESC) and
--       idx_llm_calls_user (on user_id, timestamp) — both on the migrated
--       column and both dropped with it, so both are recreated.
--
-- SAFETY: Each DROP/RENAME is guarded by column-existence checks so the
--       migration is idempotent. Index recreation uses IF NOT EXISTS.
--       A final verification block confirms every renamed column is now
--       `timestamp without time zone` and every expected index exists.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- _recent_sync.timestamp_new -> timestamp
-- NOTE: _recent_sync is legacy and absent on fleet nodes — guard on table
--       existence so the migration is fleet-compatible.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables
             WHERE table_schema='public' AND table_name='_recent_sync')
     AND EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name='_recent_sync'
                   AND column_name='timestamp') THEN
    ALTER TABLE _recent_sync DROP COLUMN timestamp;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.tables
             WHERE table_schema='public' AND table_name='_recent_sync')
     AND EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name='_recent_sync'
                   AND column_name='timestamp_new') THEN
    ALTER TABLE _recent_sync RENAME COLUMN timestamp_new TO timestamp;
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- llm_calls.timestamp_new -> timestamp
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='llm_calls'
               AND column_name='timestamp') THEN
    ALTER TABLE llm_calls DROP COLUMN timestamp;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='llm_calls'
               AND column_name='timestamp_new') THEN
    ALTER TABLE llm_calls RENAME COLUMN timestamp_new TO timestamp;
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- oracle_diagnostics.timestamp_new -> timestamp
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='oracle_diagnostics'
               AND column_name='timestamp') THEN
    ALTER TABLE oracle_diagnostics DROP COLUMN timestamp;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='oracle_diagnostics'
               AND column_name='timestamp_new') THEN
    ALTER TABLE oracle_diagnostics RENAME COLUMN timestamp_new TO timestamp;
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- oracle_log.timestamp_new -> timestamp
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='oracle_log'
               AND column_name='timestamp') THEN
    ALTER TABLE oracle_log DROP COLUMN timestamp;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='oracle_log'
               AND column_name='timestamp_new') THEN
    ALTER TABLE oracle_log RENAME COLUMN timestamp_new TO timestamp;
  END IF;
END $$;

-- ============================================================================
-- Recreate indexes on the renamed timestamp columns
-- ============================================================================

-- llm_calls
CREATE INDEX IF NOT EXISTS idx_llm_calls_timestamp
  ON public.llm_calls USING btree ("timestamp" DESC);
CREATE INDEX IF NOT EXISTS idx_llm_calls_user
  ON public.llm_calls USING btree (user_id, "timestamp");

-- oracle_log
CREATE INDEX IF NOT EXISTS idx_oracle_signal
  ON public.oracle_log USING btree (oracle_signal);
CREATE INDEX IF NOT EXISTS idx_oracle_loop
  ON public.oracle_log USING btree (loop_detected);
CREATE INDEX IF NOT EXISTS idx_oracle_session
  ON public.oracle_log USING btree (session_id, turn);
CREATE INDEX IF NOT EXISTS idx_oracle_dna
  ON public.oracle_log USING btree (dna_matched);
CREATE INDEX IF NOT EXISTS idx_oracle_task
  ON public.oracle_log USING btree (task_completed);
CREATE INDEX IF NOT EXISTS idx_oracle_verify
  ON public.oracle_log USING btree (verification_status);

-- ============================================================================
-- Verification: every renamed column must now be `timestamp without time zone`
-- and every expected index must exist. RAISE if anything is wrong.
-- ============================================================================
DO $$
DECLARE
  bad_cols INT;
  missing_idx INT;
BEGIN
  -- All four migrated columns must now be timestamp without time zone
  SELECT COUNT(*) INTO bad_cols
  FROM information_schema.columns c
  WHERE c.table_schema='public'
    AND c.table_name IN ('_recent_sync','llm_calls','oracle_diagnostics','oracle_log')
    AND c.column_name='timestamp'
    AND c.data_type <> 'timestamp without time zone';

  IF bad_cols > 0 THEN
    RAISE EXCEPTION '0036 VERIFY FAILED: % timestamp columns are not timestamp without time zone', bad_cols;
  END IF;

  -- No _new columns should remain anywhere
  SELECT COUNT(*) INTO bad_cols
  FROM information_schema.columns c
  WHERE c.table_schema='public' AND c.column_name LIKE '%_new';
  IF bad_cols > 0 THEN
    RAISE EXCEPTION '0036 VERIFY FAILED: % _new columns still remain', bad_cols;
  END IF;

  -- All expected indexes must exist
  SELECT COUNT(*) INTO missing_idx
  FROM (VALUES
    ('idx_llm_calls_timestamp'),('idx_llm_calls_user'),
    ('idx_oracle_signal'),('idx_oracle_loop'),('idx_oracle_session'),
    ('idx_oracle_dna'),('idx_oracle_task'),('idx_oracle_verify')
  ) AS expected(idx)
  WHERE NOT EXISTS (
    SELECT 1 FROM pg_indexes i
    WHERE i.schemaname='public' AND i.indexname = expected.idx
  );

  IF missing_idx > 0 THEN
    RAISE EXCEPTION '0036 VERIFY FAILED: % expected indexes missing', missing_idx;
  END IF;

  RAISE NOTICE '0036 VERIFY OK: all 4 columns timestamp, no _new remain, all indexes present';
END $$;
