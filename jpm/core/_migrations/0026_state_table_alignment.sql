-- Migration 0026: Align state tables to canonical schema
--
-- Root cause: _schema_pg.sql uses CREATE TABLE IF NOT EXISTS, which never
-- ALTERs existing tables. Live DBs created before a schema change keep the
-- old column types forever. The _set_state() writer in agent_state.py was
-- written against the canonical (text) schema, so any node with a drifted
-- state table fails every state write:
--
--   Node A:       energy text  → real        → "$2: '0.7' (must be real number, not str)"
--   Node B:       skill_override text → integer → "$4: '' (str object cannot be interpreted as an integer)"
--
-- Fix: align public.state and public.agent_state to the
-- canonical types in _schema_pg.sql. Idempotent via information_schema
-- guards — safe to run on nodes that already match.

DO $$ BEGIN
    -- public.state — the table _set_state() writes to
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='state' AND column_name='skill_override'
                 AND data_type = 'integer') THEN
        ALTER TABLE public.state ALTER COLUMN skill_override TYPE text USING skill_override::text;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='state' AND column_name='updated_at'
                 AND data_type = 'real') THEN
        ALTER TABLE public.state ALTER COLUMN updated_at TYPE double precision USING updated_at::double precision;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='state' AND column_name='energy'
                 AND data_type IN ('real','double precision','numeric')) THEN
        ALTER TABLE public.state ALTER COLUMN energy TYPE text USING energy::text;
    END IF;
END $$;

DO $$ BEGIN
    -- public.agent_state — energy drifted to real on some nodes
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='agent_state' AND column_name='energy'
                 AND data_type IN ('real','double precision','numeric')) THEN
        ALTER TABLE public.agent_state ALTER COLUMN energy TYPE text USING energy::text;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name='agent_state' AND column_name='updated_at'
                 AND data_type = 'real') THEN
        ALTER TABLE public.agent_state ALTER COLUMN updated_at TYPE double precision USING updated_at::double precision;
    END IF;
END $$;
