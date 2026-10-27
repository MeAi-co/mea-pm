SET statement_timeout = 0;

SET lock_timeout = 0;

SET idle_in_transaction_session_timeout = 0;

SET transaction_timeout = 0;

SET client_encoding = 'UTF8';

SET standard_conforming_strings = on;

SELECT pg_catalog.set_config('search_path', '', false);

SET check_function_bodies = false;

SET xmloption = content;

SET client_min_messages = warning;

SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

-- ── pgvector extension ───────────────────────────────────────────────
-- Required BEFORE any table that declares a `vector(768)` column (e.g.
-- `skills.embedding` below). Without this, a fresh DB fails to create the
-- skills table with `type "vector" does not exist`. Migration 0029 also
-- runs `CREATE EXTENSION IF NOT EXISTS vector`, but the base schema runs
-- first, so the extension must exist here too.
CREATE EXTENSION IF NOT EXISTS vector;

-- ── Schema migration tracking table ──────────────────────────────────
-- Created first so _pg.py can check for its existence to decide whether
-- the 481-statement base schema has already been applied.  Each row
-- records one successfully-applied migration file.
CREATE TABLE IF NOT EXISTS public._schema_migrations (
    name        text PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now(),
    checksum    text DEFAULT ''
);

CREATE TABLE IF NOT EXISTS public.active (
    id bigint NOT NULL,
    focus text NOT NULL,
    project text DEFAULT ''::text,
    status text DEFAULT ''::text,
    updated_at double precision DEFAULT EXTRACT(epoch FROM now())
);

CREATE SEQUENCE IF NOT EXISTS public.active_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.active_id_seq OWNED BY public.active.id;

CREATE TABLE IF NOT EXISTS public.agent_auth (
    agent_name text NOT NULL,
    token_hash text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    revoked boolean DEFAULT false NOT NULL
);

CREATE TABLE IF NOT EXISTS public.agent_health (
    agent_name text NOT NULL,
    last_ping timestamp with time zone DEFAULT now() NOT NULL,
    status text DEFAULT 'online'::text NOT NULL,
    version text,
    uptime_seconds integer DEFAULT 0,
    CONSTRAINT agent_health_status_check CHECK ((status = ANY (ARRAY['online'::text, 'degraded'::text, 'offline'::text])))
);

CREATE TABLE IF NOT EXISTS public.agent_queue (
    id bigint NOT NULL,
    from_agent text NOT NULL,
    to_agent text NOT NULL,
    message_type text DEFAULT 'message'::text NOT NULL,
    content jsonb DEFAULT '{}'::jsonb NOT NULL,
    priority text DEFAULT 'normal'::text NOT NULL,
    project text,
    status text DEFAULT 'pending'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    read_at timestamp with time zone,
    CONSTRAINT agent_queue_message_type_check CHECK ((message_type = ANY (ARRAY['message'::text, 'patch_review'::text, 'notification'::text, 'alert'::text, 'task_assignment'::text, 'role_update'::text, 'escalation'::text]))),
    CONSTRAINT agent_queue_priority_check CHECK ((priority = ANY (ARRAY['low'::text, 'normal'::text, 'high'::text, 'urgent'::text]))),
    CONSTRAINT agent_queue_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'read'::text, 'acknowledged'::text, 'archived'::text])))
);

CREATE SEQUENCE IF NOT EXISTS public.agent_queue_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.agent_queue_id_seq OWNED BY public.agent_queue.id;

CREATE TABLE IF NOT EXISTS public.agent_state (
    id bigint NOT NULL,
    mood text DEFAULT 'neutral'::text,
    energy text DEFAULT 'okay'::text,
    headspace text DEFAULT ''::text,
    skill_override integer DEFAULT 0,
    skill_directive text DEFAULT ''::text,
    updated_at double precision DEFAULT 0
);

CREATE SEQUENCE IF NOT EXISTS public.agent_state_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.agent_state_id_seq OWNED BY public.agent_state.id;

CREATE TABLE IF NOT EXISTS public.agent_talks (
    id bigint NOT NULL,
    message text NOT NULL,
    session_id text DEFAULT ''::text,
    session_name text DEFAULT ''::text,
    link_entries text DEFAULT ''::text,
    created_at double precision DEFAULT EXTRACT(epoch FROM now()),
    heartbeat_processed integer DEFAULT 0,
    source_id integer,
    message_type text DEFAULT 'conversation'::text,
    tool_count integer DEFAULT 0
);

CREATE SEQUENCE IF NOT EXISTS public.agent_talks_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.agent_talks_id_seq OWNED BY public.agent_talks.id;

CREATE TABLE IF NOT EXISTS public.capabilities (
    id bigint NOT NULL,
    tool_name text NOT NULL,
    proficiency text DEFAULT 'medium'::text,
    last_used double precision DEFAULT EXTRACT(epoch FROM now()),
    use_count integer DEFAULT 0,
    CONSTRAINT capabilities_proficiency_check CHECK ((proficiency = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text])))
);

CREATE SEQUENCE IF NOT EXISTS public.capabilities_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.capabilities_id_seq OWNED BY public.capabilities.id;

CREATE TABLE IF NOT EXISTS public.coaching (
    id bigint NOT NULL,
    session_id text NOT NULL,
    turn integer DEFAULT 0 NOT NULL,
    line text NOT NULL,
    created_at double precision DEFAULT EXTRACT(epoch FROM now()),
    last_msg_id integer DEFAULT 0,
    oracle_context text DEFAULT ''::text
);

CREATE SEQUENCE IF NOT EXISTS public.coaching_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.coaching_id_seq OWNED BY public.coaching.id;

CREATE TABLE IF NOT EXISTS public.compression_locks (
    session_id text NOT NULL,
    holder text NOT NULL,
    acquired_at double precision NOT NULL,
    expires_at double precision NOT NULL
);

CREATE TABLE IF NOT EXISTS public.discovered_repos (
    id serial NOT NULL,
    root text NOT NULL,
    label text,
    last_seen timestamp NOT NULL,
    PRIMARY KEY (root)
);

CREATE TABLE IF NOT EXISTS public.emotional_tones (
    id bigint NOT NULL,
    name text NOT NULL,
    valence real DEFAULT 0.0,
    arousal real DEFAULT 0.0
);

CREATE SEQUENCE IF NOT EXISTS public.emotional_tones_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.emotional_tones_id_seq OWNED BY public.emotional_tones.id;

CREATE TABLE IF NOT EXISTS public.entities (
    entity_id bigint NOT NULL,
    name text NOT NULL,
    entity_type text DEFAULT 'unknown'::text,
    aliases text DEFAULT ''::text,
    created_at double precision DEFAULT EXTRACT(epoch FROM now())
);

CREATE SEQUENCE IF NOT EXISTS public.entities_entity_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.entities_entity_id_seq OWNED BY public.entities.entity_id;

CREATE TABLE IF NOT EXISTS public.fact_entities (
    fact_id bigint NOT NULL,
    entity_id bigint NOT NULL
);

CREATE TABLE IF NOT EXISTS public.group_messages (
    id integer NOT NULL,
    session_id text NOT NULL,
    message_id text,
    chat_id text NOT NULL,
    thread_id text,
    from_agent text,
    from_user text,
    from_name text,
    text text NOT NULL,
    direction text DEFAULT 'inbound'::text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb,
    "timestamp" timestamp with time zone DEFAULT now()
);

CREATE SEQUENCE IF NOT EXISTS public.group_messages_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.group_messages_id_seq OWNED BY public.group_messages.id;

CREATE TABLE IF NOT EXISTS public.growth_log (
    id bigint NOT NULL,
    content text NOT NULL,
    category text DEFAULT ''::text,
    created_at double precision DEFAULT EXTRACT(epoch FROM now())
);

CREATE SEQUENCE IF NOT EXISTS public.growth_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.growth_log_id_seq OWNED BY public.growth_log.id;

CREATE TABLE IF NOT EXISTS public.integrations (
    id bigint NOT NULL,
    platform text NOT NULL,
    connected integer DEFAULT 0,
    connected_at double precision,
    last_sync_at double precision,
    scopes text DEFAULT '[]'::text
);

CREATE SEQUENCE IF NOT EXISTS public.integrations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.integrations_id_seq OWNED BY public.integrations.id;

