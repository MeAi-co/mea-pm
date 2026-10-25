-- 0028_state_valence_arousal.sql
-- Add valence/arousal columns to the state table so _set_state() can persist
-- the emotional-state extraction from self_improvement.py. Previously these
-- values were silently discarded (the table only had mood/energy/headspace).
-- Idempotent via IF NOT EXISTS — safe on nodes that already have the columns.
ALTER TABLE public.state ADD COLUMN IF NOT EXISTS valence double precision DEFAULT 0.0;
ALTER TABLE public.state ADD COLUMN IF NOT EXISTS arousal double precision DEFAULT 0.3;
