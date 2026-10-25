-- Migration 0022: Multi-State DOM Learning
--
-- Schema: ext_api
--
-- Changes:
--   ext_api.browser_dom_states         — New: state registry per page per session
--   ext_api.browser_dom_transitions    — Updated: add trigger_strategy_id, success/fail tracking
--   ext_api.compute_fingerprint — New: server-side fingerprint from elements array
--   ext_api.assign_state        — New: match fingerprint to existing state or create new
--
-- Design:
--   - States are scoped to (session_id, page_url, state_id)
--   - Fingerprint is a cheap hash of landmark roles + interactive count + depth distribution
--   - Transitions track which strategy triggered the state change
--   - is_transient marks toasts/tooltips for TTL cleanup

-- ── ext_api.browser_dom_states ─────────────────────────────────────────────────────
-- Registry of known UI states per page per session.

CREATE TABLE IF NOT EXISTS ext_api.browser_dom_states (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID NOT NULL REFERENCES ext_api.sessions(id) ON DELETE CASCADE,
    page_url        TEXT NOT NULL,
    state_id        TEXT NOT NULL,
    label           TEXT NOT NULL DEFAULT '',
    fingerprint     TEXT NOT NULL DEFAULT '',
    parent_state_id TEXT,
    is_transient    BOOLEAN NOT NULL DEFAULT false,
    first_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (session_id, page_url, state_id)
);

CREATE INDEX IF NOT EXISTS idx_browser_dom_states_page
    ON ext_api.browser_dom_states (session_id, page_url);
CREATE INDEX IF NOT EXISTS idx_browser_dom_states_fingerprint
    ON ext_api.browser_dom_states (page_url, fingerprint)
    WHERE fingerprint != '';

-- ── Update ext_api.browser_dom_transitions ──────────────────────────────────────────
-- Add strategy tracking and success/fail counters.

ALTER TABLE ext_api.browser_dom_transitions
    ADD COLUMN IF NOT EXISTS trigger_strategy_id BIGINT REFERENCES ext_api.browser_dom_strategies(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS success_count       INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS fail_count           INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_used_at         TIMESTAMPTZ;

-- Rename columns to match doc convention (from_state → from_state_id, etc.)
-- Wrapped in DO blocks for idempotency — only renames if old column still exists
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='ext_api' AND table_name='browser_dom_transitions' AND column_name='from_state') THEN
        ALTER TABLE ext_api.browser_dom_transitions RENAME COLUMN from_state TO from_state_id;
    END IF;
END $$;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='ext_api' AND table_name='browser_dom_transitions' AND column_name='to_state') THEN
        ALTER TABLE ext_api.browser_dom_transitions RENAME COLUMN to_state TO to_state_id;
    END IF;
END $$;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='ext_api' AND table_name='browser_dom_transitions' AND column_name='trigger_element') THEN
        ALTER TABLE ext_api.browser_dom_transitions RENAME COLUMN trigger_element TO trigger_element_id;
    END IF;
END $$;

-- Drop old unique constraint, add new one
ALTER TABLE ext_api.browser_dom_transitions DROP CONSTRAINT IF EXISTS browser_dom_transitions_session_id_page_url_from_state_to_state_trigger_element_trigger_action_key;
ALTER TABLE ext_api.browser_dom_transitions DROP CONSTRAINT IF EXISTS browser_dom_transitions_trigger_element_fkey;
ALTER TABLE ext_api.browser_dom_transitions DROP CONSTRAINT IF EXISTS browser_dom_transitions_trigger_element_id_fkey;
ALTER TABLE ext_api.browser_dom_transitions DROP CONSTRAINT IF EXISTS browser_dom_transitions_unique;

-- Change trigger_element_id from BIGINT to TEXT (we pass element_id strings, not DB PKs)
DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='ext_api' AND table_name='browser_dom_transitions' AND column_name='trigger_element_id'
          AND data_type = 'bigint'
    ) THEN
        ALTER TABLE ext_api.browser_dom_transitions ALTER COLUMN trigger_element_id TYPE TEXT;
    END IF;
END $$;

ALTER TABLE ext_api.browser_dom_transitions
    ADD CONSTRAINT browser_dom_transitions_unique
    UNIQUE (page_url, from_state_id, to_state_id, trigger_element_id);

-- ── Fingerprint Computation Function ───────────────────────────────────────
-- Server-side fingerprint from elements array.
-- Uses: sorted landmark roles + interactive count + depth distribution + dialog presence.
-- This is a cheap heuristic — the extension can send a better fingerprint later.

CREATE OR REPLACE FUNCTION ext_api.compute_fingerprint(elements JSONB)
RETURNS TEXT LANGUAGE plpgsql AS $$
DECLARE
    roles TEXT[];
    interactive_count INTEGER := 0;
    depth_dist TEXT;
    has_dialog BOOLEAN := false;
    el JSONB;
    role TEXT;
    depth_val INTEGER;
    depth_buckets INTEGER[] := ARRAY[0,0,0,0,0,0,0,0,0,0];
    result TEXT;
    sorted_roles TEXT;
BEGIN
    roles := ARRAY[]::TEXT[];
    
    FOR el IN SELECT * FROM jsonb_array_elements(elements)
    LOOP
        role := el->>'role';
        IF role IS NOT NULL AND role != '' THEN
            roles := array_append(roles, role);
        END IF;
        
        -- Count interactive elements
        IF el->>'tab_stop' IS NOT NULL OR el->>'clickable_score' IS NOT NULL THEN
            interactive_count := interactive_count + 1;
        END IF;
        
        -- Depth distribution (buckets of 2)
        depth_val := COALESCE((el->>'depth')::INTEGER, 0);
        IF depth_val / 2 < 10 THEN
            depth_buckets[depth_val / 2 + 1] := depth_buckets[depth_val / 2 + 1] + 1;
        END IF;
        
        -- Dialog detection
        IF role = 'dialog' OR (el->>'aria_label') ILIKE '%dialog%' OR (el->>'aria_label') ILIKE '%modal%' THEN
            has_dialog := true;
        END IF;
    END LOOP;
    
    -- Sort roles for stable hash
    SELECT array_agg(r ORDER BY r) INTO sorted_roles FROM unnest(roles) AS r;
    depth_dist := array_to_string(depth_buckets, ',');
    
    result := COALESCE(
        md5(
            COALESCE(array_to_string(roles, ','), '') || '|' ||
            interactive_count::TEXT || '|' ||
            depth_dist || '|' ||
            CASE WHEN has_dialog THEN '1' ELSE '0' END
        ),
        'empty'
    );
    
    RETURN substring(result, 1, 16);
END;
$$;

-- ── State Assignment Function ───────────────────────────────────────────────
-- Given a session_id, page_url, and elements array:
--   1. Compute fingerprint
--   2. If explicit state_id provided, use it (upsert into browser_dom_states)
--   3. Else match fingerprint to existing states for this page
--   4. Else create state_auto_<short_hash>
-- Returns: state_id

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

-- ── Transition Recording Function ───────────────────────────────────────────
-- Upsert a transition, increment success/fail counters.

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
