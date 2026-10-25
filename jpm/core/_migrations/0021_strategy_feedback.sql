-- Migration 0021: Strategy Feedback & Confidence Tracking
--
-- Schema: ext_api
--
-- Changes:
--   ext_api.browser_dom_strategies     — Add is_active, last_success_at, last_failure_at, source
--   ext_api.browser_strategy_outcomes  — New: immutable audit trail of every strategy execution
--   ext_api.compute_confidence — New: SQL function for Bayesian prior + deactivation
--
-- Design:
--   - is_active = false when fail_rate > 0.4 AND total >= 5 (configurable via constants)
--   - confidence uses Bayesian prior so 0/0 stays near learn-time confidence
--   - browser_strategy_outcomes is append-only, keyed by (action_id, dom_strategy_id) for idempotency
--   - source distinguishes learn-time vs execution-time strategy creation

-- ── Constants (configurable via env, defaults here) ─────────────────────────

-- Bayesian prior: confidence = (success + 1) / (total + 2) when total < 5
-- After 5+ executions, raw ratio dominates
-- Half-life: confidence *= exp(-hours_since_last / 72) (3-day half-life)

-- ── Alter ext_api.browser_dom_strategies ──────────────────────────────────────────

ALTER TABLE ext_api.browser_dom_strategies
    ADD COLUMN IF NOT EXISTS is_active         BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS last_success_at    TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_failure_at    TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS source            TEXT NOT NULL DEFAULT 'learn'
        CHECK (source IN ('learn', 'execution'));

CREATE INDEX IF NOT EXISTS idx_browser_dom_strategies_active
    ON ext_api.browser_dom_strategies (element_id, is_active, confidence DESC)
    WHERE is_active = true;

-- ── ext_api.browser_strategy_outcomes ───────────────────────────────────────────────
-- Immutable audit trail. Every strategy execution attempt, success or failure.
-- Keyed by (action_id, dom_strategy_id) for idempotency — retries don't double-count.
--
-- IMPORTANT (idempotent column guard): because CREATE TABLE IF NOT EXISTS silently
-- skips existing tables, the ALTER TABLE ... ADD COLUMN IF NOT EXISTS right below
-- ensures that older DBs (whose browser_strategy_outcomes table was created from an earlier
-- schema or via fix_browser_strategy_outcomes.py) still get the column. Without this, the
-- index on dom_strategy_id fails with "column does not exist" on every gateway
-- restart. This ALTER must appear BEFORE the index to avoid that ordering failure.

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

