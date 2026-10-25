-- Migration 0038: Browser Prefix Rename
--
-- Schema: ext_api
--
-- Changes:
--   Rename 7 learning tables to browser_* prefix for consistency with the
--   new spatial browser schema. PG renames are metadata-only (no data copy);
--   indexes, FKs, and constraints follow the table automatically.
--
--   Recreate 8 PL/pgSQL functions whose bodies reference the renamed tables.
--   PG does NOT rewrite function bodies on table rename, so the old functions
--   would silently reference non-existent tables at runtime. Recreating them
--   with the new names keeps them valid.
--
-- Tables renamed:
--   dom_elements        -> browser_dom_elements
--   dom_strategies      -> browser_dom_strategies
--   strategy_outcomes   -> browser_strategy_outcomes
--   dom_states          -> browser_dom_states
--   dom_transitions     -> browser_dom_transitions
--   element_strategies  -> browser_element_strategies
--   page_signatures     -> browser_page_signatures
--
-- Design:
--   - RENAME TO is idempotent-safe: wrapped in DO blocks that check existence
--   - Functions recreated via CREATE OR REPLACE (idempotent)
--   - Index names are NOT renamed (PG keeps them; schema_audit only checks
--     existence, not naming) — avoids churn on 20+ index renames

-- ── Table renames ─────────────────────────────────────────────────────────

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='ext_api' AND table_name='dom_elements') THEN
        ALTER TABLE ext_api.dom_elements RENAME TO browser_dom_elements;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='ext_api' AND table_name='dom_strategies') THEN
        ALTER TABLE ext_api.dom_strategies RENAME TO browser_dom_strategies;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='ext_api' AND table_name='strategy_outcomes') THEN
        ALTER TABLE ext_api.strategy_outcomes RENAME TO browser_strategy_outcomes;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='ext_api' AND table_name='dom_states') THEN
        ALTER TABLE ext_api.dom_states RENAME TO browser_dom_states;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='ext_api' AND table_name='dom_transitions') THEN
        ALTER TABLE ext_api.dom_transitions RENAME TO browser_dom_transitions;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='ext_api' AND table_name='element_strategies') THEN
        ALTER TABLE ext_api.element_strategies RENAME TO browser_element_strategies;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='ext_api' AND table_name='page_signatures') THEN
        ALTER TABLE ext_api.page_signatures RENAME TO browser_page_signatures;
    END IF;
END $$;


-- ── Index renames (match migration file declarations) ───────────────

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='ext_api' AND indexname='idx_dom_elements_session') THEN
        ALTER INDEX ext_api.idx_dom_elements_session RENAME TO idx_browser_dom_elements_session;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='ext_api' AND indexname='idx_dom_elements_stale') THEN
        ALTER INDEX ext_api.idx_dom_elements_stale RENAME TO idx_browser_dom_elements_stale;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='ext_api' AND indexname='idx_dom_elements_state') THEN
        ALTER INDEX ext_api.idx_dom_elements_state RENAME TO idx_browser_dom_elements_state;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='ext_api' AND indexname='idx_dom_elements_tab_stop') THEN
        ALTER INDEX ext_api.idx_dom_elements_tab_stop RENAME TO idx_browser_dom_elements_tab_stop;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='ext_api' AND indexname='idx_dom_elements_url') THEN
        ALTER INDEX ext_api.idx_dom_elements_url RENAME TO idx_browser_dom_elements_url;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='ext_api' AND indexname='idx_dom_states_fingerprint') THEN
        ALTER INDEX ext_api.idx_dom_states_fingerprint RENAME TO idx_browser_dom_states_fingerprint;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='ext_api' AND indexname='idx_dom_states_page') THEN
        ALTER INDEX ext_api.idx_dom_states_page RENAME TO idx_browser_dom_states_page;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='ext_api' AND indexname='idx_dom_strategies_active') THEN
        ALTER INDEX ext_api.idx_dom_strategies_active RENAME TO idx_browser_dom_strategies_active;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='ext_api' AND indexname='idx_dom_strategies_confident') THEN
        ALTER INDEX ext_api.idx_dom_strategies_confident RENAME TO idx_browser_dom_strategies_confident;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='ext_api' AND indexname='idx_dom_strategies_element') THEN
        ALTER INDEX ext_api.idx_dom_strategies_element RENAME TO idx_browser_dom_strategies_element;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='ext_api' AND indexname='idx_dom_transitions_from') THEN
        ALTER INDEX ext_api.idx_dom_transitions_from RENAME TO idx_browser_dom_transitions_from;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='ext_api' AND indexname='idx_dom_transitions_session') THEN
        ALTER INDEX ext_api.idx_dom_transitions_session RENAME TO idx_browser_dom_transitions_session;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='ext_api' AND indexname='idx_dom_transitions_to') THEN
        ALTER INDEX ext_api.idx_dom_transitions_to RENAME TO idx_browser_dom_transitions_to;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='ext_api' AND indexname='idx_strategy_outcomes_session') THEN
        ALTER INDEX ext_api.idx_strategy_outcomes_session RENAME TO idx_browser_strategy_outcomes_session;
    END IF;
