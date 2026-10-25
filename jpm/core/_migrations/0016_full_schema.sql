-- Migration 0016: Full JPM schema (baseline)
-- Applied when schema_version < 16 or table doesn't exist.
-- All subsequent migrations are additive-only patches.

-- Guard: only run if schema_version doesn't exist or version < 16
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'schema_version') THEN
        CREATE TABLE public.schema_version (
            version INTEGER NOT NULL
        );
    END IF;
END
$$;

-- Insert version marker if not present
INSERT INTO public.schema_version (version) VALUES (16)
ON CONFLICT DO NOTHING;
