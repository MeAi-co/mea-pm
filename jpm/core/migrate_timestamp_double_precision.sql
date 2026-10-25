-- Migration: timestamp columns from real → double precision
-- real (float32) loses precision for epoch timestamps above ~2^24 seconds (~194 days).
-- double precision (float64) is exact for all reasonable epoch timestamps.
--
-- Generated 2026-07-12. Run via: psql -f migrate_timestamp_double_precision.sql

-- active
ALTER TABLE public.active ALTER COLUMN updated_at TYPE double precision;

-- active_focus
ALTER TABLE public.active_focus ALTER COLUMN updated_at TYPE double precision;

-- agent_state
ALTER TABLE public.agent_state ALTER COLUMN updated_at TYPE double precision;

-- agent_talks
ALTER TABLE public.agent_talks ALTER COLUMN created_at TYPE double precision;

-- capabilities
ALTER TABLE public.capabilities ALTER COLUMN last_used TYPE double precision;

-- coaching
ALTER TABLE public.coaching ALTER COLUMN created_at TYPE double precision;

-- compression_locks
ALTER TABLE public.compression_locks ALTER COLUMN acquired_at TYPE double precision;
ALTER TABLE public.compression_locks ALTER COLUMN expires_at TYPE double precision;

-- credentials
ALTER TABLE public.credentials ALTER COLUMN expires_at TYPE double precision;

-- discovered_repos
ALTER TABLE public.discovered_repos ALTER COLUMN last_seen TYPE double precision;

-- emotional_tones
ALTER TABLE public.emotional_tones ALTER COLUMN valence TYPE double precision;
ALTER TABLE public.emotional_tones ALTER COLUMN arousal TYPE double precision;

-- entities
ALTER TABLE public.entities ALTER COLUMN created_at TYPE double precision;

-- explanations
ALTER TABLE public.explanations ALTER COLUMN confidence TYPE double precision;
ALTER TABLE public.explanations ALTER COLUMN created_at TYPE double precision;

-- fact_links
ALTER TABLE public.fact_links ALTER COLUMN weight TYPE double precision;

-- growth_log
ALTER TABLE public.growth_log ALTER COLUMN created_at TYPE double precision;

-- integrations
ALTER TABLE public.integrations ALTER COLUMN connected_at TYPE double precision;
ALTER TABLE public.integrations ALTER COLUMN last_sync_at TYPE double precision;

-- knowledge
ALTER TABLE public.knowledge ALTER COLUMN last_referenced TYPE double precision;
ALTER TABLE public.knowledge ALTER COLUMN weightage TYPE double precision;

-- llm_calls
ALTER TABLE public.llm_calls ALTER COLUMN "timestamp" TYPE double precision;
ALTER TABLE public.llm_calls ALTER COLUMN estimated_cost_usd TYPE double precision;

-- loops
ALTER TABLE public.loops ALTER COLUMN created_at TYPE double precision;
ALTER TABLE public.loops ALTER COLUMN resolved_at TYPE double precision;

-- messages
ALTER TABLE public.messages ALTER COLUMN "timestamp" TYPE double precision;

-- moods
ALTER TABLE public.moods ALTER COLUMN created_at TYPE double precision;

-- onboarding
ALTER TABLE public.onboarding ALTER COLUMN target_weight TYPE double precision;
ALTER TABLE public.onboarding ALTER COLUMN created_at TYPE double precision;
ALTER TABLE public.onboarding ALTER COLUMN answered_at TYPE double precision;

