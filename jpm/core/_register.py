import sys
import logging
from pathlib import Path

from ._provider import JPMemoryProvider
from ._schemas import JPM_SCHEMA
from ._handlers import _handle_jpm_update, _handle_jpm_fetch

LOG = logging.getLogger(__name__)


def create_provider() -> JPMemoryProvider:
    """Create and return a new JPMemoryProvider instance.
    
    Joshaico calls this directly instead of relying on JOSHAICO plugin
    discovery.  The returned provider is registered with the agent's
    MemoryManager during initialization.
    """
    provider = JPMemoryProvider()
    LOG.info("jpm: provider created for joshaico")
    return provider