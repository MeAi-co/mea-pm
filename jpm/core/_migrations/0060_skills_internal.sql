-- 0060_skills_internal.sql
-- Add `internal` flag to the skills table so the DB itself knows which skills
-- are host-agent-only (infra/ops wiring) and must NOT be distributed
-- to end-user bots. Complements the path-based INTERNAL_SKILL_DIR gate in
-- skill_utils.py with a first-class, queryable column — any sync/backfill can
-- filter `WHERE internal = false` to keep internal skills out of end-user sets.
-- Idempotent — safe to re-run.

ALTER TABLE public.skills ADD COLUMN IF NOT EXISTS internal boolean NOT NULL DEFAULT false;
