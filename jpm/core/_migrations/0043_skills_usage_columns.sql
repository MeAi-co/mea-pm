-- 0043_skills_usage_columns.sql
-- Add usage telemetry + lifecycle columns to public.skills.
-- Previously tracked in a sidecar file under the agent home's skills dir
-- (see core/tools/skill_usage.py). PG is the single source of truth, so the
-- sidecar is retired and usage is stored as real columns here.
-- Columns mirror the record-dict keys in skill_usage.py exactly:
--   created_by, use_count, view_count, patch_count,
--   last_used_at, last_viewed_at, last_patched_at,
--   state, pinned, archived_at   (created_at already exists)
-- Idempotent via IF NOT EXISTS — safe to re-run on any node.
ALTER TABLE public.skills ADD COLUMN IF NOT EXISTS created_by text;
ALTER TABLE public.skills ADD COLUMN IF NOT EXISTS use_count integer NOT NULL DEFAULT 0;
ALTER TABLE public.skills ADD COLUMN IF NOT EXISTS view_count integer NOT NULL DEFAULT 0;
ALTER TABLE public.skills ADD COLUMN IF NOT EXISTS patch_count integer NOT NULL DEFAULT 0;
ALTER TABLE public.skills ADD COLUMN IF NOT EXISTS last_used_at timestamptz;
ALTER TABLE public.skills ADD COLUMN IF NOT EXISTS last_viewed_at timestamptz;
ALTER TABLE public.skills ADD COLUMN IF NOT EXISTS last_patched_at timestamptz;
ALTER TABLE public.skills ADD COLUMN IF NOT EXISTS state text NOT NULL DEFAULT 'active';
ALTER TABLE public.skills ADD COLUMN IF NOT EXISTS pinned boolean NOT NULL DEFAULT false;
ALTER TABLE public.skills ADD COLUMN IF NOT EXISTS archived_at timestamptz;
