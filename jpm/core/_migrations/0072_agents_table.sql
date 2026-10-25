-- 0072_agents_table.sql
-- Create the agent registry table `public.agents`.
--
-- History: `public.agents` has been defined in the base schema
-- (_schema_pg.sql, CREATE TABLE IF NOT EXISTS public.agents ...) since the
-- self-contained-schema commit (22ccbb4, Jul 2026), but NO numbered migration
-- ever created it. The base schema only runs once, on a FRESH DB (guarded by
-- the _schema_migrations sentinel); on every existing node only the numbered
-- migrations in _migrations/ run. So on any node whose DB predates that commit
-- the table was never created, and the startup drift guard in jpm/core/_pg.py
-- fires:
--   SCHEMA DRIFT — table agents is missing base-schema column(s)
--   ['active','agent_name','created_at','last_seen','port','role','host_ip']
--
-- The table is currently UNUSED by code (no INSERT/SELECT against public.agents
-- anywhere in the repo — verified by grep), so this is a latent-drift fix, not
-- a live breakage. It is created here to match the base schema exactly so the
-- drift guard goes quiet and any future writer finds the table present.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS + guarded PK add. Safe to re-apply.

CREATE TABLE IF NOT EXISTS public.agents (
    agent_name text NOT NULL,
    role text DEFAULT 'worker'::text NOT NULL,
    host_ip text,
    port integer DEFAULT 22,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_seen timestamp with time zone,
    CONSTRAINT agents_role_check CHECK ((role = ANY (ARRAY['orchestrator'::text, 'worker'::text, 'gateway'::text, 'end-user'::text])))
);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'agents_pkey') THEN
    ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_pkey PRIMARY KEY (agent_name);
  END IF;
END $$;

COMMENT ON TABLE public.agents IS
    'Agent registry: name, role, host_ip, port, active, last_seen.';
