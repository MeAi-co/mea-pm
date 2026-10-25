-- Migration 0051: projects schema — int ids + datetime timestamps
--
-- Schema: public
--
-- Problem:
--   The projects/project_folders/discovered_repos tables used TEXT ids
--   (`p_<hex>` via secrets.token_hex) and INTEGER epoch timestamps. Per the
--   project brief: all ids except session_id must be INT (serial, auto-increment,
--   no random hashes, no manual +1), and all timestamps must be DATETIME
--   (not float, not dt+TZ).
--
--   All four tables were EMPTY at migration time (verified: projects=0,
--   project_folders=0, project_meta=0, discovered_repos=0), so this was a
--   clean drop-and-recreate — no data migration needed. (Tables have since
--   been populated by normal use; the migration itself is idempotent.)
--
-- Fix:
--   1. Drop project_folders (holds the FK to projects.id) then projects.
--   2. Recreate projects with `id serial PRIMARY KEY`, `created_at timestamp`,
--      and a new `updated_at timestamp`.
--   3. Recreate project_folders with `project_id int` FK and `added_at timestamp`.
--   4. Re-type discovered_repos.last_seen integer -> timestamp.
--   5. project_meta stays as-is (key/value KV, no timestamps).
--
-- Idempotent: DROP IF EXISTS + CREATE IF NOT EXISTS. The migration runner
-- treats "already exists" as benign and continues.

-- Drop child tables first (FK dependency), then parent — but ONLY when the
-- old TEXT-id schema is still present. On a DB where projects.id is already
-- integer (the migration's goal is already met), the DROP is unnecessary and
-- DANGEROUS: project_sessions/project_skills were created by later migrations
-- (0053/0054) that are already recorded as applied, so dropping them here
-- would delete them permanently — they would never be recreated.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='projects'
               AND column_name='id' AND data_type <> 'integer') THEN
    DROP TABLE IF EXISTS public.project_folders;
    DROP TABLE IF EXISTS public.project_sessions;
    DROP TABLE IF EXISTS public.project_skills;
    DROP TABLE IF EXISTS public.projects;
  END IF;
END $$;

-- Recreate projects with int serial id + datetime timestamps.
CREATE TABLE IF NOT EXISTS public.projects (
    id            serial PRIMARY KEY,
    slug          text NOT NULL UNIQUE,
    name          text NOT NULL,
    description   text,
    icon          text,
    color         text,
    board_slug    text,
    primary_path  text,
    created_at    timestamp NOT NULL DEFAULT now(),
    updated_at    timestamp NOT NULL DEFAULT now(),
    archived      integer NOT NULL DEFAULT 0
);

-- Recreate project_folders with int FK + datetime added_at.
CREATE TABLE IF NOT EXISTS public.project_folders (
    id          serial NOT NULL,
    project_id  int NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    path        text NOT NULL,
    label       text,
    is_primary  integer NOT NULL DEFAULT 0,
    added_at    timestamp NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, path)
);

CREATE INDEX IF NOT EXISTS idx_project_folders_path
    ON public.project_folders(path);

-- Re-type discovered_repos.last_seen integer -> timestamp.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'discovered_repos'
          AND column_name = 'last_seen'
          AND data_type = 'integer'
    ) THEN
        ALTER TABLE public.discovered_repos
            ALTER COLUMN last_seen TYPE timestamp USING to_timestamp(last_seen);
    END IF;
END $$;

-- Reversible:
--   DROP TABLE public.project_folders;
--   DROP TABLE public.projects;
--   (recreate with text id + integer created_at from the pre-0051 base schema)
