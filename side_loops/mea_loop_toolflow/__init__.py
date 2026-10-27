"""mea_loop_toolflow — DEMOTED to cron maintenance (2026-10-21).

This plugin NO LONGER registers a ``post_llm_call`` hook. The summarizer is
non-LLM and cheap, but it rewrites the SAME rows micro-compaction already
collapsed — measured on a live session (519 messages): ``summarize_tool_flow``
returned ``collapsed: 0``. Running both is
not additive; they fight over the same rows. A cadence is the right shape.

Replacement: ``<HERMES_HOME>/scripts/mea_toolflow_cron.py`` (written, NOT
scheduled — this is a test instance; wire it to cron when the instance goes
live).

The vendored engine is unchanged and still lives at
``_mea_loops_core/vendor/tool_flow_summarizer.py``; the cron script imports it
directly and does not need this plugin loaded.

Config flag (profile ``config.yaml``), default ON (cheap, non-LLM)::

    plugins:
      entries:
        mea-loop-toolflow:
          settings:
            enabled: true

``register()`` is intentionally a no-op. Re-enabling this plugin in
``plugins.enabled`` will NOT resume per-turn firing — that is deliberate, so a
stale config cannot silently reintroduce the per-turn cost.
"""
from __future__ import annotations

import logging

LOG = logging.getLogger(__name__)

PLUGIN_ID = "mea-loop-toolflow"
LOOP_NAME = "toolflow"
DEMOTED_TO = "scripts/mea_toolflow_cron.py"


def register(ctx) -> None:
    """Stock plugin entry point — intentionally registers NOTHING.

    Demoted to cron. See module docstring.
    """
    LOG.info(
        "mea_loop_toolflow: demoted to cron (%s) — no post_llm_call hook registered",
        DEMOTED_TO,
    )
