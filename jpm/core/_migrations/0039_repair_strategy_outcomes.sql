-- Migration 0039: Repair browser_strategy_outcomes schema drift
--
-- Schema: ext_api
--
-- Problem:
--   The live browser_strategy_outcomes table was created from the OLD glossary
--   schema (migration 0019) — columns: element_strategy_id, logical_name,
--   strategy_used. Migration 0021 introduced the NEW feedback schema — columns:
--   action_id, element_id, state_id, strategy_type. Because CREATE TABLE IF NOT
--   EXISTS silently skips existing tables, the 0021 CREATE never ran on this DB,
--   leaving the old glossary shape in place. schema_audit reports 4 missing
--   columns (action_id, element_id, state_id, strategy_type).
--
-- Fix (generic + idempotent):
--   Detect the old schema by the presence of the element_strategy_id column.
--   If found:
--     - If the table is EMPTY: drop and recreate with the correct 0021 schema.
--     - If the table has DATA: preserve it by renaming to a backup table
--       (browser_strategy_outcomes_legacy_0019) before recreating, so no data
--       is lost. The old glossary columns don't map cleanly to the new feedback
--       columns, so a column-wise migration isn't meaningful — backup is safer.
--   Then recreate the correct indexes. All guarded so re-runs are no-ops.
--
-- This is safe for the migration runner: every statement is idempotent, and a
-- partial failure leaves the migration unrecorded so it retries on next start.

-- ── Detect old schema and repair ──────────────────────────────────────────
DO $$
DECLARE
    has_old_schema BOOLEAN;
    row_count      BIGINT;
BEGIN
    -- Detect the old glossary schema (element_strategy_id column present)
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'ext_api'
          AND table_name = 'browser_strategy_outcomes'
          AND column_name = 'element_strategy_id'
    ) INTO has_old_schema;

    IF has_old_schema THEN
        -- Count rows to decide drop vs backup
        EXECUTE 'SELECT COUNT(*) FROM ext_api.browser_strategy_outcomes' INTO row_count;

        IF row_count = 0 THEN
            -- Empty: safe to drop and recreate
            EXECUTE 'DROP TABLE IF EXISTS ext_api.browser_strategy_outcomes CASCADE';
            RAISE NOTICE '0039: dropped empty legacy browser_strategy_outcomes';
        ELSE
            -- Has data: preserve as backup before recreating
            EXECUTE 'ALTER TABLE ext_api.browser_strategy_outcomes RENAME TO browser_strategy_outcomes_legacy_0019';
            RAISE NOTICE '0039: preserved % rows in browser_strategy_outcomes_legacy_0019', row_count;
        END IF;
    END IF;
END $$;

-- ── Recreate with the correct 0021 feedback schema ─────────────────────────
CREATE TABLE IF NOT EXISTS ext_api.browser_strategy_outcomes (
    id              BIGSERIAL PRIMARY KEY,
    dom_strategy_id BIGINT REFERENCES ext_api.browser_dom_strategies(id) ON DELETE SET NULL,
    session_id      UUID NOT NULL REFERENCES ext_api.sessions(id) ON DELETE CASCADE,
    action_id       BIGINT NOT NULL REFERENCES ext_api.session_log(id) ON DELETE CASCADE,
    element_id      TEXT NOT NULL DEFAULT '',
    page_url        TEXT NOT NULL DEFAULT '',
    state_id        TEXT NOT NULL DEFAULT 'root',
    strategy_type   TEXT NOT NULL DEFAULT '',
    success         BOOLEAN NOT NULL,
    error_code      TEXT NOT NULL DEFAULT '',
    duration_ms     INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (action_id, dom_strategy_id)
);

-- ── Recreate indexes (idempotent) ─────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_browser_strategy_outcomes_strategy
    ON ext_api.browser_strategy_outcomes (dom_strategy_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_browser_strategy_outcomes_session
    ON ext_api.browser_strategy_outcomes (session_id, page_url);