-- Idempotent column guard for existing tables (see note above):
ALTER TABLE IF EXISTS ext_api.browser_strategy_outcomes
    ADD COLUMN IF NOT EXISTS dom_strategy_id BIGINT REFERENCES ext_api.browser_dom_strategies(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_browser_strategy_outcomes_strategy
    ON ext_api.browser_strategy_outcomes (dom_strategy_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_browser_strategy_outcomes_session
    ON ext_api.browser_strategy_outcomes (session_id, page_url);

-- ── Idempotent column additions for existing tables ────────────────────────
-- CREATE TABLE IF NOT EXISTS silently skips existing tables, so new columns
-- never appear on older DBs without explicit ALTER statements. These guard
-- against the "column does not exist" failure on every gateway restart.

ALTER TABLE ext_api.browser_dom_strategies
    ADD COLUMN IF NOT EXISTS is_active         BOOLEAN NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS last_success_at    TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_failure_at    TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS source            TEXT NOT NULL DEFAULT 'learn'
        CHECK (source IN ('learn', 'execution'));

ALTER TABLE ext_api.browser_strategy_outcomes
    ADD COLUMN IF NOT EXISTS dom_strategy_id BIGINT REFERENCES ext_api.browser_dom_strategies(id) ON DELETE SET NULL;

-- ── Confidence Computation Function ────────────────────────────────────────
-- Bayesian prior: adj = (success + 1) / (total + 2) for small samples
-- Time decay: confidence *= exp(-hours_since_last_verify / 72)
-- Deactivation: fail_rate > 0.4 AND total >= 5 → is_active = false
--
-- Usage: SELECT * FROM ext_api.recompute_confidence(row_id);
--        SELECT * FROM ext_api.recompute_confidence_for_element(element_row_id);

CREATE OR REPLACE FUNCTION ext_api.recompute_confidence(strategy_id BIGINT)
RETURNS TABLE (
    new_confidence   REAL,
    new_is_active    BOOLEAN,
    deactivated      BOOLEAN
) LANGUAGE plpgsql AS $$
DECLARE
    s RECORD;
    raw_ratio REAL;
    bayesian_adj REAL;
    decay_factor REAL;
    hours_since REAL;
    fail_rate REAL;
    total_execs INTEGER;
BEGIN
    SELECT * INTO s FROM ext_api.browser_dom_strategies WHERE id = strategy_id;
    IF NOT FOUND THEN
        new_confidence := 0.0;
        new_is_active := false;
        deactivated := false;
        RETURN NEXT;
        RETURN;
    END IF;

    total_execs := s.success_count + s.fail_count;

    -- Bayesian prior: (success + 1) / (total + 2)
    -- For 0/0, this gives 0.5 (neutral, near learn-time default)
    bayesian_adj := (s.success_count + 1.0) / GREATEST(total_execs + 2, 1);

    -- Time decay: 3-day half-life
    hours_since := EXTRACT(EPOCH FROM (NOW() - COALESCE(s.last_verified, s.created_at))) / 3600.0;
    decay_factor := EXP(-hours_since / 72.0);
    -- Clamp decay: never decay below 0.3 of the bayesian score
    decay_factor := GREATEST(decay_factor, 0.3);

    new_confidence := bayesian_adj * decay_factor;
    new_confidence := ROUND(GREATEST(0.0, LEAST(1.0, new_confidence))::numeric, 4)::real;

    -- Deactivation rule: fail_rate > 0.4 AND total >= 5
    fail_rate := CAST(s.fail_count AS REAL) / GREATEST(total_execs, 1);
    new_is_active := s.is_active;

    IF total_execs >= 5 AND fail_rate > 0.4 THEN
        new_is_active := false;
        deactivated := true;
    ELSE
        deactivated := false;
    END IF;

    -- If a previously inactive strategy just succeeded, reactivate
    IF NOT s.is_active AND s.success_count > 0 THEN
        new_is_active := true;
        deactivated := false;
    END IF;

    RETURN NEXT;
END;
$$;

-- ── Apply confidence to a single strategy ───────────────────────────────────

CREATE OR REPLACE FUNCTION ext_api.apply_feedback(
    p_strategy_id    BIGINT,
    p_success        BOOLEAN,
    p_action_id      BIGINT,
    p_session_id     UUID,
    p_element_id     TEXT DEFAULT '',
    p_page_url       TEXT DEFAULT '',
    p_state_id       TEXT DEFAULT 'root',
    p_strategy_type  TEXT DEFAULT '',
    p_error_code     TEXT DEFAULT '',
    p_duration_ms    INTEGER DEFAULT 0
) RETURNS TABLE (
    outcome_id       BIGINT,
    new_confidence   REAL,
    deactivated      BOOLEAN
) LANGUAGE plpgsql AS $$
DECLARE
    rec RECORD;
    c RECORD;
BEGIN
    -- Upsert outcome (idempotent by action_id + dom_strategy_id)
    INSERT INTO ext_api.browser_strategy_outcomes
        (dom_strategy_id, session_id, action_id, element_id, page_url, state_id, strategy_type, success, error_code, duration_ms)
    VALUES
        (p_strategy_id, p_session_id, p_action_id, p_element_id, p_page_url, p_state_id, p_strategy_type, p_success, p_error_code, p_duration_ms)
    ON CONFLICT (action_id, dom_strategy_id) DO NOTHING
    RETURNING id INTO outcome_id;

    IF outcome_id IS NULL THEN
        -- Already recorded (idempotent)
        SELECT id INTO outcome_id FROM ext_api.browser_strategy_outcomes
        WHERE action_id = p_action_id AND dom_strategy_id = p_strategy_id;
        SELECT rc.new_confidence, rc.deactivated INTO c
        FROM ext_api.recompute_confidence(p_strategy_id) rc;
        new_confidence := c.new_confidence;
        deactivated := c.deactivated;
        RETURN NEXT;
        RETURN;
    END IF;

    -- Update the strategy row
    IF p_success THEN
        UPDATE ext_api.browser_dom_strategies SET
            success_count = success_count + 1,
            last_success_at = NOW(),
            last_verified = NOW(),
            is_active = true  -- success always reactivates
        WHERE id = p_strategy_id;
    ELSE
        UPDATE ext_api.browser_dom_strategies SET
            fail_count = fail_count + 1,
            last_failure_at = NOW(),
            last_verified = NOW()
        WHERE id = p_strategy_id;
    END IF;

    -- Recompute confidence and check deactivation
    SELECT rc.new_confidence, rc.new_is_active, rc.deactivated INTO c
    FROM ext_api.recompute_confidence(p_strategy_id) rc;
    new_confidence := c.new_confidence;

    UPDATE ext_api.browser_dom_strategies SET
        confidence = c.new_confidence,
        is_active = c.new_is_active
    WHERE id = p_strategy_id;

    deactivated := c.deactivated;

    RETURN NEXT;
END;
$$;