END $$;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname='ext_api' AND indexname='idx_strategy_outcomes_strategy') THEN
        ALTER INDEX ext_api.idx_strategy_outcomes_strategy RENAME TO idx_browser_strategy_outcomes_strategy;
    END IF;
END $$;

-- ── Recreate functions (bodies reference renamed tables) ─────────────────

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

CREATE OR REPLACE FUNCTION ext_api.assign_state(
    p_session_id    UUID,
    p_page_url      TEXT,
    p_elements      JSONB,
    p_explicit_state_id TEXT DEFAULT '',
    p_parent_state_id   TEXT DEFAULT ''
) RETURNS TEXT LANGUAGE plpgsql AS $$
DECLARE
    fp TEXT;
    matched_state TEXT;
    auto_id TEXT;
BEGIN
    fp := ext_api.compute_fingerprint(p_elements);
    
    -- If explicit state_id provided, use it
    IF p_explicit_state_id != '' THEN
        INSERT INTO ext_api.browser_dom_states (session_id, page_url, state_id, fingerprint, parent_state_id, last_seen_at)
        VALUES (p_session_id, p_page_url, p_explicit_state_id, fp, 
                NULLIF(p_parent_state_id, ''), NOW())
        ON CONFLICT (session_id, page_url, state_id)
        DO UPDATE SET last_seen_at = NOW(), fingerprint = fp,
                      parent_state_id = COALESCE(NULLIF(p_parent_state_id, ''), ext_api.browser_dom_states.parent_state_id);
        RETURN p_explicit_state_id;
    END IF;
    
    -- Try to match fingerprint to existing states for this page
    SELECT state_id INTO matched_state
    FROM ext_api.browser_dom_states
    WHERE page_url = p_page_url
      AND fingerprint = fp
      AND fingerprint != ''
    ORDER BY last_seen_at DESC
    LIMIT 1;
    
    IF FOUND THEN
        -- Update last_seen_at
        UPDATE ext_api.browser_dom_states SET last_seen_at = NOW()
        WHERE page_url = p_page_url AND state_id = matched_state;
        RETURN matched_state;
    END IF;
    
    -- Create auto state
    auto_id := 'state_auto_' || substring(fp, 1, 8);
    
    INSERT INTO ext_api.browser_dom_states (session_id, page_url, state_id, fingerprint, parent_state_id)
    VALUES (p_session_id, p_page_url, auto_id, fp, NULLIF(p_parent_state_id, ''))
    ON CONFLICT (session_id, page_url, state_id) DO NOTHING;
    
    RETURN auto_id;
END;
$$;

CREATE OR REPLACE FUNCTION ext_api.record_transition(
    p_session_id        UUID,
    p_page_url          TEXT,
    p_from_state_id     TEXT,
    p_to_state_id       TEXT,
    p_trigger_element_id TEXT DEFAULT '',
    p_trigger_strategy_id BIGINT DEFAULT NULL,
    p_trigger_action    TEXT DEFAULT 'click',
    p_success           BOOLEAN DEFAULT true
) RETURNS BIGINT LANGUAGE plpgsql AS $$
DECLARE
    trans_id BIGINT;
BEGIN
    INSERT INTO ext_api.browser_dom_transitions
        (session_id, page_url, from_state_id, to_state_id, trigger_element_id,
         trigger_strategy_id, trigger_action, success_count, fail_count, last_used_at)
    VALUES
        (p_session_id, p_page_url, p_from_state_id, p_to_state_id, p_trigger_element_id,
         p_trigger_strategy_id, p_trigger_action,
         CASE WHEN p_success THEN 1 ELSE 0 END,
         CASE WHEN p_success THEN 0 ELSE 1 END,
         NOW())
    ON CONFLICT (page_url, from_state_id, to_state_id, trigger_element_id)
    DO UPDATE SET
        success_count = ext_api.browser_dom_transitions.success_count + CASE WHEN p_success THEN 1 ELSE 0 END,
        fail_count = ext_api.browser_dom_transitions.fail_count + CASE WHEN p_success THEN 0 ELSE 1 END,
        last_used_at = NOW(),
        trigger_strategy_id = COALESCE(p_trigger_strategy_id, ext_api.browser_dom_transitions.trigger_strategy_id)
    RETURNING id INTO trans_id;
    
    RETURN trans_id;
END;
$$;

CREATE OR REPLACE FUNCTION ext_api.mark_stale_elements(
    p_session_id    UUID,
    p_page_url      TEXT,
    p_state_id      TEXT,
    p_current_element_ids TEXT[]
) RETURNS INTEGER LANGUAGE plpgsql AS $$
DECLARE
    stale_count INTEGER;
BEGIN
    UPDATE ext_api.browser_dom_elements SET
        is_stale = true,
        last_seen_at = NOW()
    WHERE session_id = p_session_id
      AND page_url = p_page_url
      AND state_id = p_state_id
      AND element_id != ALL(p_current_element_ids)
      AND NOT is_stale;
    
    GET DIAGNOSTICS stale_count = ROW_COUNT;
    RETURN stale_count;
