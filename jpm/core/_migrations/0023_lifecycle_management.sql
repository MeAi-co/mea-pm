-- Migration 0023: Lifecycle Management — Stale, TTL, State Caps, Cleanup
--
-- Schema: ext_api
--
-- Changes:
--   ext_api.cleanup_stale_elements()  — Mark elements is_stale when re-learned and missing
--   ext_api.cleanup_transient_states() — Remove/expire transient states past TTL
--   ext_api.enforce_state_cap()       — Drop oldest auto states per page beyond cap
--   ext_api.sanitize_state_id()       — Validate and sanitize state_id input
--   ext_api.lifecycle_metrics()       — Aggregated lifecycle observability
--
-- Design:
--   - Stale elements are marked, not deleted (plan prefers non-stale but can use stale as fallback)
--   - Transient states (toasts, tooltips) expire after 5 minutes by default
--   - Auto states capped at 50 per page per session (configurable)
--   - All cleanup is idempotent and safe to run on a cron schedule
--   - state_id sanitization prevents injection and limits length to 64 chars

-- ── Constants ─────────────────────────────────────────────────────────────
-- Configurable via env, defaults here for self-documentation
-- TRANSIENT_TTL_MINUTES: How long transient states live before cleanup (default: 5)
-- MAX_AUTO_STATES_PER_PAGE: Max auto-generated states per page per session (default: 50)
-- STALE_GRACE_PERIOD_MINUTES: How long before a missing element is marked stale (default: 0, immediate)

-- ── Stale Element Marking ─────────────────────────────────────────────────
-- When a state is re-learned, elements that were present before but are
-- missing in the new learn are marked is_stale = true.
-- This is called AFTER the new elements are inserted.

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

-- ── Transient State Cleanup ──────────────────────────────────────────────
-- Expire transient states (toasts, tooltips) that haven't been seen recently.
-- Default TTL: 5 minutes. States are soft-deleted (is_stale on elements).

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

-- ── State Cap Enforcement ─────────────────────────────────────────────────
-- Enforce a maximum number of auto-generated states per page per session.
-- When the cap is exceeded, the oldest auto states are cleaned up.
-- Explicitly named states (not state_auto_*) are never removed.

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

-- ── State ID Sanitization ─────────────────────────────────────────────────
-- Validate and sanitize state_id input.
-- Rules: max 64 chars, alphanumeric + underscore + hyphen only.
-- Returns cleaned state_id or raises exception.

CREATE OR REPLACE FUNCTION ext_api.sanitize_state_id(
    p_state_id TEXT
) RETURNS TEXT LANGUAGE plpgsql AS $$
DECLARE
    cleaned TEXT;
BEGIN
    -- Strip non-alphanumeric, non-underscore, non-hyphen characters
    cleaned := regexp_replace(p_state_id, '[^a-zA-Z0-9_-]', '', 'g');
    
    -- Truncate to 64 chars
    cleaned := substring(cleaned, 1, 64);
    
    -- Default to 'root' if empty after sanitization
    IF cleaned = '' OR cleaned IS NULL THEN
        cleaned := 'root';
    END IF;
    
    RETURN cleaned;
END;
$$;

-- ── Lifecycle Metrics ────────────────────────────────────────────────────
-- Aggregated observability for lifecycle management.

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
