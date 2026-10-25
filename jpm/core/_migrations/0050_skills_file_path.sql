-- 0050_skills_file_path.sql
-- Add file_path column to skills table so the on-disk location of each
-- skill is a recorded fact (not a derived convention). This binds PG to
-- disk and lets readers locate a skill directly instead of guessing from
-- category. Idempotent — safe to re-run.

ALTER TABLE public.skills ADD COLUMN IF NOT EXISTS file_path text;