CREATE TABLE IF NOT EXISTS public.knowledge (
    id bigint NOT NULL,
    entity_type text DEFAULT 'general'::text NOT NULL,
    name text NOT NULL,
    description text DEFAULT ''::text,
    retrieval_count integer DEFAULT 0,
    helpful_count integer DEFAULT 0,
    stale_count integer DEFAULT 0,
    last_referenced double precision DEFAULT EXTRACT(epoch FROM now()),
    archived integer DEFAULT 0,
    weightage real DEFAULT 0.5,
    fingerprint text DEFAULT ''::text,
    next_id integer,
    chain text DEFAULT ''::text,
    content text DEFAULT ''::text,
    files text DEFAULT '{}'::text,
    profile text DEFAULT 'default'::text NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, ((((COALESCE(name, ''::text) || ' '::text) || COALESCE(description, ''::text)) || ' '::text) || COALESCE(fingerprint, ''::text)))) STORED
);

CREATE SEQUENCE IF NOT EXISTS public.knowledge_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.knowledge_id_seq OWNED BY public.knowledge.id;

CREATE TABLE IF NOT EXISTS public.llm_calls (
    id bigint NOT NULL,
    user_id integer,
    session_id text,
    "timestamp" double precision DEFAULT EXTRACT(epoch FROM now()) NOT NULL,
    model text NOT NULL,
    provider text,
    input_tokens integer DEFAULT 0,
    output_tokens integer DEFAULT 0,
    cache_read_tokens integer DEFAULT 0,
    cache_write_tokens integer DEFAULT 0,
    total_tokens integer DEFAULT 0,
    estimated_cost_usd real,
    latency_ms integer,
    success integer DEFAULT 1,
    error_message text
);

CREATE SEQUENCE IF NOT EXISTS public.llm_calls_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.llm_calls_id_seq OWNED BY public.llm_calls.id;

CREATE TABLE IF NOT EXISTS public.loops (
    id bigint NOT NULL,
    content text NOT NULL,
    project text DEFAULT ''::text,
    priority text DEFAULT 'medium'::text,
    resolved integer DEFAULT 0,
    created_at double precision DEFAULT EXTRACT(epoch FROM now()),
    resolved_at double precision,
    CONSTRAINT loops_priority_check CHECK ((priority = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text, 'critical'::text])))
);

CREATE SEQUENCE IF NOT EXISTS public.loops_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.loops_id_seq OWNED BY public.loops.id;

CREATE TABLE IF NOT EXISTS public.messages (
    id bigint NOT NULL,
    session_id text NOT NULL,
    role text NOT NULL,
    content text,
    tool_call_id text,
    tool_name text,
    tool_calls text,
    "timestamp" double precision NOT NULL,
    token_count integer,
    finish_reason text,
    reasoning_details text,
    reasoning_content text,
    codex_reasoning_items text,
    codex_message_items text,
    platform_message_id text,
    observed integer DEFAULT 0,
    active integer DEFAULT 1 NOT NULL,
    compacted integer DEFAULT 0 NOT NULL,
    flow_summarized_at timestamptz,
    agent_compacted integer DEFAULT 0 NOT NULL,
    message_id integer,
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, (COALESCE(content, ''::text) || ' '::text) || COALESCE(tool_name, ''::text))) STORED
);

-- One message, one row. Same session + role + content = same logical message.
-- Uses md5(content) to keep the index compact (content can be very long).
-- Idempotent message inserts: ON CONFLICT (session_id, message_id) DO NOTHING
-- ensures warm-start retries and compaction replays never create duplicates.
-- Replaces the old content-hash approach which broke on empty streaming rows.
-- Drop the old content-hash index if it still exists (migration 03865a8).
DROP INDEX IF EXISTS public.messages_session_role_content_idx;
CREATE UNIQUE INDEX IF NOT EXISTS messages_session_message_id_idx
    ON public.messages (session_id, message_id);

-- Content-hash dedup: same session + same content = same logical message,
-- even when the replay path mints a FRESH message_id/msg_key each time
-- (warm-start re-injection, compaction replay). This index is the net that
-- catches those re-writes so dupes never land. The write path uses targetless
-- ON CONFLICT DO NOTHING so a collision on ANY unique index (content_hash,
-- msg_key, or message_id) is swallowed gracefully — never a unique_violation.
-- Partial on active=1 (archived rows never collide on re-insert) and
-- content_hash IS NOT NULL (empty/NULL content excluded — NULLs are distinct
-- in unique indexes anyway, and streaming placeholders must never collide).
CREATE UNIQUE INDEX IF NOT EXISTS messages_session_content_idx
    ON public.messages (session_id, content_hash)
    WHERE active = 1 AND content_hash IS NOT NULL;

CREATE SEQUENCE IF NOT EXISTS public.messages_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.messages_id_seq OWNED BY public.messages.id;

CREATE TABLE IF NOT EXISTS public.state (
    id bigint NOT NULL,
    mood text DEFAULT 'neutral'::text,
    energy text DEFAULT 0.5,
    headspace text DEFAULT ''::text,
    skill_override text DEFAULT ''::text,
    updated_at double precision DEFAULT EXTRACT(epoch FROM now())
);

CREATE SEQUENCE IF NOT EXISTS public.state_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.state_id_seq OWNED BY public.state.id;

CREATE TABLE IF NOT EXISTS public.moods (
    id bigint NOT NULL,
    user_id text,
    mood text NOT NULL,
    context text,
    source_id integer,
    created_at double precision DEFAULT EXTRACT(epoch FROM now())
);

CREATE SEQUENCE IF NOT EXISTS public.moods_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.moods_id_seq OWNED BY public.moods.id;

CREATE TABLE IF NOT EXISTS public.onboarding (
    id bigint NOT NULL,
    question_key text NOT NULL,
    question text NOT NULL,
    hint text DEFAULT ''::text NOT NULL,
    phase text DEFAULT 'who'::text NOT NULL,
    target_type text DEFAULT 'user_pref'::text NOT NULL,
    target_weight real DEFAULT 0.9 NOT NULL,
    asked integer DEFAULT 0 NOT NULL,
    answered integer DEFAULT 0 NOT NULL,
    answer text,
    created_at double precision DEFAULT EXTRACT(epoch FROM now()) NOT NULL,
    answered_at real
);

CREATE SEQUENCE IF NOT EXISTS public.onboarding_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.onboarding_id_seq OWNED BY public.onboarding.id;

CREATE TABLE IF NOT EXISTS public.oracle_diagnostics (
    id bigint NOT NULL,
    session_id text NOT NULL,
    window_end_turn integer NOT NULL,
    "timestamp" double precision DEFAULT EXTRACT(epoch FROM now()),
    validation_rate real DEFAULT 0.0,
    violation_rate real DEFAULT 0.0,
    verification_rate real DEFAULT 0.0,
    mismatch_rate real DEFAULT 0.0,
    steering_compliance_rate real DEFAULT 0.0,
    steering_fail_rate real DEFAULT 0.0,
    loop_count integer DEFAULT 0,
    violations_count integer DEFAULT 0,
    mismatches_count integer DEFAULT 0,
    avg_validation_ms real DEFAULT 0.0,
    avg_verification_ms real DEFAULT 0.0,
    avg_steering_ms real DEFAULT 0.0,
    pre_seed_count integer DEFAULT 0,
    pre_seed_accuracy real DEFAULT 0.0
);

CREATE SEQUENCE IF NOT EXISTS public.oracle_diagnostics_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.oracle_diagnostics_id_seq OWNED BY public.oracle_diagnostics.id;

