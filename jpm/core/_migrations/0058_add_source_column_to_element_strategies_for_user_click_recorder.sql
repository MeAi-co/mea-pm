-- Migration 0058: Add source column to element strategies for user-click recorder
--
-- Schema: ext_api
--
-- Changes:
--   ext_api.browser_element_strategies — Add source column to distinguish
--     user-recorded ground-truth actions (highest confidence) from
--     agent-learned ones. Also add user_click_count for the recorder.
--
-- Design:
--   - source: 'user' (recorded from real human clicks, isTrusted=true) vs
--     'agent' (learned from agent-driven glossary_learn). User-recorded
--     strategies are ground truth and should rank above agent-learned ones.
--   - user_click_count: how many times a real user clicked this element.
--     Lets the agent know an action is human-verified and how often.

-- ── ext_api.browser_element_strategies ──────────────────────────────────────
-- Add source + user_click_count columns (idempotent).

ALTER TABLE ext_api.browser_element_strategies
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'agent'
        CHECK (source IN ('user', 'agent'));

ALTER TABLE ext_api.browser_element_strategies
    ADD COLUMN IF NOT EXISTS user_click_count INTEGER NOT NULL DEFAULT 0;

-- Index: user-recorded strategies are the highest-confidence ground truth.
CREATE INDEX IF NOT EXISTS idx_elem_strat_source
    ON ext_api.browser_element_strategies (source, user_click_count DESC)
    WHERE source = 'user';
