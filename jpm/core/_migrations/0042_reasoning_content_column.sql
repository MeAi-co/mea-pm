-- 0042_reasoning_content_column.sql
-- Add reasoning_content to public.messages.
-- The code INSERTs reasoning_content (run_agent.py, session.py, joshaico_state.py)
-- but the base schema only defined reasoning_details. Fresh nodes crashed with
-- UndefinedColumnError on every assistant-message write. The main DB had it
-- added ad-hoc; this migration makes it explicit so all nodes converge.
ALTER TABLE public.messages ADD COLUMN IF NOT EXISTS reasoning_content text;