CREATE TABLE IF NOT EXISTS public.oracle_log (
    id bigint NOT NULL,
    session_id text NOT NULL,
    turn integer NOT NULL,
    "timestamp" double precision DEFAULT EXTRACT(epoch FROM now()),
    tool_name text NOT NULL,
    tool_params text DEFAULT '{}'::text,
    llm_rationale text DEFAULT ''::text,
    validation_status text,
    validation_reason text DEFAULT ''::text,
    dna_matched text DEFAULT ''::text,
    expected_next_action text DEFAULT ''::text,
    exit_code integer,
    stdout_hash text DEFAULT ''::text,
    stderr_hash text DEFAULT ''::text,
    duration_ms integer DEFAULT 0,
    verification_status text,
    verification_detail text DEFAULT ''::text,
    world_state_snapshot text DEFAULT '{}'::text,
    pre_seed_source text DEFAULT ''::text,
    pre_seed_similarity integer DEFAULT 0,
    task_completed integer,
    tool_call_entropy integer DEFAULT 0,
    loop_detected integer DEFAULT 0,
    trail text DEFAULT '{}'::text,
    oracle_signal text DEFAULT ''::text,
    constraint_valid integer DEFAULT 1,
    CONSTRAINT oracle_log_validation_status_check CHECK ((validation_status = ANY (ARRAY['VALID'::text, 'VIOLATION'::text, 'ADVISORY'::text, 'STEERED'::text, ''::text]))),
    CONSTRAINT oracle_log_verification_status_check CHECK ((verification_status = ANY (ARRAY['VERIFIED'::text, 'MISMATCH'::text, 'UNVERIFIED'::text, 'SKIPPED'::text, ''::text])))
);

CREATE SEQUENCE IF NOT EXISTS public.oracle_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.oracle_log_id_seq OWNED BY public.oracle_log.id;

CREATE TABLE IF NOT EXISTS public.patterns (
    id bigint NOT NULL,
    name text NOT NULL,
    description text DEFAULT ''::text,
    pattern_type text DEFAULT 'pattern'::text,
    confidence real DEFAULT 0.5,
    times_fired integer DEFAULT 0,
    last_fired real,
    archived integer DEFAULT 0
);

CREATE SEQUENCE IF NOT EXISTS public.patterns_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.patterns_id_seq OWNED BY public.patterns.id;

CREATE TABLE IF NOT EXISTS public.pipeline_control (
    id integer DEFAULT 1 NOT NULL,
    paused boolean DEFAULT false NOT NULL,
    paused_by text,
    reason text,
    paused_at timestamp with time zone,
    resumed_at timestamp with time zone,
    CONSTRAINT pipeline_control_id_check CHECK ((id = 1))
);

CREATE TABLE IF NOT EXISTS public.plugin_usage (
    id bigint NOT NULL,
    telegram_id bigint NOT NULL,
    plugin_name text NOT NULL,
    first_used real,
    last_used real,
    use_count integer DEFAULT 0,
    enabled integer DEFAULT 1
);

CREATE SEQUENCE IF NOT EXISTS public.plugin_usage_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.plugin_usage_id_seq OWNED BY public.plugin_usage.id;

CREATE TABLE IF NOT EXISTS public.project_folders (
    id serial NOT NULL,
    project_id int NOT NULL,
    path text NOT NULL,
    label text,
    is_primary integer DEFAULT 0 NOT NULL,
    added_at timestamp DEFAULT now() NOT NULL,
    PRIMARY KEY (project_id, path)
);

CREATE TABLE IF NOT EXISTS public.project_meta (
    id serial NOT NULL,
    key text NOT NULL,
    value text,
    PRIMARY KEY (key)
);

CREATE TABLE IF NOT EXISTS public.projects (
    id serial NOT NULL,
    slug text NOT NULL,
    name text NOT NULL,
    description text,
    icon text,
    color text,
    board_slug text,
    primary_path text,
    created_at timestamp DEFAULT now() NOT NULL,
    updated_at timestamp DEFAULT now() NOT NULL,
    archived integer DEFAULT 0 NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT projects_slug_key UNIQUE (slug)
);

CREATE TABLE IF NOT EXISTS public.pulse (
    id bigint NOT NULL,
    status text DEFAULT 'nominal'::text,
    summary text DEFAULT ''::text,
    session_id text DEFAULT ''::text,
    created_at double precision DEFAULT EXTRACT(epoch FROM now()),
    confidence real DEFAULT 0.95,
    source_message_id integer,
    CONSTRAINT pulse_status_check CHECK ((status = ANY (ARRAY['nominal'::text, 'blocked'::text, 'degraded'::text, 'idle'::text])))
);

CREATE TABLE IF NOT EXISTS public.pulse_history (
    id bigint NOT NULL,
    mood text DEFAULT 'neutral'::text,
    energy text DEFAULT 'okay'::text,
    health text DEFAULT ''::text,
    headspace text DEFAULT ''::text,
    session_id text DEFAULT ''::text,
    created_at double precision DEFAULT EXTRACT(epoch FROM now())
);

CREATE SEQUENCE IF NOT EXISTS public.pulse_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.pulse_history_id_seq OWNED BY public.pulse_history.id;

CREATE SEQUENCE IF NOT EXISTS public.pulse_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.pulse_id_seq OWNED BY public.pulse.id;

CREATE TABLE IF NOT EXISTS public.reflections (
    id bigint NOT NULL,
    session_id text,
    trigger text,
    insight text NOT NULL,
    impact integer DEFAULT 5,
    created_at double precision DEFAULT EXTRACT(epoch FROM now())
);

CREATE SEQUENCE IF NOT EXISTS public.reflections_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.reflections_id_seq OWNED BY public.reflections.id;

CREATE TABLE IF NOT EXISTS public.schema_version (
    version integer NOT NULL
);

CREATE TABLE IF NOT EXISTS public.sessions (
    id text NOT NULL,
    source text NOT NULL,
    user_id text,
    model text,
    model_config text,
    system_prompt text,
    parent_session_id text,
    started_at real NOT NULL,
    ended_at real,
    end_reason text,
    message_count integer DEFAULT 0,
    tool_call_count integer DEFAULT 0,
    input_tokens integer DEFAULT 0,
    output_tokens integer DEFAULT 0,
    cache_read_tokens integer DEFAULT 0,
    cache_write_tokens integer DEFAULT 0,
    reasoning_tokens integer DEFAULT 0,
    cwd text,
    billing_provider text,
    billing_base_url text,
    billing_mode text,
    estimated_cost_usd real,
    actual_cost_usd real,
    cost_status text,
    cost_source text,
    pricing_version text,
    title text,
    api_call_count integer DEFAULT 0,
    handoff_state text,
    handoff_platform text,
    handoff_error text,
    rewind_count integer DEFAULT 0 NOT NULL,
    archived integer DEFAULT 0 NOT NULL,
    git_branch text,
    git_repo_root text,
    session_key text,
    display_name text,
    chat_type text DEFAULT 'dm',
    chat_id text,
    thread_id text,
    origin_json jsonb,
    last_prompt_tokens integer DEFAULT 0,
    expiry_finalized boolean DEFAULT false,
    suspended boolean DEFAULT false,
    resume_pending boolean DEFAULT false,
    resume_reason text,
    last_resume_marked_at real,
    is_fresh_reset boolean DEFAULT false,
    was_auto_reset boolean DEFAULT false,
    auto_reset_reason text,
    reset_had_activity boolean DEFAULT false,
    last_processed_msg_id bigint DEFAULT 0
);

-- ── Gateway routing columns (added by 0017 migration) ──────────────────
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS session_key text;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS chat_id text;
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
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS suspended boolean DEFAULT false;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS resume_pending boolean DEFAULT false;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS resume_reason text;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS last_resume_marked_at real;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS expiry_finalized boolean DEFAULT false;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS is_fresh_reset boolean DEFAULT false;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS was_auto_reset boolean DEFAULT false;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS auto_reset_reason text;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS reset_had_activity boolean DEFAULT false;

-- ── Gateway indexes ────────────────────────────────────────────────────
CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_active_key
    ON public.sessions (session_key)
    WHERE session_key IS NOT NULL AND (end_reason IS NULL OR end_reason = '');
CREATE INDEX IF NOT EXISTS idx_sessions_mirror_lookup
    ON public.sessions (source, chat_id)
    WHERE session_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sessions_channel_directory
    ON public.sessions (source, user_id, chat_name)
    WHERE session_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sessions_updated_at
    ON public.sessions (updated_at DESC NULLS LAST);

-- ── Gateway trigger ─────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.update_sessions_updated_at()
RETURNS TRIGGER AS $_$
BEGIN
    NEW.updated_at := EXTRACT(EPOCH FROM NOW());
    RETURN NEW;
END;
$_$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sessions_updated_at ON public.sessions;

CREATE TRIGGER trg_sessions_updated_at
    BEFORE UPDATE ON public.sessions
    FOR EACH ROW
    EXECUTE FUNCTION public.update_sessions_updated_at();

