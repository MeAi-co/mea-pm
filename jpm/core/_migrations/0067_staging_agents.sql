-- 0067_staging_agents.sql
-- Fleet-agent registry: the routing source of truth for cross-node assign.
-- WHY THIS MIGRATION EXISTS
-- The table was previously created ONLY inline in core/gateway/staging_api.py
-- (CREATE TABLE IF NOT EXISTS). That meant it materialised on whichever node
-- ran the live code first (the hub) and NEVER reached the other nodes — they
-- pull the repo but the migration runner had nothing to apply, so their local
-- jpm-pg showed `relation "staging_agents" does not exist`. The drift guard in
-- jpm/core/_pg.py only inspects the base schema (_schema_pg.sql), so an inline
-- CREATE TABLE is invisible to it too.
--
-- This migration is the canonical creator. Every node applies it to its OWN
-- local jpm-pg on gateway boot (jpm/core/_pg.py migration runner, tracked in
-- _schema_migrations), so each node's staging_assign tool can read the roster
-- from its own database — no cross-node query, no hub dependency.
--
-- STRUCTURE ONLY — NO DATA.
-- This file carries the schema and nothing else. The node roster (aliases,
-- hostnames, roles, ports) is NOT committed to git: deployment topology must
-- not travel through the repo. Each node backfills its own roster manually
-- (or via the /agents/register self-report at boot). An empty table is the
-- correct post-migration state.
--
-- DESIGN
--   * Stable handle is the hostname (survives IP changes), NOT the raw IP.
--   * webhook_port is per-node (differs) and self-reported from each node's
--     JOSHAICO_STAGING_PORT env at boot via POST /agents/register.
--   * Addressing key is the (hostname, webhook_port) tuple: self-spawned
--     copies share a host, so the port is the discriminator.
--   * role ports to the /role feature (programmer|assistant|manager).
--   * No node-branding in code — the roster is data, backfilled per node.
--   * Internal agents ONLY. End-user bots are a separate population and have
--     no access to this registry (they live in user_profiles, not here).
--
-- Idempotent: CREATE TABLE IF NOT EXISTS. Safe to re-apply on any node.

CREATE TABLE IF NOT EXISTS public.staging_agents (
    bot_alias     TEXT PRIMARY KEY,              -- routing key (per-node backfill)
    bot_id        BIGINT UNIQUE,                 -- numeric Telegram bot id (self-reported)
    bot_tag       TEXT,                          -- @username
    hostname      TEXT NOT NULL,                 -- stable handle (survives IP changes)
    access_mode   TEXT NOT NULL DEFAULT 'ssh',   -- 'ssh' | 'http'
    key_path      TEXT,                          -- SSH key path when direct HTTP is unavailable
    webhook_port  INTEGER,                       -- per-node, from JOSHAICO_STAGING_PORT
    role          TEXT NOT NULL DEFAULT 'worker',-- ports to /role: programmer|assistant|manager
    instance_of   TEXT,                          -- NULL for primary, parent alias for a spawned copy
    active        BOOLEAN NOT NULL DEFAULT true,
    last_seen     TIMESTAMPTZ,
    UNIQUE (magicdns, webhook_port)
);
