"""Vendored engine modules for the MEAI per-loop plugins.

These modules have no stock equivalent, so the per-loop subprocesses cannot
import them from the stock tree. They are vendored here ONCE and imported as
``_mea_loops_core.vendor.<module>``.

Vendored:
  * ``agent_digest`` — agent-message digest compressor (DB-only, detachable).

Re-vendor when the upstream module changes materially. Each vendored module must
import ONLY stock modules (``agent.auxiliary_client``) + the vendored engine
(``jpm.*``) — never another fork-core module.
"""
