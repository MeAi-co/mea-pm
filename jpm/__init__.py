"""jpm — Workhorse Memory for Development Agents

Stripped-down JPM for dev agents. No personality tracking,
no emotional fluff, no small talk. Pure project context.

Schema:
  pulse          — project status snapshots
  active         — current focus/project
  loops          — open dev issues, bugs, todos
  knowledge      — systems, configs, architecture, dependencies (FTS5)
  reflections    — technical lessons learned
  capabilities   — tool proficiency
  task_context   — project milestones, deployment status

Storage:
  DB (persistent_memory.db) — source of truth
  YAML (JPM_MEMORY.yaml) — injection payload, rebuilt from DB

Entity extraction:
  Auto-extracts capitalized names, quoted terms, and "aka" patterns
  from knowledge content. Links facts to entities via join table.
  Enables probe(entity), related(entity), and reason(entities) queries.

MemoryProvider:
  Implements the MemoryProvider ABC so JPM can be set as the active
  memory backend via memory.provider: jpm in config.yaml.
  Provides the unified jpm() tool for all memory operations.
"""
from __future__ import annotations
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Re-export all core symbols ──────────────────────────────────────
from .core._paths import _get_joshaico_home, _get_yaml_path
from .core._parse import parse_kv
from .core._cache import _LRUCache, _get_cache, _CACHE
from .core._entities import _extract_entities
from .core._ensure import _ensure_db
from .core._search import _search_knowledge
from .core._read import _get_latest_pulse, _get_active, _get_open_loops, _get_knowledge
from .core._entity_query import _resolve_entity, _link_fact_entities, _probe_entity, _related_entities, _reason_entities
from .core._capabilities import _get_capabilities, _get_task_context
from .core._write import (
    _write_pulse, _set_active, _add_loop, _resolve_loop,
    _add_knowledge, _add_reflection, _track_tool_use,
    _set_task_context, _update_trust,
)
from .core._yaml import _build_yaml, _write_yaml
from .core._schemas import JPM_SCHEMA
from .core._handlers import _handle_jpm_update, _handle_jpm_fetch
# NOTE: jpm plugin hooks (pre_llm_call_callback, post_llm_call_callback,
# post_tool_call_callback, on_session_end_callback) were unwired — jpm is a
# baked-in memory provider, never registered as a plugin. Kept as comments for
# a potential OOB hook rebuild.
# from .core._hooks import pre_llm_call_callback, post_llm_call_callback, post_tool_call_callback, on_session_end_callback
# from .core._briefing import on_session_start_callback
from .core._register import create_provider

# ── Re-export MemoryProvider ────────────────────────────────────────
from .core._provider import JPMemoryProvider