"""mea_loop_digest — DEMOTED to cron maintenance (2026-10-21).

This plugin NO LONGER registers a ``post_llm_call`` hook. The digest is an
LLM-based in-place row compressor; running it at every turn end burned aux-LLM
calls for no per-turn benefit, and it rewrites the same rows micro-compaction
already collapsed. It is pure DB maintenance, so a cadence is the right shape.

Replacement: ``<HERMES_HOME>/scripts/mea_digest_cron.py`` (written, NOT scheduled
— this is a test instance; wire it to cron when the instance goes live).

The vendored engine is unchanged and still lives at
``_mea_loops_core/vendor/agent_digest.py``; the cron script imports it directly
and does not need this plugin loaded.

Config flag (profile ``config.yaml``), default OFF::

    plugins:
      entries:
        mea-loop-digest:
          settings:
            enabled: false

``register()`` is intentionally a no-op. Re-enabling this plugin in
``plugins.enabled`` will NOT resume per-turn firing — that is deliberate, so a
stale config cannot silently reintroduce the per-turn cost.
"""
from __future__ import annotations

import logging

LOG = logging.getLogger(__name__)

PLUGIN_ID = "mea-loop-digest"
LOOP_NAME = "agent_digest"
DEMOTED_TO = "scripts/mea_digest_cron.py"


def register(ctx) -> None:
    """Stock plugin entry point — intentionally registers NOTHING.

    Demoted to cron. See module docstring.
    """
    LOG.info(
        "mea_loop_digest: demoted to cron (%s) — no post_llm_call hook registered",
        DEMOTED_TO,
    )
