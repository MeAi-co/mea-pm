"""mea_pm — MEAI Persistent Memory (memory provider plugin).

Thin wrapper that exposes the vendored ``jpm`` engine as a stock-Hermes
MemoryProvider. The engine lives untouched in ``./jpm/`` (vendored from the
Joshaico fork) so its 8 absolute ``from jpm.core...`` self-imports resolve.

Stock loader contract (plugins/memory/__init__.py):
  * discovery: this file must mention ``register_memory_provider`` or
    ``MemoryProvider`` in its first 8 KB (or define a MemoryProvider subclass).
  * load: the loader imports this package under a synthetic namespace and calls
    ``register(ctx)``; ``ctx.register_memory_provider(instance)`` captures the
    provider. No core modification required.

Activate with ``memory.provider: mea_pm`` in the profile's config.yaml.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the vendored engine importable as top-level ``jpm``. The loader imports
# THIS package under a synthetic name, so the engine's absolute ``jpm.*``
# self-imports need ``jpm`` resolvable on sys.path. Insert at position 0 so the
# vendored copy wins over any other ``jpm`` on the path.
_PLUGIN_DIR = Path(__file__).resolve().parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

from jpm.core._register import create_provider  # noqa: E402
from jpm.core._provider import JPMemoryProvider  # noqa: E402

__all__ = ["register", "JPMemoryProvider", "create_provider"]


def register(ctx) -> None:
    """Stock plugin entry point: hand the provider to the collector."""
    ctx.register_memory_provider(create_provider())
