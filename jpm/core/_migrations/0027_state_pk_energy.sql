-- Migration 0027: state.id primary key + energy numeric handling
--
-- Why: the v2 agent_state.py uses `ON CONFLICT (id) DO UPDATE` for the
-- fixed single state row. Two preconditions are missing on live nodes:
--
--   1. public.state.id has NO primary key (rebuilt without one by earlier
--      migrations), so ON CONFLICT (id) errors: "there is no unique or
--      exclusion constraint matching the ON CONFLICT specification".
--   2. energy is `text` (canonical), but asyncpg refuses to bind a float
--      into a text column: DataError "expected str, got float". The v2
--      writer passes energy as a float (0.5 etc.), so writes fail on PG.
--
-- Fix:
--   * Add a primary key on public.state.id (idempotent via DO block).
--   * Add a generated/text-safe path: keep energy as text (canonical,
--     _schema_pg.sql defines `energy text DEFAULT 0.5`), and the v2
--     writer will pass energy as a string. This migration only adds the PK
--     and normalizes any existing row so id=1 is the canonical single row.
--
-- Idempotent: safe on nodes that already have a PK on state.id.

DO $$ BEGIN
    -- state.id primary key. Guard via information_schema + pg_constraint:
    -- a table's PK constraint may be named anything (legacy installs may
    -- carry a differently-named PK), so check for contype='p' on the
    -- relation, not a name.
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.state'::regclass AND contype = 'p'
    ) THEN
        -- dedupe first: ON CONFLICT needs uniqueness; keep the latest row per id
        DELETE FROM public.state a
        USING public.state b
        WHERE a.id = b.id AND a.updated_at < b.updated_at
          AND a.ctid <> b.ctid;
        ALTER TABLE public.state ADD PRIMARY KEY (id);
    END IF;
END $$;

DO $$ BEGIN
    -- Normalize to the single canonical row (id = 1) if the table has rows
    -- with other ids — v2 upserts against id=1. Only when id=1 is absent.
    IF NOT EXISTS (SELECT 1 FROM public.state WHERE id = 1)
       AND EXISTS (SELECT 1 FROM public.state) THEN
        UPDATE public.state SET id = 1 WHERE id = (SELECT id FROM public.state ORDER BY updated_at DESC LIMIT 1);
    END IF;
END $$;
