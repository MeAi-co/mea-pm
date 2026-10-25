-- 0074_drop_class_a_dead_tables.sql
-- Drop six vestigial Class-A tables from public: renamed/superseded predecessors
-- whose live replacements are already in use. All six have 0 code references in
-- live code (verified by grep for SQL verbs against each name) and 0 FK
-- references pointing at them.
--
--   public.active_focus        -> superseded by public.active
--   public.credentials         -> superseded by ext_api.credentials (browser orch)
--   public.staging             -> superseded by public.staging_inbox / staging_tasks
--   public.tasks_notify_subs   -> superseded by kanban.kanban_notify_subs
--   public.kanban_notify_subs  -> superseded by kanban.kanban_notify_subs
--
-- NOTE: public.credentials is NOT the live credential store. The live store is
-- ext_api.credentials (browser_orchestrator/server.py). public.credentials has
-- 0 code references; any orphaned rows should be exported before dropping.
--
-- Idempotent: DROP TABLE IF EXISTS. Safe to re-apply. No gateway restart needed
-- (the startup drift guard only checks base-schema COLUMNS, not tables).

DROP TABLE IF EXISTS public.active_focus;
DROP TABLE IF EXISTS public.credentials;
DROP TABLE IF EXISTS public.staging;
DROP TABLE IF EXISTS public.tasks_notify_subs;
DROP TABLE IF EXISTS public.kanban_notify_subs;
