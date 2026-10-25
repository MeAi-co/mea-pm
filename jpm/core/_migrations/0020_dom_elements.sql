-- Migration 0020: DOM Elements & Page Learning
--
-- Schema: ext_api (same namespace as extension/bridge tables)
--
-- Tables:
--   ext_api.browser_dom_elements       — Per-element data: identity, position, DOM context, state
--   ext_api.browser_dom_strategies     — Multiple ways to reach each element (keyboard, pointer, nested)
--   ext_api.browser_dom_transitions    — State machine: which action leads from which state to which
--
-- Design principles:
--   - Elements are scoped to (session_id, page_url, state_id) — re-learn per UI state
--   - page_url strips query params so Gmail search variants share the same skeleton
--   - state_id = 'root' by default; menus/dialogs create new states with their own tab order
--   - is_stale flag triggers re-learn on page re-render without URL change
--   - Multiple strategies per element, verified at learn time, confidence-scored

-- ── ext_api.browser_dom_elements ──────────────────────────────────────────────────
-- Every discoverable element on a page, with full identity, position, and state.

CREATE TABLE IF NOT EXISTS ext_api.browser_dom_elements (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID NOT NULL REFERENCES ext_api.sessions(id) ON DELETE CASCADE,
    page_url        TEXT NOT NULL,           -- stable URL (no query params)
    page_title      TEXT NOT NULL DEFAULT '',
    state_id        TEXT NOT NULL DEFAULT 'root',  -- 'root', 'menu_open', 'compose_open', etc.

    -- Identity
    element_id      TEXT NOT NULL,           -- 'el_0', 'el_1', etc.
    tab_stop        INTEGER,                 -- NULL if not keyboard-reachable
    tag             TEXT,
    type            TEXT,
    role            TEXT,
    computed_role   TEXT,

    -- Names & labels
    name            TEXT,
    computed_name   TEXT,
    text            TEXT,
    aria_label      TEXT,
    parent_name     TEXT,
    label_for       TEXT,

    -- Position
    bbox_x          INTEGER,
    bbox_y          INTEGER,
    bbox_w          INTEGER,
    bbox_h          INTEGER,
    depth           INTEGER,

    -- DOM context
    parent_tag      TEXT,
    parent_role     TEXT,
    container_path  JSONB,                   -- array of {tag, role, aria_label, id}
    selector_candidates JSONB,               -- array of CSS selectors

    -- State
    tab_index       TEXT,
    pressed         TEXT,
    selected        TEXT,
    current         TEXT,
    expanded        TEXT,
    checked         TEXT,
    has_popup       TEXT,
    controls        TEXT,
    owns            TEXT,

    -- Attributes
    id_attr         TEXT,
    class_attr      TEXT,
    name_attr       TEXT,
    href            TEXT,
    value           TEXT,
    placeholder     TEXT,
    tooltip         TEXT,
    source          TEXT DEFAULT 'light-dom',

    -- Scoring
    clickable_score REAL,
    visible         BOOLEAN,
    in_viewport     BOOLEAN,
    enabled         BOOLEAN,

    -- Metadata
    first_seen_at   TIMESTAMP NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMP NOT NULL DEFAULT now(),
    seen_count      INTEGER NOT NULL DEFAULT 1,
    is_stale        BOOLEAN NOT NULL DEFAULT false,

    UNIQUE (session_id, page_url, state_id, element_id)
);

CREATE INDEX IF NOT EXISTS idx_browser_dom_elements_session
    ON ext_api.browser_dom_elements (session_id);
CREATE INDEX IF NOT EXISTS idx_browser_dom_elements_url
    ON ext_api.browser_dom_elements (page_url);
CREATE INDEX IF NOT EXISTS idx_browser_dom_elements_state
    ON ext_api.browser_dom_elements (session_id, page_url, state_id);