CREATE TABLE IF NOT EXISTS public.signals (
    id bigint NOT NULL,
    trigger text NOT NULL,
    action text NOT NULL,
    params text DEFAULT '{}'::text,
    description text DEFAULT ''::text,
    enabled integer DEFAULT 1,
    created_at double precision DEFAULT EXTRACT(epoch FROM now())
);

CREATE SEQUENCE IF NOT EXISTS public.signals_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.signals_id_seq OWNED BY public.signals.id;

CREATE TABLE IF NOT EXISTS public.skill_files (
    id bigint NOT NULL,
    skill_id integer NOT NULL,
    file_path text NOT NULL,
    content text NOT NULL,
    next_file_id integer
);

CREATE SEQUENCE IF NOT EXISTS public.skill_files_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.skill_files_id_seq OWNED BY public.skill_files.id;

CREATE TABLE IF NOT EXISTS public.skills (
    id bigint NOT NULL,
    name text NOT NULL,
    category text DEFAULT ''::text,
    description text DEFAULT ''::text,
    version text DEFAULT ''::text,
    author text DEFAULT ''::text,
    tags text DEFAULT ''::text,
    role_tags text DEFAULT ''::text,
    content text NOT NULL,
    first_file_id integer,
    source text DEFAULT 'local'::text,
    trust_level text DEFAULT 'builtin'::text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    embedding            public.vector(768),
    embedding_model      text,
    embedding_updated_at timestamptz,
    created_by           text,
    use_count            integer NOT NULL DEFAULT 0,
    view_count           integer NOT NULL DEFAULT 0,
    patch_count          integer NOT NULL DEFAULT 0,
    last_used_at         timestamptz,
    last_viewed_at       timestamptz,
    last_patched_at      timestamptz,
    state                text NOT NULL DEFAULT 'active',
    pinned               boolean NOT NULL DEFAULT false,
    archived_at          timestamptz
);

CREATE SEQUENCE IF NOT EXISTS public.skills_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.skills_id_seq OWNED BY public.skills.id;

CREATE TABLE IF NOT EXISTS public.small_talk (
    id bigint NOT NULL,
    topic text NOT NULL,
    date text DEFAULT ''::text,
    vibe text DEFAULT 'neutral'::text,
    created_at double precision DEFAULT EXTRACT(epoch FROM now())
);

CREATE SEQUENCE IF NOT EXISTS public.small_talk_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.small_talk_id_seq OWNED BY public.small_talk.id;

CREATE TABLE IF NOT EXISTS public.staging_inbox (
    id bigint NOT NULL,
    from_agent text NOT NULL,
    message_type text DEFAULT 'message'::text NOT NULL,
    content jsonb DEFAULT '{}'::jsonb NOT NULL,
    priority text DEFAULT 'normal'::text NOT NULL,
    project text,
    acknowledged integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    read_at timestamp with time zone,
    CONSTRAINT staging_inbox_message_type_check CHECK ((message_type = ANY (ARRAY['message'::text, 'patch_review'::text, 'notification'::text, 'alert'::text, 'task_assignment'::text, 'role_update'::text, 'escalation'::text]))),
    CONSTRAINT staging_inbox_priority_check CHECK ((priority = ANY (ARRAY['low'::text, 'normal'::text, 'high'::text, 'urgent'::text])))
);

CREATE SEQUENCE IF NOT EXISTS public.staging_inbox_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.staging_inbox_id_seq OWNED BY public.staging_inbox.id;

CREATE TABLE IF NOT EXISTS public.staging_tasks (
    id text NOT NULL,
    bot_id text NOT NULL,
    board_id text DEFAULT 'default'::text NOT NULL,
    title text NOT NULL,
    body text,
    assignee text,
    status text NOT NULL,
    priority integer DEFAULT 0,
    created_by text,
    created_at integer NOT NULL,
    started_at integer,
    completed_at integer,
    workspace_kind text DEFAULT 'scratch'::text NOT NULL,
    workspace_path text,
    branch_name text,
    project_id text,
    claim_lock text,
    claim_expires integer,
    tenant text,
    result text,
    idempotency_key text,
    consecutive_failures integer DEFAULT 0 NOT NULL,
    worker_pid integer,
    last_failure_error text,
    max_runtime_seconds integer,
    last_heartbeat_at integer,
    current_run_id integer,
    workflow_template_id text,
    current_step_key text,
    skills text,
    model_override text,
    max_retries integer,
    goal_mode integer DEFAULT 0 NOT NULL,
    goal_max_turns integer,
    session_id text,
    block_kind text,
    block_recurrences integer DEFAULT 0 NOT NULL
);

CREATE TABLE IF NOT EXISTS public.state_meta (
    key text NOT NULL,
    value text
);

