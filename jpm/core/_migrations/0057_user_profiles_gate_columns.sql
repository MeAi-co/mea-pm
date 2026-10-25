-- 0057_user_profiles_gate_columns.sql
-- Add the per-user auth/gate columns to public.user_profiles that the
-- f2bd053 pull added to _schema_pg.sql but shipped without a numbered
-- migration. Without this, the live DB drifts from the base schema and
-- writes to these columns fail (SCHEMA DRIFT warning on startup).
--
-- Idempotent: ADD COLUMN IF NOT EXISTS is safe to re-run on any node.

ALTER TABLE IF EXISTS public.user_profiles
    ADD COLUMN IF NOT EXISTS bot_id text,
    ADD COLUMN IF NOT EXISTS gateway text,
    ADD COLUMN IF NOT EXISTS tier text DEFAULT 'shared'::text,
    ADD COLUMN IF NOT EXISTS status text DEFAULT 'active'::text,
    ADD COLUMN IF NOT EXISTS rate_limit integer DEFAULT 20,
    ADD COLUMN IF NOT EXISTS rate_window integer DEFAULT 60,
    ADD COLUMN IF NOT EXISTS min_interval real DEFAULT 1.0,
    ADD COLUMN IF NOT EXISTS daily_quota integer DEFAULT 500;

-- The gate indexes on the new columns (mirrors _schema_pg.sql).
-- user_profiles is an ADMIN-ONLY table: it does not exist on end-user bot
-- DBs. CREATE INDEX IF NOT EXISTS does NOT guard against a missing table
-- (it only guards the index), so it would hard-fail on bot DBs. Guard the
-- whole block with to_regclass() so it no-ops cleanly when the table is
-- absent.
DO $$
BEGIN
    IF to_regclass('public.user_profiles') IS NOT NULL THEN
        CREATE INDEX IF NOT EXISTS user_profiles_bot_id_key
            ON public.user_profiles (bot_id);
        CREATE INDEX IF NOT EXISTS idx_user_profiles_gateway
            ON public.user_profiles (gateway);
    END IF;
END $$;
