"""jpm core — shared modules used by all agents."""
from ._paths import _get_agent_home, _get_yaml_path
from ._parse import parse_kv
from ._cache import _LRUCache, _get_cache, _CACHE
from ._entities import _extract_entities
from ._ensure import _ensure_db
from ._search import _search_knowledge
from ._read import _get_latest_pulse, _get_active, _get_open_loops, _get_knowledge
from ._entity_query import _resolve_entity, _link_fact_entities, _probe_entity, _related_entities, _reason_entities
from ._capabilities import _get_capabilities, _get_task_context
from ._write import (_write_pulse, _set_active, _add_loop, _resolve_loop,
                     _add_knowledge, _add_reflection, _track_tool_use,
                     _set_task_context, _update_trust)
from ._yaml import _build_yaml, _write_yaml
from ._provider import JPMemoryProvider
from ._schemas import JPM_SCHEMA
from ._handlers import _handle_jpm_update, _handle_jpm_fetch
# NOTE: jpm plugin hooks unwired — jpm is a baked-in memory provider, not a
# plugin. Hook callbacks never registered/dispatched.
# from ._hooks import pre_llm_call_callback, post_llm_call_callback, post_tool_call_callback, on_session_end_callback
from ._register import create_provider