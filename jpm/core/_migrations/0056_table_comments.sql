-- 0056_table_comments.sql
-- Backfill COMMENT ON TABLE for all core JPM tables so the agent's memory
-- vault is self-describing. The prompt-injection hook (phase 2) reads these
-- via obj_description() to surface a live memory inventory to the agent.
-- Idempotent: COMMENT ON TABLE overwrites, safe to re-run.
--
-- Defensive: only comments tables that actually exist on THIS node. Fleet
-- nodes may not have every table (e.g. skill_escalation, _recent_sync,
-- messages_dedup_backup are node-specific), so a bare COMMENT ON TABLE on a
-- missing relation fails the whole migration and it never marks itself
-- applied. Guarding each with to_regclass() makes it safe everywhere.

DO $$
DECLARE
  _pairs text[][] := ARRAY[
    -- ============ CORE MEMORY / KNOWLEDGE ============
    ['knowledge', 'Persistent facts: user prefs, learnings, rules, identity. FTS + embedding search, trust scoring, entity links. The agent''s long-term memory.'],
    ['messages', 'Every conversation message across all sessions. Full history with role, tool calls, tokens, embeddings, dedup. The agent''s episodic memory.'],
    ['sessions', 'Session metadata: lineage (parent_session_id), lifecycle (end_reason), model, cost, chat binding, resume state.'],
    ['reflections', 'Distilled lessons learned from sessions: trigger, insight, impact. The agent''s self-improvement log.'],
    ['patterns', 'Reusable behavioral patterns with confidence, firing count, embedding.'],
    ['patterns_history', 'Historical record of pattern content and reference counts.'],
    ['pattern_evidence', 'Join table linking patterns to the knowledge facts that evidence them.'],
    ['pattern_triggers', 'Join table linking patterns to tags and tones that trigger them, with weight.'],
    ['entities', 'Named entities (systems, people, projects) referenced by knowledge facts.'],
    ['fact_entities', 'Join table linking knowledge facts to entities.'],
    ['fact_links', 'Explicit relationships between knowledge facts with relationship type and weight.'],
    ['fact_tags', 'Join table linking knowledge facts to tags.'],
    ['tags', 'Tag vocabulary used across knowledge and patterns.'],
    ['explanations', 'Explanations for knowledge facts: driver, confidence, supersession chain.'],
    ['explanation_evidence', 'Join table linking explanations to the facts that support them.'],
    ['topics', 'Conversation topics with emotional weight, engagement count, trigger keywords.'],
    ['small_talk', 'Lightweight social/banter memory: topic, date, vibe.'],
    ['use_cases', 'Catalog of agent use cases: tools/skills/memory needed, value, example prompts.'],
    ['emotional_tones', 'Emotional tone vocabulary with valence and arousal dimensions.'],
    ['moods', 'User mood snapshots over time.'],
    ['user_says', 'Notable user statements with session linkage.'],
    ['user_profiles', 'End-user bot profiles: telegram_id, name, role, bot_token, active state.'],
    ['users', 'User accounts: identity, role, status, onboarding, plan.'],
    ['onboarding', 'Onboarding question flow: questions, phases, answers, target weights.'],
    -- ============ AGENT STATE ============
    ['pulse', 'Agent current status: status, summary, confidence, source message.'],
    ['pulse_history', 'Historical pulse snapshots: mood, energy, health, headspace.'],
    ['active', 'Active focus areas and projects with status.'],
    ['active_focus', 'Current focus/project pointer with status.'],
    ['loops', 'Open issues/loops to resolve with priority and resolution state.'],
    ['state', 'Agent state: mood, energy, headspace, skill override, valence/arousal.'],
    ['state_meta', 'Key/value metadata for agent state.'],
    ['capabilities', 'Tool capability inventory: proficiency, use count, last used.'],
    ['agent_state', 'Per-agent state: mood, energy, headspace, skill override/directive.'],
    ['agent_health', 'Per-agent health pings: last_ping, status, version, uptime.'],
    ['agent_auth', 'Agent auth tokens: hashed tokens, revocation state.'],
    ['agent_talks', 'Agent-to-agent talk messages with session linkage and tool counts.'],
    ['agent_queue', 'Inter-agent message queue: from/to agent, type, priority, project, status.'],
    -- ============ TASKS / PROJECTS ============
    ['tasks', 'Task board items: title, body, assignee, status, priority, workspace, claim lock, runs.'],
    ['task_runs', 'Task execution runs: step, status, worker, outcome, summary, error.'],
    ['task_events', 'Task lifecycle events: kind, payload, run linkage.'],
    ['task_attachments', 'Files attached to tasks: stored path, content type, size, uploader.'],
    ['task_comments', 'Comments on tasks: author, body, timestamp.'],
    ['task_links', 'Parent/child task relationships.'],
    ['task_context', 'Per-project task state: milestone, status.'],
    ['tasks_notify_subs', 'Task notification subscriptions: platform, chat, notifier profile.'],
    ['kanban_notify_subs', 'Kanban notification subscriptions: task, platform, chat, notifier.'],
    ['staging_tasks', 'Staging/worker task queue: bot_id, board, assignee, workspace, claim, goal mode, session.'],
    ['projects', 'Projects: slug, name, description, icon, board, primary path, archive state.'],
    ['project_sessions', 'Join table binding projects to sessions.'],
    ['project_skills', 'Join table binding projects to their skill libraries.'],
    ['project_folders', 'Project folder paths: primary flag, label.'],
    ['project_meta', 'Key/value metadata for projects.'],
    -- ============ STAGING / GROUP CHAT ============
    ['staging', 'Raw inbound text staging: source, status, error.'],
    ['staging_inbox', 'Inter-agent staging inbox: from agent, type, priority, ack state.'],
    ['group_messages', 'Group-chat messages: chat/thread, from agent/user, direction, metadata.'],
    -- ============ TELEMETRY / OPS ============
    ['tool_calls', 'Tool invocation telemetry: tool, toolset, success, duration, result size.'],
    ['llm_calls', 'LLM call telemetry: model, provider, token counts, cost, latency, success.'],
    ['telemetry', 'Per-session daily telemetry: tokens, tool calls, tool names.'],
    ['usage_logs', 'Per-user daily usage: sessions, tokens, tool calls, top tools.'],
    ['gateway_events', 'Gateway lifecycle events: type, commit, pid, hostname, timestamps.'],
    ['credentials', 'Platform credentials: encrypted tokens, refresh, expiry, scopes.'],
    ['integrations', 'Platform integration state: connected, sync, scopes.'],
    ['plugin_usage', 'Per-user plugin usage: first/last used, count, enabled.'],
    ['signals', 'Signal definitions: trigger, action, params, enabled.'],
    ['discovered_repos', 'Discovered git repos: root, label, last seen.'],
    ['compression_locks', 'Context compression locks per session: holder, expiry.'],
    ['pipeline_control', 'Pipeline pause control: paused state, reason, timestamps.'],
    ['synthesis_queue', 'Knowledge synthesis queue: cluster ids, name, reason, status.'],
    ['reflection_queue', 'Reflection queue: topic type, reference, priority, result fact.'],
    ['growth_log', 'Agent growth log: content, category, timestamp.'],
    ['coaching', 'Coaching session lines: turn, line, oracle context.'],
    ['oracle_log', 'Oracle self-improvement log: tool calls, validation, verification, loop detection.'],
    ['oracle_diagnostics', 'Oracle diagnostic metrics: validation/verification/steering rates, loop counts.'],
    ['verification_state', 'Verification tracking: last event, changed paths per session/root.'],
    ['verification_events', 'Verification events: command, kind, scope, status, exit code, output summary.'],
    ['verification_meta', 'Key/value metadata for verification.'],
    ['skill_escalation', 'Skill escalation tracking: tier, strikes, last turn per session/skill.'],
    ['schema_version', 'Schema version marker.'],
    ['_schema_migrations', 'Applied migration tracking: name, applied_at, checksum.'],
    ['_recent_sync', 'Recent message sync cache: role, content, tokens, dedup, platform id.'],
    -- ============ TELEGRAM DM TOPICS ============
    ['telegram_dm_topic_bindings', 'Telegram DM topic bindings: chat/thread to session, managed mode.'],
    ['telegram_dm_topic_mode', 'Telegram DM topic mode config: enabled, capabilities, intro/pinned messages.'],
    -- ============ SKILLS ============
    ['skills', 'Skill library: name, category, description, version, tags, content, usage, lifecycle state.'],
    ['skill_files', 'Skill supporting files: file_path, content, linked chain.'],
    -- ============ BACKUP / DEDUP ============
    ['messages_dedup_backup', 'Backup of messages before dedup cleanup.'],
    ['messages_dedup_content_backup', 'Backup of message content before dedup cleanup.']
  ];
  _pair text[];
  _tname text;
  _c text;
BEGIN
  FOREACH _pair SLICE 1 IN ARRAY _pairs LOOP
    _tname := _pair[1];
    _c := _pair[2];
    IF to_regclass('public.' || quote_ident(_tname)) IS NOT NULL THEN
      EXECUTE format('COMMENT ON TABLE public.%I IS %L', _tname, _c);
    END IF;
  END LOOP;
END $$;