END;
$$;

CREATE OR REPLACE FUNCTION ext_api.cleanup_transient_states(
    p_ttl_minutes INTEGER DEFAULT 5
) RETURNS TABLE (
    state_id       TEXT,
    page_url       TEXT,
    elements_marked INTEGER
) LANGUAGE plpgsql AS $$
DECLARE
    rec RECORD;
    marked INTEGER;
    sess_id UUID;
BEGIN
    FOR rec IN
        SELECT s.id, s.state_id, s.page_url, s.session_id
        FROM ext_api.browser_dom_states s
        WHERE s.is_transient
          AND s.last_seen_at < NOW() - (p_ttl_minutes || ' minutes')::INTERVAL
    LOOP
        sess_id := rec.session_id;
        
        UPDATE ext_api.browser_dom_elements SET
            is_stale = true,
            last_seen_at = NOW()
        WHERE session_id = sess_id
        AND page_url = rec.page_url
        AND state_id = rec.state_id
        AND NOT is_stale;
        
        GET DIAGNOSTICS marked = ROW_COUNT;
        
        state_id := rec.state_id;
        page_url := rec.page_url;
        elements_marked := marked;
        RETURN NEXT;
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION ext_api.enforce_state_cap(
    p_max_states INTEGER DEFAULT 50
) RETURNS TABLE (
    page_url       TEXT,
    session_id     UUID,
    removed_count  INTEGER
) LANGUAGE plpgsql AS $$
DECLARE
    rec RECORD;
    to_remove TEXT[];
    removed INTEGER;
    sess_id UUID;
BEGIN
    FOR rec IN
        SELECT s.session_id, s.page_url, COUNT(*) as total
        FROM ext_api.browser_dom_states s
        WHERE s.state_id LIKE 'state_auto_%'
        GROUP BY s.session_id, s.page_url
        HAVING COUNT(*) > p_max_states
    LOOP
        sess_id := rec.session_id;
        
        -- Find the oldest auto states to remove
        SELECT array_agg(sub.state_id) INTO to_remove
        FROM (
            SELECT st.state_id
            FROM ext_api.browser_dom_states st
            WHERE st.session_id = sess_id
              AND st.page_url = rec.page_url
              AND st.state_id LIKE 'state_auto_%'
            ORDER BY st.last_seen_at ASC
            OFFSET p_max_states
            LIMIT rec.total - p_max_states
        ) sub;
        
        IF to_remove IS NOT NULL AND array_length(to_remove, 1) > 0 THEN
            -- Mark elements as stale
            UPDATE ext_api.browser_dom_elements SET is_stale = true
            WHERE session_id = sess_id
              AND page_url = rec.page_url
              AND state_id = ANY(to_remove)
              AND NOT is_stale;
            
            -- Remove the states
            DELETE FROM ext_api.browser_dom_states
            WHERE session_id = sess_id
              AND page_url = rec.page_url
              AND state_id = ANY(to_remove);
            
            GET DIAGNOSTICS removed = ROW_COUNT;
            
            page_url := rec.page_url;
            session_id := sess_id;
            removed_count := removed;
            RETURN NEXT;
        END IF;
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION ext_api.lifecycle_metrics()
RETURNS TABLE (
    total_states            BIGINT,
    transient_states        BIGINT,
    auto_states             BIGINT,
    named_states            BIGINT,
    stale_elements          BIGINT,
    active_elements         BIGINT,
    pages_with_states       BIGINT,
    max_states_per_page     BIGINT,
    avg_states_per_page     NUMERIC
) LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    SELECT
        (SELECT COUNT(*) FROM ext_api.browser_dom_states)::BIGINT,
        (SELECT COUNT(*) FROM ext_api.browser_dom_states WHERE is_transient)::BIGINT,
        (SELECT COUNT(*) FROM ext_api.browser_dom_states WHERE state_id LIKE 'state_auto_%')::BIGINT,
        (SELECT COUNT(*) FROM ext_api.browser_dom_states WHERE state_id NOT LIKE 'state_auto_%')::BIGINT,
        (SELECT COUNT(*) FROM ext_api.browser_dom_elements WHERE is_stale)::BIGINT,
        (SELECT COUNT(*) FROM ext_api.browser_dom_elements WHERE NOT is_stale)::BIGINT,
        (SELECT COUNT(DISTINCT (session_id, page_url)) FROM ext_api.browser_dom_states)::BIGINT,
        COALESCE((SELECT MAX(cnt) FROM (SELECT COUNT(*) as cnt FROM ext_api.browser_dom_states GROUP BY session_id, page_url) sub), 0)::BIGINT,
        COALESCE((SELECT ROUND(AVG(cnt), 1) FROM (SELECT COUNT(*) as cnt FROM ext_api.browser_dom_states GROUP BY session_id, page_url) sub), 0)::NUMERIC;
END;
$$;

