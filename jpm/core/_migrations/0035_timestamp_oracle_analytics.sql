-- ============================================================================
-- Migration 0035: Timestamp columns — Track B (oracle/analytics) duplicate-column
-- ============================================================================
-- GOAL: Convert the remaining epoch-float timestamp columns to
--       `timestamp without time zone` (MySQL DATETIME equivalent, system TZ,
--       no TZ suffix) WITHOUT touching the live column. This is Track B — the
--       four tables 0033/0034 intentionally left out:
--         - _recent_sync          (legacy, no active writer, 31 rows)
--         - llm_calls             (usage tracking, float written explicitly)
--         - oracle_diagnostics    (per-window oracle stats, DB-default timestamp)
--         - oracle_log            (per-tool oracle audit, DB-default timestamp)
--
--       Same two-step dance as 0033/0034: this file ADDS `_new` columns and
--       backfills them from each row's OWN stored value. A later migration
--       (0036) drops the old float columns and renames `_new` -> original.
--
-- ORDERING: DEFAULT CURRENT_TIMESTAMP and NOT NULL are applied to
--       the _new columns AFTER the backfill, NOT at column creation.
--       Adding a column with DEFAULT fires the default on ALL existing rows
--       at ALTER time (stamping 'now' on everything) and makes the backfill
--       a no-op. So: add nullable no-default column -> backfill from old ->
--       THEN set default -> THEN set NOT NULL (only where the source column
--       was NOT NULL).
--
-- NULLABILITY (matches source column):
--   - _recent_sync.timestamp       nullable, no default -> _new stays nullable
--   - llm_calls.timestamp          NOT NULL + epoch default -> _new NOT NULL
--   - oracle_diagnostics.timestamp nullable + default   -> _new nullable + default
--   - oracle_log.timestamp         nullable + default   -> _new nullable + default
--
-- SAFETY: Every backfill uses to_timestamp(col) — a pure value conversion of
--         each row's stored epoch. No CURRENT_TIMESTAMP in any backfill.
--         NULLs are preserved (NULL old stays NULL in _new).
--         Idempotent: each ADD COLUMN guarded by a column-existence check.
--         Each backfill runs in a DO block with EXCEPTION that RAISEs a
--         clear named error on failure.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- _recent_sync.timestamp (double precision epoch) -> timestamp
-- NOTE: _recent_sync is a legacy table that does NOT exist on fleet nodes
--       (their schema lineage predates it). Guard the entire section on
--       table existence so the migration is fleet-compatible.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables
             WHERE table_schema='public' AND table_name='_recent_sync')
     AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_schema='public' AND table_name='_recent_sync'
                       AND column_name='timestamp_new') THEN
    ALTER TABLE _recent_sync ADD COLUMN timestamp_new timestamp;
  END IF;
END $$;

DO $$
BEGIN
  -- Only backfill when the source is still an epoch float. On DBs where the
  -- column is ALREADY `timestamp` (converted by an earlier lineage), calling
  -- to_timestamp(timestamp) hard-fails: "function to_timestamp(timestamp
  -- without time zone) does not exist". Skip — the value is already correct.
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='_recent_sync'
               AND column_name='timestamp' AND data_type='double precision') THEN
    UPDATE _recent_sync SET timestamp_new = to_timestamp(timestamp)
      WHERE timestamp IS NOT NULL;
  END IF;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0035 backfill FAILED on _recent_sync.timestamp: %', SQLERRM;
END $$;

-- Source was nullable/no-default; keep _new nullable, just add a sane default.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables
             WHERE table_schema='public' AND table_name='_recent_sync') THEN
    ALTER TABLE _recent_sync ALTER COLUMN timestamp_new SET DEFAULT CURRENT_TIMESTAMP;
  END IF;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0035 post-backfill ALTER FAILED on _recent_sync.timestamp_new: %', SQLERRM;
END $$;

-- ---------------------------------------------------------------------------
-- llm_calls.timestamp (double precision epoch, NOT NULL + epoch default)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name='llm_calls'
                   AND column_name='timestamp_new') THEN
    ALTER TABLE llm_calls ADD COLUMN timestamp_new timestamp;
  END IF;
END $$;

DO $$
BEGIN
  -- Guard on source type: only convert when still epoch float (see _recent_sync note).
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='llm_calls'
               AND column_name='timestamp' AND data_type='double precision') THEN
    UPDATE llm_calls SET timestamp_new = to_timestamp(timestamp)
      WHERE timestamp IS NOT NULL;
  END IF;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0035 backfill FAILED on llm_calls.timestamp: %', SQLERRM;
END $$;

-- Source was NOT NULL with an epoch default; mirror on _new AFTER backfill.
DO $$
BEGIN
  ALTER TABLE llm_calls ALTER COLUMN timestamp_new SET DEFAULT CURRENT_TIMESTAMP;
  ALTER TABLE llm_calls ALTER COLUMN timestamp_new SET NOT NULL;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0035 post-backfill ALTER FAILED on llm_calls.timestamp_new: %', SQLERRM;
END $$;

