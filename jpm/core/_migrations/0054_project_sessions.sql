-- 0054_project_sessions.sql
-- Many-to-many project <-> session mapping.
-- Replaces the stale 1:1 `sessions.project_id` column (only held one active
-- project per session) with a proper join table, so a project can span many
-- sessions and a session can belong to many projects. This is what lets a
-- user switch projects without restarting/reloading sessions.
--
-- Mirrors the `project_skills` join-table pattern from migration 0053.
-- Additive + idempotent; safe to re-run.

-- 1. Join table
CREATE TABLE IF NOT EXISTS public.project_sessions (
    project_id  integer     NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    session_id  text        NOT NULL REFERENCES public.sessions(id) ON DELETE CASCADE,
    added_at    timestamp   NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, session_id)
);

CREATE INDEX IF NOT EXISTS idx_project_sessions_session
    ON public.project_sessions(session_id);

-- 2. Backfill existing 1:1 bindings into the join table.
-- Guarded so it only runs while `sessions.project_id` still exists. On an
-- already-applied DB the column is gone, so a bare INSERT would fail every
-- re-run and the runner (correctly) would refuse to mark 0054 applied —
-- leaving this error to scream on every startup. Guarding makes the backfill
-- a no-op on re-runs, so 0054 becomes fully idempotent.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_schema = 'public'
       AND table_name   = 'sessions'
       AND column_name  = 'project_id'
  ) THEN
    INSERT INTO public.project_sessions (project_id, session_id)
    SELECT project_id, id
      FROM public.sessions
     WHERE project_id IS NOT NULL
    ON CONFLICT (project_id, session_id) DO NOTHING;
  END IF;
END $$;

-- 3. Drop the stale 1:1 column. Versioned here so it runs exactly once.
ALTER TABLE public.sessions DROP COLUMN IF EXISTS project_id;
