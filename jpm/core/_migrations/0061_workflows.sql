-- 0061_workflows.sql
-- Workflows — bind skills to named, runnable scripts.
--
-- The mental model: projects → skills → workflows. A skill (e.g. create-pdf)
-- can have MULTIPLE named workflows (report-pdf, invoice-pdf, scan-to-pdf),
-- each bound to a specific script. The agent looks up a skill's workflows,
-- picks the right one, runs it in the background, and records which one it
-- used — so next time it reaches for the proven path instead of re-deriving.
--
-- Mirrors the project_skills / skill_files join-table pattern. Additive +
-- idempotent; safe to re-run.

CREATE TABLE IF NOT EXISTS public.workflows (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    skill_id      bigint      NOT NULL REFERENCES public.skills(id) ON DELETE CASCADE,
    name          text        NOT NULL,
    description   text        NOT NULL DEFAULT '',
    script_path   text        NOT NULL,          -- relative to the skill dir, e.g. scripts/report_pdf.py
    params_schema text        NOT NULL DEFAULT '{}',  -- JSON schema for inputs
    use_count     integer     NOT NULL DEFAULT 0,
    last_used_at  timestamp with time zone,
    created_at    timestamp with time zone NOT NULL DEFAULT now(),
    updated_at    timestamp with time zone NOT NULL DEFAULT now(),
    UNIQUE (skill_id, name)
);

CREATE INDEX IF NOT EXISTS idx_workflows_skill
    ON public.workflows(skill_id);

-- Descriptive comments so the memory-vault prompt and schema map surface
-- what each column is for (agents read these to understand the registry).
COMMENT ON TABLE public.workflows IS
    'Workflow registry: binds a skill to one or more named, runnable scripts. '
    'A skill (e.g. create-pdf) can have MULTIPLE workflows (report-pdf, '
    'invoice-pdf), each bound to a script. The agent lists a skill''s '
    'workflows, runs the right one in the background, and records which it '
    'used so it reaches for the proven path next time.';

COMMENT ON COLUMN public.workflows.id IS
    'Primary key.';
COMMENT ON COLUMN public.workflows.skill_id IS
    'FK to public.skills(id) — the parent skill this workflow belongs to.';
COMMENT ON COLUMN public.workflows.name IS
    'Workflow name, unique per skill (e.g. report-pdf).';
COMMENT ON COLUMN public.workflows.description IS
    'What the workflow does + when to use it. Injected into the system prompt '
    'workflow index (capped ~160 chars) so the agent knows it exists.';
COMMENT ON COLUMN public.workflows.script_path IS
    'Path to the script, relative to the skill dir (e.g. scripts/report_pdf.py). '
    'Resolved on disk first, then from skill_files content.';
COMMENT ON COLUMN public.workflows.params_schema IS
    'JSON schema describing the inputs the script expects (passed as JSON on '
    'sys.argv[1] when run).';
COMMENT ON COLUMN public.workflows.use_count IS
    'How many times this workflow has been run — drives "reach for the proven '
    'path first" ordering.';
COMMENT ON COLUMN public.workflows.last_used_at IS
    'Timestamp of the most recent run.';
COMMENT ON COLUMN public.workflows.created_at IS
    'When the workflow was registered.';
COMMENT ON COLUMN public.workflows.updated_at IS
    'When the workflow was last updated.';

-- Reversible:
--   DROP TABLE public.workflows;