-- oracle_diagnostics
ALTER TABLE public.oracle_diagnostics ALTER COLUMN "timestamp" TYPE double precision;
ALTER TABLE public.oracle_diagnostics ALTER COLUMN validation_rate TYPE double precision;
ALTER TABLE public.oracle_diagnostics ALTER COLUMN violation_rate TYPE double precision;
ALTER TABLE public.oracle_diagnostics ALTER COLUMN verification_rate TYPE double precision;
ALTER TABLE public.oracle_diagnostics ALTER COLUMN mismatch_rate TYPE double precision;
ALTER TABLE public.oracle_diagnostics ALTER COLUMN steering_compliance_rate TYPE double precision;
ALTER TABLE public.oracle_diagnostics ALTER COLUMN steering_fail_rate TYPE double precision;
ALTER TABLE public.oracle_diagnostics ALTER COLUMN avg_validation_ms TYPE double precision;
ALTER TABLE public.oracle_diagnostics ALTER COLUMN avg_verification_ms TYPE double precision;
ALTER TABLE public.oracle_diagnostics ALTER COLUMN avg_steering_ms TYPE double precision;
ALTER TABLE public.oracle_diagnostics ALTER COLUMN pre_seed_accuracy TYPE double precision;

-- oracle_log
ALTER TABLE public.oracle_log ALTER COLUMN "timestamp" TYPE double precision;

-- pattern_triggers
ALTER TABLE public.pattern_triggers ALTER COLUMN weight TYPE double precision;

-- patterns
ALTER TABLE public.patterns ALTER COLUMN confidence TYPE double precision;
ALTER TABLE public.patterns ALTER COLUMN last_fired TYPE double precision;

-- patterns_history
ALTER TABLE public.patterns_history ALTER COLUMN last_referenced_at TYPE double precision;
ALTER TABLE public.patterns_history ALTER COLUMN created_at TYPE double precision;

-- plugin_usage
ALTER TABLE public.plugin_usage ALTER COLUMN first_used TYPE double precision;
ALTER TABLE public.plugin_usage ALTER COLUMN last_used TYPE double precision;

-- pulse
ALTER TABLE public.pulse ALTER COLUMN created_at TYPE double precision;
ALTER TABLE public.pulse ALTER COLUMN confidence TYPE double precision;

-- pulse_history
ALTER TABLE public.pulse_history ALTER COLUMN created_at TYPE double precision;

-- reflection_queue
ALTER TABLE public.reflection_queue ALTER COLUMN priority TYPE double precision;
ALTER TABLE public.reflection_queue ALTER COLUMN created_at TYPE double precision;
ALTER TABLE public.reflection_queue ALTER COLUMN processed_at TYPE double precision;

-- reflections
ALTER TABLE public.reflections ALTER COLUMN created_at TYPE double precision;

-- sessions
ALTER TABLE public.sessions ALTER COLUMN started_at TYPE double precision;
ALTER TABLE public.sessions ALTER COLUMN ended_at TYPE double precision;
ALTER TABLE public.sessions ALTER COLUMN estimated_cost_usd TYPE double precision;
ALTER TABLE public.sessions ALTER COLUMN actual_cost_usd TYPE double precision;

-- signals
ALTER TABLE public.signals ALTER COLUMN created_at TYPE double precision;

-- skills
ALTER TABLE public.skills ALTER COLUMN created_at TYPE double precision;
ALTER TABLE public.skills ALTER COLUMN updated_at TYPE double precision;

-- state
ALTER TABLE public.state ALTER COLUMN updated_at TYPE double precision;

-- task_events
ALTER TABLE public.task_events ALTER COLUMN created_at TYPE double precision;

-- tasks
ALTER TABLE public.tasks ALTER COLUMN created_at TYPE double precision;
ALTER TABLE public.tasks ALTER COLUMN started_at TYPE double precision;
ALTER TABLE public.tasks ALTER COLUMN completed_at TYPE double precision;
ALTER TABLE public.tasks ALTER COLUMN last_heartbeat_at TYPE double precision;
ALTER TABLE public.tasks ALTER COLUMN claim_expires TYPE double precision;

-- user_pref
ALTER TABLE public.user_pref ALTER COLUMN created_at TYPE double precision;
ALTER TABLE public.user_pref ALTER COLUMN updated_at TYPE double precision;