CREATE INDEX IF NOT EXISTS idx_browser_dom_elements_tab_stop
    ON ext_api.browser_dom_elements (session_id, page_url, state_id, tab_stop)
    WHERE tab_stop IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_browser_dom_elements_stale
    ON ext_api.browser_dom_elements (session_id, is_stale)
    WHERE is_stale = true;

-- ── ext_api.browser_dom_strategies ────────────────────────────────────────────────
-- Multiple ways to reach each element, verified at learn time.

CREATE TABLE IF NOT EXISTS ext_api.browser_dom_strategies (
    id              BIGSERIAL PRIMARY KEY,
    element_id      BIGINT NOT NULL REFERENCES ext_api.browser_dom_elements(id) ON DELETE CASCADE,
    strategy_type   TEXT NOT NULL
                    CHECK (strategy_type IN (
                        'keyboard_focus',     -- tab_stop = N, then Enter/Space
                        'keyboard_activate',  -- specific key combo
                        'pointer_click',      -- click by bbox coordinates
                        'nested_path',        -- ancestor_id + offset
                        'selector'            -- CSS selector
                    )),
    tab_steps       INTEGER,                 -- for keyboard_focus: how many tabs from page load
    activate_key    TEXT,                     -- for keyboard_activate: 'Enter', 'Space', 'ArrowDown'
    ancestor_id     BIGINT REFERENCES ext_api.browser_dom_elements(id),  -- for nested_path
    ancestor_offset INTEGER,                  -- for nested_path: "3rd child of ancestor"
    css_selector    TEXT,                     -- for selector strategy
    confidence      REAL NOT NULL DEFAULT 0.5,
    last_verified   TIMESTAMP,
    last_failed     TIMESTAMP,
    fail_count      INTEGER NOT NULL DEFAULT 0,
    success_count   INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMP NOT NULL DEFAULT now(),

    UNIQUE (element_id, strategy_type)
);

CREATE INDEX IF NOT EXISTS idx_browser_dom_strategies_element
    ON ext_api.browser_dom_strategies (element_id);
CREATE INDEX IF NOT EXISTS idx_browser_dom_strategies_confident
    ON ext_api.browser_dom_strategies (element_id, confidence DESC);

-- ── ext_api.browser_dom_transitions ──────────────────────────────────────────────
-- State machine: which action on which element leads from which state to which.

CREATE TABLE IF NOT EXISTS ext_api.browser_dom_transitions (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID NOT NULL REFERENCES ext_api.sessions(id) ON DELETE CASCADE,
    page_url        TEXT NOT NULL,
    from_state      TEXT NOT NULL,
    to_state        TEXT NOT NULL,
    trigger_element BIGINT REFERENCES ext_api.browser_dom_elements(id) ON DELETE SET NULL,
    trigger_action  TEXT NOT NULL,            -- 'click', 'type', 'hover', 'navigate'
    trigger_key     TEXT,                     -- 'Enter', 'Space', etc. for keyboard activation
    frequency       INTEGER NOT NULL DEFAULT 1,
    last_observed   TIMESTAMP NOT NULL DEFAULT now(),
    created_at      TIMESTAMP NOT NULL DEFAULT now(),

    UNIQUE (session_id, page_url, from_state, to_state, trigger_element, trigger_action)
);

CREATE INDEX IF NOT EXISTS idx_browser_dom_transitions_session
    ON ext_api.browser_dom_transitions (session_id, page_url);
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='ext_api' AND table_name='browser_dom_transitions' AND column_name='from_state_id') THEN
        CREATE INDEX IF NOT EXISTS idx_browser_dom_transitions_from ON ext_api.browser_dom_transitions (session_id, page_url, from_state_id);
    END IF;
END $$;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='ext_api' AND table_name='browser_dom_transitions' AND column_name='to_state_id') THEN
        CREATE INDEX IF NOT EXISTS idx_browser_dom_transitions_to ON ext_api.browser_dom_transitions (session_id, page_url, to_state_id);
    END IF;
END $$;
