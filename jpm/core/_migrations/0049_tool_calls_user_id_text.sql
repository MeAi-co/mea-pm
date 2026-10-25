-- Migration 0049: tool_calls.user_id integer -> text
--
-- Schema: public
--
-- Problem:
--   The base schema (_schema_pg.sql) declared `tool_calls.user_id` as `integer`
--   (a leftover from the old SQLite-era FK-to-users.id design). But agents pass
--   a PLATFORM user identifier here — a string like `'system:startup'` (boot-time
--   internal calls) or a Telegram/Discord/WhatsApp account id (live chat calls,
--   e.g. `1762309326`).
--
--   asyncpg resolves each `$N` placeholder's target column type and coerces the
--   bound value to it. For a `user_id integer` column it called int('system:startup'),
--   which raised `invalid input for query argument $1: 'system:startup' ('str' object
--   cannot be interpreted as an integer)`. log_tool_call() swallowed that into
--   disabled DEBUG logging, so from ~08-18 onward EVERY tool call silently failed
--   to be recorded.
--
-- Fix:
--   1. Re-type the column to `text` (lossless — no existing row carries a value
--      that would be mangled; prior rows are NULL or small ints, both representable
--      as text).
--   2. Align the base schema to match so a fresh bootstrap builds the same table.
--
-- Idempotent: the ALTER is guarded by a DO block that only fires while the column
-- is still type `integer`.
--
-- NOTE: a running gateway whose connection pool opened BEFORE this migration
--       holds stale prepared statements bound to the old `integer` type. A
--       gateway restart is REQUIRED after applying for the fix to go live.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'tool_calls'
          AND column_name = 'user_id'
          AND data_type = 'integer'
    ) THEN
        ALTER TABLE public.tool_calls
            ALTER COLUMN user_id TYPE text USING user_id::text;
    END IF;
END $$;

-- Reversible:
--   ALTER TABLE public.tool_calls
--       ALTER COLUMN user_id TYPE integer USING
--           CASE WHEN user_id ~ '^[0-9]+$' THEN user_id::integer ELSE NULL END;
