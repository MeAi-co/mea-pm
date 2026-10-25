-- Migration 0053: project-scoped skills — project_skills join + per-session active project
--
-- Schema: public
--
-- Phase 2 of the project fix: a project is a named bundle of skills that load
-- together. The project set IS the classification — co-membership in the set
-- satisfies any "base skill" need, so the skill-manager classifier is bypassed
-- when a project is active (classifier_runs = no project AND no skills loaded).
--
-- Two additions:
--   1. project_skills — flat join (project_id, skill_id, added_at), NO role.
--      The project set is authoritative; there is no role field to resolve.
--   2. sessions.project_id — the per-session ACTIVE project. A project is a
--      working context, not global state; one active project per session,
--      switchable on demand (/project bmw). Stored on the session so it
--      survives resume and carries downstream.
--
-- Idempotent: IF NOT EXISTS everywhere. The migration runner treats
-- "already exists" as benign and continues.

-- Flat project→skill join. No role column — the set IS the classification.
CREATE TABLE IF NOT EXISTS public.project_skills (
    project_id  int NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    skill_id    bigint NOT NULL REFERENCES public.skills(id) ON DELETE CASCADE,
    added_at    timestamp NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, skill_id)
);

CREATE INDEX IF NOT EXISTS idx_project_skills_skill
    ON public.project_skills(skill_id);

-- Per-session active project (NULL = no project active → classifier runs).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'sessions'
          AND column_name = 'project_id'
    ) THEN
        ALTER TABLE public.sessions ADD COLUMN project_id int;
    END IF;
END $$;

-- Reversible:
--   DROP TABLE public.project_skills;
--   ALTER TABLE public.sessions DROP COLUMN project_id;