-- ---------------------------------------------------------------------------
-- oracle_diagnostics.timestamp (double precision epoch, nullable + epoch default)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name='oracle_diagnostics'
                   AND column_name='timestamp_new') THEN
    ALTER TABLE oracle_diagnostics ADD COLUMN timestamp_new timestamp;
  END IF;
END $$;

DO $$
BEGIN
  -- Guard on source type: only convert when still epoch float (see _recent_sync note).
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='oracle_diagnostics'
               AND column_name='timestamp' AND data_type='double precision') THEN
    UPDATE oracle_diagnostics SET timestamp_new = to_timestamp(timestamp)
      WHERE timestamp IS NOT NULL;
  END IF;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0035 backfill FAILED on oracle_diagnostics.timestamp: %', SQLERRM;
END $$;

DO $$
BEGIN
  ALTER TABLE oracle_diagnostics ALTER COLUMN timestamp_new SET DEFAULT CURRENT_TIMESTAMP;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0035 post-backfill ALTER FAILED on oracle_diagnostics.timestamp_new: %', SQLERRM;
END $$;

-- ---------------------------------------------------------------------------
-- oracle_log.timestamp (double precision epoch, nullable + epoch default)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema='public' AND table_name='oracle_log'
                   AND column_name='timestamp_new') THEN
    ALTER TABLE oracle_log ADD COLUMN timestamp_new timestamp;
  END IF;
END $$;

DO $$
BEGIN
  -- Guard on source type: only convert when still epoch float (see _recent_sync note).
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='oracle_log'
               AND column_name='timestamp' AND data_type='double precision') THEN
    UPDATE oracle_log SET timestamp_new = to_timestamp(timestamp)
      WHERE timestamp IS NOT NULL;
  END IF;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0035 backfill FAILED on oracle_log.timestamp: %', SQLERRM;
END $$;

DO $$
BEGIN
  ALTER TABLE oracle_log ALTER COLUMN timestamp_new SET DEFAULT CURRENT_TIMESTAMP;
EXCEPTION WHEN OTHERS THEN
  RAISE EXCEPTION '0035 post-backfill ALTER FAILED on oracle_log.timestamp_new: %', SQLERRM;
END $$;

-- ============================================================================
-- Verification: value equality (timestamp_new = to_timestamp(timestamp)) AND
-- NULL preservation. RAISE if any row is wrong.
-- ============================================================================
DO $$
DECLARE
  bad_rows BIGINT;
BEGIN
  -- Only verify tables whose source column is STILL epoch float. When the
  -- source is already `timestamp`, to_timestamp(timestamp) is invalid and the
  -- comparison is meaningless (the _new column was never backfilled here).
  -- _recent_sync (only if the table exists — legacy, absent on fleet nodes)
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='_recent_sync'
               AND column_name='timestamp' AND data_type='double precision') THEN
    SELECT COUNT(*) INTO bad_rows FROM _recent_sync
      WHERE (timestamp IS NULL) <> (timestamp_new IS NULL)
         OR (timestamp IS NOT NULL AND timestamp_new <> to_timestamp(timestamp));
    IF bad_rows > 0 THEN
      RAISE EXCEPTION '0035 VERIFY FAILED: _recent_sync has % mismatched rows', bad_rows;
    END IF;
  END IF;

  -- llm_calls
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='llm_calls'
               AND column_name='timestamp' AND data_type='double precision') THEN
    SELECT COUNT(*) INTO bad_rows FROM llm_calls
      WHERE (timestamp IS NULL) <> (timestamp_new IS NULL)
         OR (timestamp IS NOT NULL AND timestamp_new <> to_timestamp(timestamp));
    IF bad_rows > 0 THEN
      RAISE EXCEPTION '0035 VERIFY FAILED: llm_calls has % mismatched rows', bad_rows;
    END IF;
  END IF;

  -- oracle_diagnostics
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='oracle_diagnostics'
               AND column_name='timestamp' AND data_type='double precision') THEN
    SELECT COUNT(*) INTO bad_rows FROM oracle_diagnostics
      WHERE (timestamp IS NULL) <> (timestamp_new IS NULL)
         OR (timestamp IS NOT NULL AND timestamp_new <> to_timestamp(timestamp));
    IF bad_rows > 0 THEN
      RAISE EXCEPTION '0035 VERIFY FAILED: oracle_diagnostics has % mismatched rows', bad_rows;
    END IF;
  END IF;

  -- oracle_log
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='oracle_log'
               AND column_name='timestamp' AND data_type='double precision') THEN
    SELECT COUNT(*) INTO bad_rows FROM oracle_log
      WHERE (timestamp IS NULL) <> (timestamp_new IS NULL)
         OR (timestamp IS NOT NULL AND timestamp_new <> to_timestamp(timestamp));
    IF bad_rows > 0 THEN
      RAISE EXCEPTION '0035 VERIFY FAILED: oracle_log has % mismatched rows', bad_rows;
    END IF;
  END IF;

  RAISE NOTICE '0035 VERIFY OK: all _new columns match to_timestamp(old), NULLs preserved';
END $$;
