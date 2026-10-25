-- Migration 0017: Add gateway routing columns to sessions table
-- Replaces sessions.json with PG as the single source of truth.

-- ── Gateway routing columns ───────────────────────────────────────────

ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS chat_id text;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS session_key text;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS chat_name text;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS chat_type text DEFAULT 'dm';
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS thread_id text;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS user_name text;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS chat_topic text;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS user_id_alt text;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS chat_id_alt text;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS guild_id text;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS parent_chat_id text;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS message_id text;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS profile text;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS display_name text;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS total_tokens integer DEFAULT 0;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS last_prompt_tokens integer DEFAULT 0;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS updated_at real;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS origin_json jsonb;

-- ── Gateway state flags ───────────────────────────────────────────────

ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS suspended boolean DEFAULT false;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS resume_pending boolean DEFAULT false;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS resume_reason text;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS last_resume_marked_at real;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS expiry_finalized boolean DEFAULT false;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS is_fresh_reset boolean DEFAULT false;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS was_auto_reset boolean DEFAULT false;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS auto_reset_reason text;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS reset_had_activity boolean DEFAULT false;

-- ── Indexes ───────────────────────────────────────────────────────────

-- Unique on session_key for OPEN sessions only (allows historical closed rows
-- to share a key).
CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_active_key
    ON public.sessions (session_key)
    WHERE session_key IS NOT NULL AND (end_reason IS NULL OR end_reason = '');

-- Mirror delivery lookup: find active session for a platform+chat_id.
CREATE INDEX IF NOT EXISTS idx_sessions_mirror_lookup
    ON public.sessions (source, chat_id)
    WHERE session_key IS NOT NULL;

-- Channel directory: unique chat origins for discovery.
CREATE INDEX IF NOT EXISTS idx_sessions_channel_directory
    ON public.sessions (source, user_id, chat_name)
    WHERE session_key IS NOT NULL;

-- Pruning/sorting by last activity.
CREATE INDEX IF NOT EXISTS idx_sessions_updated_at
    ON public.sessions (updated_at DESC NULLS LAST);

-- Primary key for ON CONFLICT (id) UPSERT support.
-- Handles the case where a previous migration left sessions without a PK.
ALTER TABLE public.sessions ADD PRIMARY KEY (id);

-- ── updated_at trigger ────────────────────────────────────────────────

-- Create function if it doesn't exist (guarded by DO block to avoid
-- "no schema has been selected to create in" on re-runs)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_sessions_updated_at') THEN
        CREATE OR REPLACE FUNCTION public.update_sessions_updated_at()
        RETURNS TRIGGER AS $_$
        BEGIN
            NEW.updated_at := EXTRACT(EPOCH FROM NOW());
            RETURN NEW;
        END;
        $_$ LANGUAGE plpgsql;
    END IF;
END
$$;

DROP TRIGGER IF EXISTS trg_sessions_updated_at ON public.sessions;

CREATE TRIGGER trg_sessions_updated_at
    BEFORE UPDATE ON public.sessions
    FOR EACH ROW
    EXECUTE FUNCTION public.update_sessions_updated_at();
