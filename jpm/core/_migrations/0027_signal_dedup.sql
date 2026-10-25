-- 0027_signal_dedup.sql
-- Add a unique index on signals(trigger, action) so duplicate trigger-action
-- rules can't accumulate. Backs up the idempotent _create_signal() guard in
-- self_improvement.py. Idempotent: safe to run on nodes that already have the
-- index or that have duplicate rows (the WHERE clause skips existing dups).
CREATE UNIQUE INDEX IF NOT EXISTS uq_signals_trigger_action
    ON public.signals (trigger, action)
    WHERE (trigger IS NOT NULL AND action IS NOT NULL);
