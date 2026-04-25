from __future__ import annotations

import pytest

from pvpn_tui.proton_api import LocalAgentClient


def test_new_client_is_disconnected() -> None:
    c = LocalAgentClient()
    assert c.connected is False


async def test_request_port_forwarding_before_connect_raises() -> None:
    c = LocalAgentClient()
    with pytest.raises(RuntimeError, match="not connected"):
        await c.request_port_forwarding()


async def test_stop_is_idempotent_when_not_connected() -> None:
    c = LocalAgentClient()
    # Should be a no-op; no listener to cancel, no error to raise.
    await c.stop()
    assert c.connected is False
