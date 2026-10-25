-- Migration 0019: Page Glossary — learned element strategies
--
-- Schema: ext_api (same namespace as extension/bridge tables)
--
-- Tables:
--   ext_api.browser_page_signatures      — Page identity (domain + path pattern + structural hash)
--   ext_api.browser_element_strategies   — Learned strategies for logical elements on a page
--   ext_api.browser_strategy_outcomes    — Per-action outcome log for analysis & decay
--
-- Design principles:
--   - Write-only first: data accumulates before reads are enabled
--   - Soft versioning: layout_version + is_active for A/B test recovery
--   - Never delete: deactivate instead, keep history for analysis
--   - Stats-driven: success/failure counts enable automatic decay

-- ── ext_api.browser_page_signatures ──────────────────────────────────────────────
-- Page identity. Coarse (domain + path_pattern) + fine (signature_hash).
-- signature_hash detects "same URL pattern but different layout" (A/B tests, redesigns).

CREATE TABLE IF NOT EXISTS ext_api.browser_page_signatures (
    id              BIGSERIAL PRIMARY KEY,
    domain          TEXT NOT NULL,                    -- e.g. 'app.example.com'
    path_pattern    TEXT NOT NULL,                    -- '/dashboard/:id' or '/settings'
    signature_hash  TEXT NOT NULL,                    -- hash of structural fingerprint
    title_pattern   TEXT,                             -- optional regex for page title
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (domain, path_pattern, signature_hash)
);

CREATE INDEX IF NOT EXISTS idx_page_sig_domain_path
    ON ext_api.browser_page_signatures (domain, path_pattern);

-- ── ext_api.browser_element_strategies ────────────────────────────────────────────
-- Learned strategies for logical elements on a page.
-- One row per logical_name per page_signature.

CREATE TABLE IF NOT EXISTS ext_api.browser_element_strategies (
    id                  BIGSERIAL PRIMARY KEY,
    page_signature_id   BIGINT NOT NULL REFERENCES ext_api.browser_page_signatures(id) ON DELETE CASCADE,

    -- How the agent (or human) refers to this element
    logical_name        TEXT NOT NULL,                 -- 'login_button', 'search_input', 'add_to_cart'
    accessible_name     TEXT,                          -- last known accessible name / text

    -- Ranked ways to find it (most reliable first)
    selector_candidates JSONB NOT NULL DEFAULT '[]'::jsonb,  -- ["[data-testid=login]", "#login-btn", ...]
    preferred_strategy  TEXT NOT NULL DEFAULT 'native-fast',  -- native-fast | pointer | mouse | ...

    -- Stats for ranking & decay
    success_count       INTEGER NOT NULL DEFAULT 0,
    failure_count       INTEGER NOT NULL DEFAULT 0,
    last_success_at     TIMESTAMPTZ,
    last_failure_at     TIMESTAMPTZ,
    last_seen_score     REAL,                          -- clickable_score from last discover

    -- Soft versioning
    layout_version      INTEGER NOT NULL DEFAULT 1,
    is_active           BOOLEAN NOT NULL DEFAULT true,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (page_signature_id, logical_name)
);

CREATE INDEX IF NOT EXISTS idx_elem_strat_page
    ON ext_api.browser_element_strategies (page_signature_id)
    WHERE is_active;

CREATE INDEX IF NOT EXISTS idx_elem_strat_logical
    ON ext_api.browser_element_strategies (logical_name);

-- ── ext_api.browser_strategy_outcomes ────────────────────────────────────────────
-- Per-action outcome log for deeper analysis and decay calculations.

CREATE TABLE IF NOT EXISTS ext_api.browser_strategy_outcomes (
    id                  BIGSERIAL PRIMARY KEY,
    element_strategy_id BIGINT REFERENCES ext_api.browser_element_strategies(id) ON DELETE SET NULL,
    session_id          UUID REFERENCES ext_api.sessions(id) ON DELETE SET NULL,
    logical_name        TEXT,
    success             BOOLEAN NOT NULL,
    strategy_used       TEXT,
    error_code          TEXT,                          -- structured error code from diagnostics
    duration_ms         INTEGER NOT NULL DEFAULT 0,
    page_url            TEXT NOT NULL DEFAULT '',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='ext_api' AND table_name='browser_strategy_outcomes' AND column_name='element_strategy_id') THEN
        CREATE INDEX IF NOT EXISTS idx_strat_outcomes_strategy ON ext_api.browser_strategy_outcomes (element_strategy_id, created_at DESC);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_strat_outcomes_session
    ON ext_api.browser_strategy_outcomes (session_id, created_at DESC);

-- ── Auto-update updated_at trigger ──────────────────────────────────────

CREATE OR REPLACE FUNCTION ext_api.update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_browser_page_signatures_updated_at ON ext_api.browser_page_signatures;
CREATE TRIGGER trg_browser_page_signatures_updated_at
    BEFORE UPDATE ON ext_api.browser_page_signatures
    FOR EACH ROW EXECUTE FUNCTION ext_api.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_browser_element_strategies_updated_at ON ext_api.browser_element_strategies;
CREATE TRIGGER trg_browser_element_strategies_updated_at
    BEFORE UPDATE ON ext_api.browser_element_strategies
    FOR EACH ROW EXECUTE FUNCTION ext_api.update_updated_at_column();
