-- Migration 0025: Add tool_calls column to messages table
-- Commit fe77a6c ("Eliminate message_extras table — merge tool_calls into
-- messages") added `tool_calls text` to the messages table definition in the
-- BASE schema (_schema_pg.sql). But the base schema only runs once, on a fresh
-- DB (guarded by the _schema_migrations sentinel). Existing nodes that already
-- had the sentinel skipped the 481-statement base loop, so the column was never
-- added to live DBs — every append_message() then failed with:
--   column "tool_calls" of relation "messages" does not exist
--
-- This numbered migration is the durable fix: it runs exactly once per node
-- (tracked in _schema_migrations) and is idempotent via IF NOT EXISTS, so it
-- is safe whether the column was already added manually or not.

ALTER TABLE public.messages ADD COLUMN IF NOT EXISTS tool_calls text;
