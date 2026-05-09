"""SessionManager calls registry hooks at the right lifecycle moments."""
from unittest.mock import AsyncMock

import pytest


class _FakeRegistry:
    """Minimal stand-in for GoProDeviceRegistry used to verify SessionManager
    delegation. We don't construct a real registry because lifecycle.py is
    deeply tied to the rest of the recording stack; the test focuses on
    delegation only."""
    def __init__(self):
        self.episode_start = AsyncMock()
        self.episode_stop = AsyncMock()
        self.commit_episode = AsyncMock()
        self.discard_episode = AsyncMock()
        self.stop = AsyncMock()


@pytest.mark.asyncio
async def test_session_manager_passes_registry_through_to_hooks():
    """SessionManager constructor accepts gopro_registry and forwards
    episode_start / episode_stop / episode_save / episode_discard /
    end (or equivalent shutdown path) to it.

    NOTE: this is a wiring test — the implementing subagent should locate
    the actual SessionManager initializer in
    backend/mimicrec/session/lifecycle.py and the relevant lifecycle
    methods. Replace this stub with the right call sequence for the
    repo's existing test harness."""
    pytest.skip(
        "Implement against the actual SessionManager test harness "
        "after wiring gopro_registry through. This stub documents intent."
    )
