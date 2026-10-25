-- 0075_drop_class_b_dead_tables.sql
-- Drop the Class-B dead tables: JPM v3 knowledge-graph scaffolding that was
-- designed but never wired to any live code path. JPM v3 has been superseded
-- by JPM v4 / native JPM, so this scaffolding is dead.
--
-- Verified before drop (hub, 2026-10-12):
--   * 0 rows in every table
--   * 0 live-code references (only one-off migration scripts + .venv noise)
--   * 0 FK references from any other table
--
-- RESERVED tables are explicitly NOT touched here: plugin_usage, usage_logs,
-- use_cases (reserved for planned features).
--
-- Idempotent: DROP TABLE IF EXISTS ... CASCADE.

DROP TABLE IF EXISTS public.explanation_evidence CASCADE;
DROP TABLE IF EXISTS public.explanations CASCADE;
DROP TABLE IF EXISTS public.fact_links CASCADE;
DROP TABLE IF EXISTS public.fact_tags CASCADE;
DROP TABLE IF EXISTS public.pattern_evidence CASCADE;
DROP TABLE IF EXISTS public.pattern_triggers CASCADE;
DROP TABLE IF EXISTS public.patterns_history CASCADE;
DROP TABLE IF EXISTS public.reflection_queue CASCADE;
DROP TABLE IF EXISTS public.synthesis_queue CASCADE;

-- Orphaned sequences owned by the dropped tables (CASCADE on the table drop
-- normally removes these, but drop explicitly for safety on nodes where the
-- OWNED BY linkage was never established).
DROP SEQUENCE IF EXISTS public.explanations_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.fact_links_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.patterns_history_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.reflection_queue_id_seq CASCADE;
DROP SEQUENCE IF EXISTS public.synthesis_queue_id_seq CASCADE;
