-- 0044_intent_patterns.sql
-- Seed intent-routing patterns from real session mining (2026-08-13).
-- pattern_type='intent' distinguishes these from tool_sequence/approach/workflow.
-- Idempotent: INSERT ... ON CONFLICT (name) DO NOTHING.
--
-- These are the MESSY real-world phrasings users actually type (typos, slang,
-- curse words), NOT textbook examples. The intent router matches them via
-- pgvector cosine similarity so typo/slang variants still route.

INSERT INTO public.patterns (name, description, pattern_type, confidence, times_fired, archived)
VALUES
  -- recall_frustration (highest priority — 13 sessions, dominant pain point)
  ('intent_recall_you_forgot', 'recall_frustration', 'intent', 0.9, 0, 0),
  ('intent_recall_we_talked', 'recall_frustration', 'intent', 0.9, 0, 0),
  ('intent_recall_dont_remember', 'recall_frustration', 'intent', 0.9, 0, 0),
  ('intent_recall_catch_up', 'recall_frustration', 'intent', 0.9, 0, 0),
  ('intent_recall_what_were_doing', 'recall_frustration', 'intent', 0.9, 0, 0),
  ('intent_recall_told_you_before', 'recall_frustration', 'intent', 0.9, 0, 0),
  ('intent_recall_doa_session_saerch', 'recall_frustration', 'intent', 0.9, 0, 0),
  ('intent_recall_forget_who_you_are', 'recall_frustration', 'intent', 0.9, 0, 0),
  ('intent_recall_we_talked_yesterday', 'recall_frustration', 'intent', 0.9, 0, 0),
  ('intent_recall_dont_you_remember', 'recall_frustration', 'intent', 0.9, 0, 0),
  -- save_remember (positive intent — store durably)
  ('intent_save_this', 'save_remember', 'intent', 0.9, 0, 0),
  ('intent_remember_this', 'save_remember', 'intent', 0.9, 0, 0),
  ('intent_keep_in_mind', 'save_remember', 'intent', 0.9, 0, 0),
  ('intent_save_to_memory', 'save_remember', 'intent', 0.9, 0, 0),
  -- skill_usage (users reference skills INDIRECTLY)
  ('intent_skill_had_a_skill', 'skill_usage', 'intent', 0.9, 0, 0),
  ('intent_skill_use_that_skill', 'skill_usage', 'intent', 0.9, 0, 0),
  ('intent_skill_dont_know_to_use', 'skill_usage', 'intent', 0.9, 0, 0),
  ('intent_skill_why_not_use', 'skill_usage', 'intent', 0.9, 0, 0),
  -- start_fresh (NOT "start over" — too destructive, deliberately excluded)
  ('intent_fresh_new_session', 'start_fresh', 'intent', 0.9, 0, 0),
  ('intent_fresh_new_day', 'start_fresh', 'intent', 0.9, 0, 0),
  ('intent_fresh_new_sess', 'start_fresh', 'intent', 0.9, 0, 0),
  -- identity
  ('intent_identity_who_are_you', 'identity', 'intent', 0.9, 0, 0),
  ('intent_identity_whats_your_name', 'identity', 'intent', 0.9, 0, 0),
  ('intent_identity_intact', 'identity', 'intent', 0.9, 0, 0),
  -- correction (curse/ALL-CAPS = strong signal, higher threshold in router)
  ('intent_correction_wrong_path', 'correction', 'intent', 0.9, 0, 0),
  ('intent_correction_told_ya', 'correction', 'intent', 0.9, 0, 0),
  ('intent_correction_well_duh', 'correction', 'intent', 0.9, 0, 0),
  ('intent_correction_stupid_logic', 'correction', 'intent', 0.9, 0, 0),
  ('intent_correction_no_assumptions', 'correction', 'intent', 0.9, 0, 0),
  ('intent_correction_be_surgical', 'correction', 'intent', 0.9, 0, 0)
ON CONFLICT (name) DO NOTHING;