CREATE TABLE IF NOT EXISTS public.tags (
    id bigint NOT NULL,
    name text NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS public.tags_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.tags_id_seq OWNED BY public.tags.id;

CREATE TABLE IF NOT EXISTS public.task_attachments (
    id bigint NOT NULL,
    task_id text NOT NULL,
    filename text NOT NULL,
    stored_path text NOT NULL,
    content_type text,
    size integer DEFAULT 0 NOT NULL,
    uploaded_by text,
    created_at integer NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS public.task_attachments_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.task_attachments_id_seq OWNED BY public.task_attachments.id;

CREATE TABLE IF NOT EXISTS public.task_comments (
    id bigint NOT NULL,
    task_id text NOT NULL,
    author text NOT NULL,
    body text NOT NULL,
    created_at integer NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS public.task_comments_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.task_comments_id_seq OWNED BY public.task_comments.id;

CREATE TABLE IF NOT EXISTS public.task_context (
    id bigint NOT NULL,
    project_name text NOT NULL,
    milestone text DEFAULT ''::text,
    status text DEFAULT ''::text,
    updated_at double precision DEFAULT EXTRACT(epoch FROM now())
);

CREATE SEQUENCE IF NOT EXISTS public.task_context_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.task_context_id_seq OWNED BY public.task_context.id;

CREATE TABLE IF NOT EXISTS public.task_events (
    id bigint NOT NULL,
    task_id text NOT NULL,
    run_id integer,
    kind text NOT NULL,
    payload text,
    created_at integer NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS public.task_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.task_events_id_seq OWNED BY public.task_events.id;

CREATE TABLE IF NOT EXISTS public.task_links (
    parent_id text NOT NULL,
    child_id text NOT NULL
);

CREATE TABLE IF NOT EXISTS public.task_runs (
    id bigint NOT NULL,
    task_id text NOT NULL,
    profile text,
    step_key text,
    status text NOT NULL,
    claim_lock text,
    claim_expires integer,
    worker_pid integer,
    max_runtime_seconds integer,
    last_heartbeat_at integer,
    started_at integer NOT NULL,
    ended_at integer,
    outcome text,
    summary text,
    metadata text,
    error text
);

CREATE SEQUENCE IF NOT EXISTS public.task_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.task_runs_id_seq OWNED BY public.task_runs.id;

CREATE TABLE IF NOT EXISTS public.tasks (
    id text NOT NULL,
    board_id text DEFAULT 'default'::text NOT NULL,
    title text NOT NULL,
    body text,
    assignee text,
    status text NOT NULL,
    priority integer DEFAULT 0,
    created_by text,
    created_at integer NOT NULL,
    started_at integer,
    completed_at integer,
    workspace_kind text DEFAULT 'scratch'::text NOT NULL,
    workspace_path text,
    branch_name text,
    project_id text,
    claim_lock text,
    claim_expires integer,
    tenant text,
    result text,
    idempotency_key text,
    consecutive_failures integer DEFAULT 0 NOT NULL,
    worker_pid integer,
    last_failure_error text,
    max_runtime_seconds integer,
    last_heartbeat_at integer,
    current_run_id integer,
    workflow_template_id text,
    current_step_key text,
    skills text,
    model_override text,
    max_retries integer,
    goal_mode integer DEFAULT 0 NOT NULL,
    goal_max_turns integer,
    session_id text,
    block_kind text,
    block_recurrences integer DEFAULT 0 NOT NULL
);

CREATE TABLE IF NOT EXISTS public.telegram_dm_topic_bindings (
    chat_id text NOT NULL,
    thread_id text NOT NULL,
    user_id text NOT NULL,
    session_key text NOT NULL,
    session_id text NOT NULL,
    managed_mode text DEFAULT 'auto'::text NOT NULL,
    linked_at real NOT NULL,
    updated_at real NOT NULL
);

CREATE TABLE IF NOT EXISTS public.telegram_dm_topic_mode (
    chat_id text NOT NULL,
    user_id text NOT NULL,
    enabled integer DEFAULT 1 NOT NULL,
    activated_at real NOT NULL,
    updated_at real NOT NULL,
    has_topics_enabled integer,
    allows_users_to_create_topics integer,
    capability_checked_at real,
    intro_message_id text,
    pinned_message_id text
);

CREATE TABLE IF NOT EXISTS public.telemetry (
    id bigint NOT NULL,
    session_id text NOT NULL,
    date text NOT NULL,
    input_tokens integer DEFAULT 0,
    output_tokens integer DEFAULT 0,
    tool_calls integer DEFAULT 0,
    tool_names text DEFAULT '[]'::text
);

CREATE SEQUENCE IF NOT EXISTS public.telemetry_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.telemetry_id_seq OWNED BY public.telemetry.id;

CREATE TABLE IF NOT EXISTS public.tool_calls (
    id bigint NOT NULL,
    user_id text,
    session_id text,
    "timestamp" double precision DEFAULT EXTRACT(epoch FROM now()) NOT NULL,
    tool_name text NOT NULL,
    toolset text,
    success integer DEFAULT 1,
    duration_ms integer,
    error_message text,
    result_size_bytes integer
);

CREATE SEQUENCE IF NOT EXISTS public.tool_calls_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.tool_calls_id_seq OWNED BY public.tool_calls.id;

CREATE TABLE IF NOT EXISTS public.topics (
    id bigint NOT NULL,
    name text NOT NULL,
    why_it_matters text DEFAULT ''::text,
    emotional_weight text DEFAULT 'neutral'::text,
    engagement_count integer DEFAULT 1,
    last_mentioned double precision DEFAULT EXTRACT(epoch FROM now()),
    trigger_keywords text DEFAULT ''::text,
    related_facts text DEFAULT ''::text,
    created_at double precision DEFAULT EXTRACT(epoch FROM now())
);

CREATE SEQUENCE IF NOT EXISTS public.topics_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.topics_id_seq OWNED BY public.topics.id;

CREATE TABLE IF NOT EXISTS public.usage_logs (
    id bigint NOT NULL,
    telegram_id bigint NOT NULL,
    date text NOT NULL,
    sessions_count integer DEFAULT 0,
    input_tokens integer DEFAULT 0,
    output_tokens integer DEFAULT 0,
    tool_calls_count integer DEFAULT 0,
    top_tools text DEFAULT '{}'::text
);

CREATE SEQUENCE IF NOT EXISTS public.usage_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.usage_logs_id_seq OWNED BY public.usage_logs.id;

CREATE TABLE IF NOT EXISTS public.use_cases (
    id bigint NOT NULL,
    title text NOT NULL,
    description text NOT NULL,
    category text DEFAULT 'general'::text NOT NULL,
    tools_needed text DEFAULT ''::text,
    skills_needed text DEFAULT ''::text,
    memory_refs text DEFAULT ''::text,
    value_proposition text NOT NULL,
    example_prompts text DEFAULT ''::text,
    triggers text DEFAULT ''::text,
    created_at double precision DEFAULT EXTRACT(epoch FROM now()),
    updated_at double precision DEFAULT EXTRACT(epoch FROM now()),
    weight real DEFAULT 0.5
);

CREATE SEQUENCE IF NOT EXISTS public.use_cases_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.use_cases_id_seq OWNED BY public.use_cases.id;

CREATE TABLE IF NOT EXISTS public.user_profiles (
    telegram_id bigint NOT NULL,
    name text DEFAULT ''::text,
    email text DEFAULT ''::text,
    role text DEFAULT 'end_user'::text NOT NULL,
    bot_token text NOT NULL,
    created_at double precision DEFAULT EXTRACT(epoch FROM now()),
    last_active_at real,
    active integer DEFAULT 1,
    bot_id text,
    gateway text,
    tier text DEFAULT 'shared'::text,
    status text DEFAULT 'active'::text,
    rate_limit integer DEFAULT 20,
    rate_window integer DEFAULT 60,
    min_interval real DEFAULT 1.0,
    daily_quota integer DEFAULT 500
);


-- ============================================================
-- user schema: central user/bot registry (gate identity unit)
-- PK is bot_id (the identity unit the gate keys on), NOT telegram_id
-- (telegram_id collides across tiers: internal agents + end users share chat IDs)
-- ============================================================
CREATE SCHEMA IF NOT EXISTS end_user;

CREATE TABLE IF NOT EXISTS end_user.user_profiles (
    bot_id         text PRIMARY KEY,
    telegram_id    bigint NOT NULL,
    name           text NOT NULL DEFAULT '',
    email          text NOT NULL DEFAULT '',
    role           text NOT NULL DEFAULT 'end_user',
    bot_token      text NOT NULL DEFAULT '',
    gateway        text NOT NULL DEFAULT '',
    tier           text NOT NULL DEFAULT 'shared',
    status         text NOT NULL DEFAULT 'active',
    rate_limit     integer NOT NULL DEFAULT 20,
    rate_window    integer NOT NULL DEFAULT 60,
    min_interval   real NOT NULL DEFAULT 1.0,
    daily_quota    integer NOT NULL DEFAULT 500,
    created_at     double precision DEFAULT EXTRACT(epoch FROM now()),
    last_active_at real,
    active         integer NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS public.user_says (
    id bigint NOT NULL,
    message text NOT NULL,
    session_id text DEFAULT ''::text,
    session_name text DEFAULT ''::text,
    link_entries text DEFAULT ''::text,
    created_at double precision DEFAULT EXTRACT(epoch FROM now()),
    heartbeat_processed integer DEFAULT 0,
    source_id integer,
    message_type text DEFAULT 'conversation'::text
);

CREATE SEQUENCE IF NOT EXISTS public.user_says_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.user_says_id_seq OWNED BY public.user_says.id;

CREATE TABLE IF NOT EXISTS public.users (
    id bigint NOT NULL,
    telegram_id bigint,
    username text,
    display_name text,
    role text DEFAULT 'end_user'::text,
    status text DEFAULT 'active'::text,
    created_at real,
    last_active real,
    onboarding_completed integer DEFAULT 0,
    plan text DEFAULT 'free'::text,
    notes text
);

CREATE SEQUENCE IF NOT EXISTS public.users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;

CREATE TABLE IF NOT EXISTS public.verification_events (
    id bigint NOT NULL,
    created_at text NOT NULL,
    session_id text NOT NULL,
    cwd text NOT NULL,
    root text NOT NULL,
    command text NOT NULL,
    canonical_command text NOT NULL,
    kind text NOT NULL,
    scope text NOT NULL,
    status text NOT NULL,
    exit_code integer NOT NULL,
    output_summary text NOT NULL
);

CREATE SEQUENCE IF NOT EXISTS public.verification_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.verification_events_id_seq OWNED BY public.verification_events.id;

CREATE TABLE IF NOT EXISTS public.verification_meta (
    key text NOT NULL,
    value text NOT NULL
);

CREATE TABLE IF NOT EXISTS public.verification_state (
    session_id text NOT NULL,
    root text NOT NULL,
    last_event_id integer,
    last_edit_at text,
    changed_paths_json text DEFAULT '[]'::text NOT NULL
);

ALTER TABLE ONLY public.active ALTER COLUMN id SET DEFAULT nextval('public.active_id_seq'::regclass);

ALTER TABLE ONLY public.agent_queue ALTER COLUMN id SET DEFAULT nextval('public.agent_queue_id_seq'::regclass);

ALTER TABLE ONLY public.agent_state ALTER COLUMN id SET DEFAULT nextval('public.agent_state_id_seq'::regclass);

ALTER TABLE ONLY public.agent_talks ALTER COLUMN id SET DEFAULT nextval('public.agent_talks_id_seq'::regclass);

ALTER TABLE ONLY public.capabilities ALTER COLUMN id SET DEFAULT nextval('public.capabilities_id_seq'::regclass);

ALTER TABLE ONLY public.coaching ALTER COLUMN id SET DEFAULT nextval('public.coaching_id_seq'::regclass);

ALTER TABLE ONLY public.emotional_tones ALTER COLUMN id SET DEFAULT nextval('public.emotional_tones_id_seq'::regclass);

ALTER TABLE ONLY public.entities ALTER COLUMN entity_id SET DEFAULT nextval('public.entities_entity_id_seq'::regclass);

ALTER TABLE ONLY public.group_messages ALTER COLUMN id SET DEFAULT nextval('public.group_messages_id_seq'::regclass);

ALTER TABLE ONLY public.growth_log ALTER COLUMN id SET DEFAULT nextval('public.growth_log_id_seq'::regclass);

ALTER TABLE ONLY public.integrations ALTER COLUMN id SET DEFAULT nextval('public.integrations_id_seq'::regclass);

ALTER TABLE ONLY public.knowledge ALTER COLUMN id SET DEFAULT nextval('public.knowledge_id_seq'::regclass);

ALTER TABLE ONLY public.llm_calls ALTER COLUMN id SET DEFAULT nextval('public.llm_calls_id_seq'::regclass);

ALTER TABLE ONLY public.loops ALTER COLUMN id SET DEFAULT nextval('public.loops_id_seq'::regclass);

ALTER TABLE ONLY public.messages ALTER COLUMN id SET DEFAULT nextval('public.messages_id_seq'::regclass);

ALTER TABLE ONLY public.moods ALTER COLUMN id SET DEFAULT nextval('public.moods_id_seq'::regclass);

ALTER TABLE ONLY public.onboarding ALTER COLUMN id SET DEFAULT nextval('public.onboarding_id_seq'::regclass);

ALTER TABLE ONLY public.oracle_diagnostics ALTER COLUMN id SET DEFAULT nextval('public.oracle_diagnostics_id_seq'::regclass);

ALTER TABLE ONLY public.oracle_log ALTER COLUMN id SET DEFAULT nextval('public.oracle_log_id_seq'::regclass);

ALTER TABLE ONLY public.patterns ALTER COLUMN id SET DEFAULT nextval('public.patterns_id_seq'::regclass);

ALTER TABLE ONLY public.plugin_usage ALTER COLUMN id SET DEFAULT nextval('public.plugin_usage_id_seq'::regclass);

ALTER TABLE ONLY public.pulse ALTER COLUMN id SET DEFAULT nextval('public.pulse_id_seq'::regclass);

ALTER TABLE ONLY public.pulse_history ALTER COLUMN id SET DEFAULT nextval('public.pulse_history_id_seq'::regclass);

ALTER TABLE ONLY public.reflections ALTER COLUMN id SET DEFAULT nextval('public.reflections_id_seq'::regclass);

ALTER TABLE ONLY public.signals ALTER COLUMN id SET DEFAULT nextval('public.signals_id_seq'::regclass);

ALTER TABLE ONLY public.skill_files ALTER COLUMN id SET DEFAULT nextval('public.skill_files_id_seq'::regclass);

ALTER TABLE ONLY public.skills ALTER COLUMN id SET DEFAULT nextval('public.skills_id_seq'::regclass);

ALTER TABLE ONLY public.small_talk ALTER COLUMN id SET DEFAULT nextval('public.small_talk_id_seq'::regclass);

ALTER TABLE ONLY public.staging_inbox ALTER COLUMN id SET DEFAULT nextval('public.staging_inbox_id_seq'::regclass);

ALTER TABLE ONLY public.state ALTER COLUMN id SET DEFAULT nextval('public.state_id_seq'::regclass);

ALTER TABLE ONLY public.tags ALTER COLUMN id SET DEFAULT nextval('public.tags_id_seq'::regclass);

ALTER TABLE ONLY public.task_attachments ALTER COLUMN id SET DEFAULT nextval('public.task_attachments_id_seq'::regclass);

ALTER TABLE ONLY public.task_comments ALTER COLUMN id SET DEFAULT nextval('public.task_comments_id_seq'::regclass);

ALTER TABLE ONLY public.task_context ALTER COLUMN id SET DEFAULT nextval('public.task_context_id_seq'::regclass);

ALTER TABLE ONLY public.task_events ALTER COLUMN id SET DEFAULT nextval('public.task_events_id_seq'::regclass);

ALTER TABLE ONLY public.task_runs ALTER COLUMN id SET DEFAULT nextval('public.task_runs_id_seq'::regclass);

ALTER TABLE ONLY public.telemetry ALTER COLUMN id SET DEFAULT nextval('public.telemetry_id_seq'::regclass);

ALTER TABLE ONLY public.tool_calls ALTER COLUMN id SET DEFAULT nextval('public.tool_calls_id_seq'::regclass);

ALTER TABLE ONLY public.topics ALTER COLUMN id SET DEFAULT nextval('public.topics_id_seq'::regclass);

ALTER TABLE ONLY public.usage_logs ALTER COLUMN id SET DEFAULT nextval('public.usage_logs_id_seq'::regclass);

ALTER TABLE ONLY public.use_cases ALTER COLUMN id SET DEFAULT nextval('public.use_cases_id_seq'::regclass);

ALTER TABLE ONLY public.user_says ALTER COLUMN id SET DEFAULT nextval('public.user_says_id_seq'::regclass);

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);

ALTER TABLE ONLY public.verification_events ALTER COLUMN id SET DEFAULT nextval('public.verification_events_id_seq'::regclass);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'active_pkey') THEN
    ALTER TABLE ONLY public.active
    ADD CONSTRAINT active_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'agent_auth_pkey') THEN
    ALTER TABLE ONLY public.agent_auth
    ADD CONSTRAINT agent_auth_pkey PRIMARY KEY (agent_name);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'agent_health_pkey') THEN
    ALTER TABLE ONLY public.agent_health
    ADD CONSTRAINT agent_health_pkey PRIMARY KEY (agent_name);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'agent_queue_pkey') THEN
    ALTER TABLE ONLY public.agent_queue
    ADD CONSTRAINT agent_queue_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'agent_state_pkey') THEN
    ALTER TABLE ONLY public.agent_state
    ADD CONSTRAINT agent_state_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'agent_talks_pkey') THEN
    ALTER TABLE ONLY public.agent_talks
    ADD CONSTRAINT agent_talks_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'capabilities_pkey') THEN
    ALTER TABLE ONLY public.capabilities
    ADD CONSTRAINT capabilities_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'capabilities_tool_name_key') THEN
    ALTER TABLE ONLY public.capabilities
    ADD CONSTRAINT capabilities_tool_name_key UNIQUE (tool_name);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'coaching_pkey') THEN
    ALTER TABLE ONLY public.coaching
    ADD CONSTRAINT coaching_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'compression_locks_pkey') THEN
    ALTER TABLE ONLY public.compression_locks
    ADD CONSTRAINT compression_locks_pkey PRIMARY KEY (session_id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'discovered_repos_pkey') THEN
    ALTER TABLE ONLY public.discovered_repos
    ADD CONSTRAINT discovered_repos_pkey PRIMARY KEY (root);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'emotional_tones_name_key') THEN
    ALTER TABLE ONLY public.emotional_tones
    ADD CONSTRAINT emotional_tones_name_key UNIQUE (name);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'emotional_tones_pkey') THEN
    ALTER TABLE ONLY public.emotional_tones
    ADD CONSTRAINT emotional_tones_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'entities_name_key') THEN
    ALTER TABLE ONLY public.entities
    ADD CONSTRAINT entities_name_key UNIQUE (name);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'entities_pkey') THEN
    ALTER TABLE ONLY public.entities
    ADD CONSTRAINT entities_pkey PRIMARY KEY (entity_id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fact_entities_pkey') THEN
    ALTER TABLE ONLY public.fact_entities
    ADD CONSTRAINT fact_entities_pkey PRIMARY KEY (fact_id, entity_id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'group_messages_pkey') THEN
    ALTER TABLE ONLY public.group_messages
    ADD CONSTRAINT group_messages_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'growth_log_pkey') THEN
    ALTER TABLE ONLY public.growth_log
    ADD CONSTRAINT growth_log_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'integrations_pkey') THEN
    ALTER TABLE ONLY public.integrations
    ADD CONSTRAINT integrations_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'knowledge_pkey') THEN
    ALTER TABLE ONLY public.knowledge
    ADD CONSTRAINT knowledge_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'llm_calls_pkey') THEN
    ALTER TABLE ONLY public.llm_calls
    ADD CONSTRAINT llm_calls_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'loops_pkey') THEN
    ALTER TABLE ONLY public.loops
    ADD CONSTRAINT loops_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'messages_pkey') THEN
    ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'moods_pkey') THEN
    ALTER TABLE ONLY public.moods
    ADD CONSTRAINT moods_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'onboarding_pkey') THEN
    ALTER TABLE ONLY public.onboarding
    ADD CONSTRAINT onboarding_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'onboarding_question_key_key') THEN
    ALTER TABLE ONLY public.onboarding
    ADD CONSTRAINT onboarding_question_key_key UNIQUE (question_key);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'oracle_diagnostics_pkey') THEN
    ALTER TABLE ONLY public.oracle_diagnostics
    ADD CONSTRAINT oracle_diagnostics_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'oracle_log_pkey') THEN
    ALTER TABLE ONLY public.oracle_log
    ADD CONSTRAINT oracle_log_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'patterns_name_key') THEN
    ALTER TABLE ONLY public.patterns
    ADD CONSTRAINT patterns_name_key UNIQUE (name);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'patterns_pkey') THEN
    ALTER TABLE ONLY public.patterns
    ADD CONSTRAINT patterns_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pipeline_control_pkey') THEN
    ALTER TABLE ONLY public.pipeline_control
    ADD CONSTRAINT pipeline_control_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'plugin_usage_pkey') THEN
    ALTER TABLE ONLY public.plugin_usage
    ADD CONSTRAINT plugin_usage_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'project_folders_pkey') THEN
    ALTER TABLE ONLY public.project_folders
    ADD CONSTRAINT project_folders_pkey PRIMARY KEY (project_id, path);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'project_meta_pkey') THEN
    ALTER TABLE ONLY public.project_meta
    ADD CONSTRAINT project_meta_pkey PRIMARY KEY (key);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'projects_pkey') THEN
    ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'projects_slug_key') THEN
    ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_slug_key UNIQUE (slug);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pulse_history_pkey') THEN
    ALTER TABLE ONLY public.pulse_history
    ADD CONSTRAINT pulse_history_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pulse_pkey') THEN
    ALTER TABLE ONLY public.pulse
    ADD CONSTRAINT pulse_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'reflections_pkey') THEN
    ALTER TABLE ONLY public.reflections
    ADD CONSTRAINT reflections_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'sessions_pkey') THEN
    ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'signals_pkey') THEN
    ALTER TABLE ONLY public.signals
    ADD CONSTRAINT signals_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'skill_files_pkey') THEN
    ALTER TABLE ONLY public.skill_files
    ADD CONSTRAINT skill_files_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'skills_name_key') THEN
    ALTER TABLE ONLY public.skills
    ADD CONSTRAINT skills_name_key UNIQUE (name);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'skills_pkey') THEN
    ALTER TABLE ONLY public.skills
    ADD CONSTRAINT skills_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'small_talk_pkey') THEN
    ALTER TABLE ONLY public.small_talk
    ADD CONSTRAINT small_talk_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'staging_inbox_pkey') THEN
    ALTER TABLE ONLY public.staging_inbox
    ADD CONSTRAINT staging_inbox_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'state_meta_pkey') THEN
    ALTER TABLE ONLY public.state_meta
    ADD CONSTRAINT state_meta_pkey PRIMARY KEY (key);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tags_name_key') THEN
    ALTER TABLE ONLY public.tags
    ADD CONSTRAINT tags_name_key UNIQUE (name);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tags_pkey') THEN
    ALTER TABLE ONLY public.tags
    ADD CONSTRAINT tags_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'task_attachments_pkey') THEN
    ALTER TABLE ONLY public.task_attachments
    ADD CONSTRAINT task_attachments_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'task_comments_pkey') THEN
    ALTER TABLE ONLY public.task_comments
    ADD CONSTRAINT task_comments_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'task_context_pkey') THEN
    ALTER TABLE ONLY public.task_context
    ADD CONSTRAINT task_context_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'task_events_pkey') THEN
    ALTER TABLE ONLY public.task_events
    ADD CONSTRAINT task_events_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'task_links_pkey') THEN
    ALTER TABLE ONLY public.task_links
    ADD CONSTRAINT task_links_pkey PRIMARY KEY (parent_id, child_id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'task_runs_pkey') THEN
    ALTER TABLE ONLY public.task_runs
    ADD CONSTRAINT task_runs_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tasks_pkey') THEN
    ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'telegram_dm_topic_bindings_pkey') THEN
    ALTER TABLE ONLY public.telegram_dm_topic_bindings
    ADD CONSTRAINT telegram_dm_topic_bindings_pkey PRIMARY KEY (chat_id, thread_id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'telegram_dm_topic_mode_pkey') THEN
    ALTER TABLE ONLY public.telegram_dm_topic_mode
    ADD CONSTRAINT telegram_dm_topic_mode_pkey PRIMARY KEY (chat_id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'telemetry_pkey') THEN
    ALTER TABLE ONLY public.telemetry
    ADD CONSTRAINT telemetry_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tool_calls_pkey') THEN
    ALTER TABLE ONLY public.tool_calls
    ADD CONSTRAINT tool_calls_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'topics_name_key') THEN
    ALTER TABLE ONLY public.topics
    ADD CONSTRAINT topics_name_key UNIQUE (name);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'topics_pkey') THEN
    ALTER TABLE ONLY public.topics
    ADD CONSTRAINT topics_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'usage_logs_pkey') THEN
    ALTER TABLE ONLY public.usage_logs
    ADD CONSTRAINT usage_logs_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'use_cases_pkey') THEN
    ALTER TABLE ONLY public.use_cases
    ADD CONSTRAINT use_cases_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_profiles_pkey') THEN
    ALTER TABLE ONLY public.user_profiles
    ADD CONSTRAINT user_profiles_pkey PRIMARY KEY (telegram_id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'user_profiles_bot_id_key') THEN
    CREATE UNIQUE INDEX user_profiles_bot_id_key ON public.user_profiles (bot_id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'user_says_pkey') THEN
    ALTER TABLE ONLY public.user_says
    ADD CONSTRAINT user_says_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_pkey') THEN
    ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_telegram_id_key') THEN
    ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_telegram_id_key UNIQUE (telegram_id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'verification_events_pkey') THEN
    ALTER TABLE ONLY public.verification_events
    ADD CONSTRAINT verification_events_pkey PRIMARY KEY (id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'verification_meta_pkey') THEN
    ALTER TABLE ONLY public.verification_meta
    ADD CONSTRAINT verification_meta_pkey PRIMARY KEY (key);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'verification_state_pkey') THEN
    ALTER TABLE ONLY public.verification_state
    ADD CONSTRAINT verification_state_pkey PRIMARY KEY (session_id, root);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_agent_queue_created ON public.agent_queue USING btree (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_queue_to_status ON public.agent_queue USING btree (to_agent, status);

CREATE INDEX IF NOT EXISTS idx_agent_talks_created ON public.agent_talks USING btree (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_talks_heartbeat ON public.agent_talks USING btree (heartbeat_processed);

CREATE INDEX IF NOT EXISTS idx_agent_talks_session ON public.agent_talks USING btree (session_id);

CREATE INDEX IF NOT EXISTS idx_agent_talks_source ON public.agent_talks USING btree (source_id);

CREATE INDEX IF NOT EXISTS idx_capabilities_tool ON public.capabilities USING btree (tool_name);

CREATE INDEX IF NOT EXISTS idx_coaching_session ON public.coaching USING btree (session_id, turn);

CREATE INDEX IF NOT EXISTS idx_entities_name ON public.entities USING btree (name);

CREATE INDEX IF NOT EXISTS idx_fact_entities_entity ON public.fact_entities USING btree (entity_id);

CREATE INDEX IF NOT EXISTS idx_fact_entities_fact ON public.fact_entities USING btree (fact_id);

CREATE INDEX IF NOT EXISTS idx_group_messages_agent ON public.group_messages USING btree (from_agent, "timestamp" DESC);

CREATE INDEX IF NOT EXISTS idx_group_messages_chat ON public.group_messages USING btree (chat_id, "timestamp" DESC);

CREATE INDEX IF NOT EXISTS idx_group_messages_direction ON public.group_messages USING btree (direction, "timestamp" DESC);

CREATE INDEX IF NOT EXISTS idx_group_messages_session ON public.group_messages USING btree (session_id, "timestamp" DESC);

CREATE INDEX IF NOT EXISTS idx_knowledge_search ON public.knowledge USING gin (search_vector);

CREATE INDEX IF NOT EXISTS idx_knowledge_type ON public.knowledge USING btree (entity_type);

CREATE UNIQUE INDEX idx_knowledge_unique ON public.knowledge USING btree (profile, entity_type, name);

CREATE INDEX IF NOT EXISTS idx_llm_calls_session ON public.llm_calls USING btree (session_id);

CREATE INDEX IF NOT EXISTS idx_llm_calls_timestamp ON public.llm_calls USING btree ("timestamp" DESC);

CREATE INDEX IF NOT EXISTS idx_llm_calls_user ON public.llm_calls USING btree (user_id, "timestamp");

CREATE INDEX IF NOT EXISTS idx_loops_active ON public.loops USING btree (resolved, priority, created_at);

CREATE INDEX IF NOT EXISTS idx_messages_search ON public.messages USING gin (search_vector);

CREATE INDEX IF NOT EXISTS idx_messages_session ON public.messages USING btree (session_id, "timestamp");

CREATE INDEX IF NOT EXISTS idx_messages_session_active ON public.messages USING btree (session_id, active, "timestamp");

CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON public.messages USING btree ("timestamp" DESC);

CREATE INDEX IF NOT EXISTS idx_messages_role_active ON public.messages USING btree (role, active, compacted, "timestamp" DESC);

CREATE INDEX IF NOT EXISTS idx_moods_source ON public.moods USING btree (source_id);

CREATE INDEX IF NOT EXISTS idx_moods_user ON public.moods USING btree (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_oracle_diag_session ON public.oracle_diagnostics USING btree (session_id, window_end_turn);

CREATE INDEX IF NOT EXISTS idx_oracle_dna ON public.oracle_log USING btree (dna_matched);

CREATE INDEX IF NOT EXISTS idx_oracle_loop ON public.oracle_log USING btree (loop_detected);

CREATE INDEX IF NOT EXISTS idx_oracle_session ON public.oracle_log USING btree (session_id, turn);

CREATE INDEX IF NOT EXISTS idx_oracle_signal ON public.oracle_log USING btree (oracle_signal);

CREATE INDEX IF NOT EXISTS idx_oracle_task ON public.oracle_log USING btree (task_completed);

CREATE INDEX IF NOT EXISTS idx_oracle_verify ON public.oracle_log USING btree (verification_status);

CREATE INDEX IF NOT EXISTS idx_patterns_confidence ON public.patterns USING btree (confidence);

CREATE INDEX IF NOT EXISTS idx_patterns_type ON public.patterns USING btree (pattern_type);

CREATE UNIQUE INDEX idx_plugin_usage_user_plugin ON public.plugin_usage USING btree (telegram_id, plugin_name);

CREATE INDEX IF NOT EXISTS idx_project_folders_path ON public.project_folders USING btree (path);

CREATE INDEX IF NOT EXISTS idx_pulse_created ON public.pulse USING btree (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_reflections_session ON public.reflections USING btree (session_id);

CREATE INDEX IF NOT EXISTS idx_sessions_parent ON public.sessions USING btree (parent_session_id);

CREATE INDEX IF NOT EXISTS idx_sessions_source ON public.sessions USING btree (source);

CREATE INDEX IF NOT EXISTS idx_sessions_source_id ON public.sessions USING btree (source, id);

CREATE INDEX IF NOT EXISTS idx_sessions_started ON public.sessions USING btree (started_at DESC);

CREATE INDEX IF NOT EXISTS idx_signals_enabled ON public.signals USING btree (enabled);

CREATE INDEX IF NOT EXISTS idx_signals_trigger ON public.signals USING btree (trigger);

CREATE INDEX IF NOT EXISTS idx_staging_pending ON public.staging_inbox USING btree (acknowledged, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_staging_project ON public.staging_inbox USING btree (project) WHERE (project IS NOT NULL);

CREATE INDEX IF NOT EXISTS idx_task_attachments_task ON public.task_attachments USING btree (task_id, created_at);

CREATE INDEX IF NOT EXISTS idx_task_comments_task ON public.task_comments USING btree (task_id, created_at);

CREATE UNIQUE INDEX idx_task_context_project ON public.task_context USING btree (project_name);

CREATE INDEX IF NOT EXISTS idx_task_events_run ON public.task_events USING btree (run_id, id);

CREATE INDEX IF NOT EXISTS idx_task_events_task ON public.task_events USING btree (task_id, created_at);

CREATE INDEX IF NOT EXISTS idx_task_links_child ON public.task_links USING btree (child_id);

CREATE INDEX IF NOT EXISTS idx_task_links_parent ON public.task_links USING btree (parent_id);

CREATE INDEX IF NOT EXISTS idx_task_runs_status ON public.task_runs USING btree (status);

CREATE INDEX IF NOT EXISTS idx_task_runs_task ON public.task_runs USING btree (task_id, started_at);

CREATE INDEX IF NOT EXISTS idx_tasks_assignee_status ON public.tasks USING btree (assignee, status);

CREATE INDEX IF NOT EXISTS idx_tasks_board ON public.tasks USING btree (board_id);

CREATE INDEX IF NOT EXISTS idx_tasks_idempotency ON public.tasks USING btree (idempotency_key);

CREATE INDEX IF NOT EXISTS idx_tasks_session_id ON public.tasks USING btree (session_id);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON public.tasks USING btree (status);

CREATE INDEX IF NOT EXISTS idx_tasks_tenant ON public.tasks USING btree (tenant);

CREATE UNIQUE INDEX idx_telegram_dm_topic_bindings_session ON public.telegram_dm_topic_bindings USING btree (session_id);

CREATE INDEX IF NOT EXISTS idx_telegram_dm_topic_bindings_user ON public.telegram_dm_topic_bindings USING btree (user_id, chat_id);

CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON public.tool_calls USING btree (session_id);

CREATE INDEX IF NOT EXISTS idx_tool_calls_timestamp ON public.tool_calls USING btree ("timestamp" DESC);

CREATE INDEX IF NOT EXISTS idx_tool_calls_user ON public.tool_calls USING btree (user_id, "timestamp");

CREATE INDEX IF NOT EXISTS idx_topics_engagement ON public.topics USING btree (engagement_count DESC);

CREATE INDEX IF NOT EXISTS idx_topics_last_mentioned ON public.topics USING btree (last_mentioned DESC);

CREATE UNIQUE INDEX idx_usage_logs_user_date ON public.usage_logs USING btree (telegram_id, date);

CREATE INDEX IF NOT EXISTS idx_use_cases_category ON public.use_cases USING btree (category);

CREATE INDEX IF NOT EXISTS idx_use_cases_weight ON public.use_cases USING btree (weight DESC);

CREATE INDEX IF NOT EXISTS idx_user_says_created ON public.user_says USING btree (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_user_says_heartbeat ON public.user_says USING btree (heartbeat_processed);

CREATE INDEX IF NOT EXISTS idx_user_says_session ON public.user_says USING btree (session_id);

CREATE INDEX IF NOT EXISTS idx_user_says_source ON public.user_says USING btree (source_id);

CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON public.users USING btree (telegram_id);

CREATE INDEX IF NOT EXISTS idx_verification_events_session_root ON public.verification_events USING btree (session_id, root, id DESC);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'project_folders_project_id_fkey') THEN
    ALTER TABLE ONLY public.project_folders
    ADD CONSTRAINT project_folders_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.gateway_events (
    id bigint NOT NULL,
    event_type text NOT NULL DEFAULT 'boot',
    commit_sha text DEFAULT ''::text,
    pid integer DEFAULT 0,
    hostname text DEFAULT ''::text,
    started_at double precision DEFAULT EXTRACT(epoch FROM now()),
    created_at double precision DEFAULT EXTRACT(epoch FROM now())
);

CREATE SEQUENCE IF NOT EXISTS public.gateway_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.gateway_events_id_seq OWNED BY public.gateway_events.id;

ALTER TABLE ONLY public.gateway_events ALTER COLUMN id SET DEFAULT nextval('public.gateway_events_id_seq'::regclass);

CREATE INDEX IF NOT EXISTS idx_gateway_events_started_at ON public.gateway_events USING btree (started_at DESC);
