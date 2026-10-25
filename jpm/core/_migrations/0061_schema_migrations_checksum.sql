-- 0061_schema_migrations_checksum.sql
-- Add the checksum column to public._schema_migrations that the base
-- schema (_schema_pg.sql) defines but shipped without a numbered
-- migration. Without this, the live DB drifts from the base schema and
-- the startup schema-drift guard logs a SCHEMA DRIFT warning on every
-- boot (and any future write to the column would fail).
--
-- Idempotent: ADD COLUMN IF NOT EXISTS is safe to re-run on any node.

ALTER TABLE IF EXISTS public._schema_migrations
    ADD COLUMN IF NOT EXISTS checksum text DEFAULT '';
