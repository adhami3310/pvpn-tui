from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from pvpn_tui.connection import (
    ActiveConnection,
    Connection,
    ConnectionState,
)
from pvpn_tui.proton_api import WGCredentials

# ---- fakes ---------------------------------------------------------------


@dataclass
class FakePhysical:
    enabled: bool = True
    x25519_pk: str = "peer-pubkey-base64"
    entry_ip: str = "1.2.3.4"
    domain: str = "node-x.protonvpn.net"


@dataclass
class FakeServer:
    id: str = "srv-1"
    name: str = "US-CA#1"
    exit_country: str = "US"
    physical_servers: tuple = (FakePhysical(),)


class FakeAuth:
    """Stand-in for AuthService with the surface Connection needs."""

    def __init__(self) -> None:
        self.cert_refresh_called = 0
        self._creds = WGCredentials(
            wg_private_key="our-wg-priv",
            ed25519_sk_pem="-----BEGIN PRIVATE KEY-----\n",
            certificate_pem="-----BEGIN CERTIFICATE-----\n",
            validity_remaining_s=7 * 24 * 3600,
        )

    @property
    def wg_credentials(self) -> WGCredentials:
        return self._creds

    @property
    def server_list(self) -> Any:
        return None

    async def ensure_fresh_cert(self) -> None:
        self.cert_refresh_called += 1


@pytest.fixture
def auth() -> FakeAuth:
    return FakeAuth()


@pytest.fixture(autouse=True)
def stub_wg_and_agent(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Replace subprocess-touching helpers with in-memory equivalents."""
    captured: dict = {"up_calls": [], "down_calls": [], "link": False}

    async def fake_up(cfg) -> None:
        captured["up_calls"].append(cfg)
        captured["link"] = True

    async def fake_down(iface: str = "wg0") -> None:
        captured["down_calls"].append(iface)
        captured["link"] = False

    def fake_link_exists(iface: str = "wg0") -> bool:
        return captured["link"]

    def fake_read_stats(iface: str = "wg0"):
        return None

    import pvpn_tui.connection as cm

    monkeypatch.setattr(cm, "wg_up", fake_up)
    monkeypatch.setattr(cm, "wg_down", fake_down)
    monkeypatch.setattr(cm, "link_exists", fake_link_exists)
    monkeypatch.setattr(cm, "read_stats", fake_read_stats)

    # Skip the local-agent connection entirely in unit tests.
    async def fake_start_agent(self, domain: str) -> None:
        return None

    monkeypatch.setattr(Connection, "_start_agent", fake_start_agent)

    # Don't touch state.json from unit tests.
    monkeypatch.setattr(
        cm.AppState,
        "load",
        classmethod(lambda cls: cls()),
    )
    monkeypatch.setattr(cm.AppState, "save", lambda self: None)

    return captured


# ---- initial state -------------------------------------------------------


def test_initial_state_is_disconnected(auth: FakeAuth) -> None:
    c = Connection(auth)
    assert c.state is ConnectionState.DISCONNECTED
    assert c.active is None
    assert c.last_error is None
    assert c.target_name is None
    assert c.is_busy is False


# ---- subscribe/emit ------------------------------------------------------


def test_subscribe_returns_unsubscribe_callable(auth: FakeAuth) -> None:
    c = Connection(auth)
    seen: list[str] = []
    unsub = c.subscribe(lambda conn: seen.append(conn.state.value))

    c._set(ConnectionState.CONNECTING)
    assert seen == ["connecting"]

    unsub()
    c._set(ConnectionState.DISCONNECTED)
    # Listener removed; should not have fired again.
    assert seen == ["connecting"]


def test_double_unsubscribe_is_safe(auth: FakeAuth) -> None:
    c = Connection(auth)
    unsub = c.subscribe(lambda _conn: None)
    unsub()
    # Second call must not raise.
    unsub()


def test_listener_exception_does_not_break_emit(auth: FakeAuth) -> None:
    c = Connection(auth)
    seen: list[str] = []

    def boom(_conn: Connection) -> None:
        raise RuntimeError("listener bug")

    c.subscribe(boom)
    c.subscribe(lambda conn: seen.append(conn.state.value))
    c._set(ConnectionState.CONNECTING)

    # The good listener still fires even though the first one raised.
    assert seen == ["connecting"]


# ---- connect / disconnect happy path -------------------------------------


async def test_connect_runs_through_states_and_calls_wg_up(
    auth: FakeAuth,
    stub_wg_and_agent: dict,
) -> None:
    c = Connection(auth)
    seen: list[str] = []
    c.subscribe(lambda conn: seen.append(conn.state.value))

    server = FakeServer()
    task = c.start_connect(server)
    await task

    assert c.state is ConnectionState.CONNECTED
    assert c.active is not None
    assert c.active.server_name == "US-CA#1"
    assert c.active.endpoint == "1.2.3.4:51820"
    assert c.active.exit_country == "US"
    assert c.active.connected_at > 0
    assert "connecting" in seen and "connected" in seen
    assert auth.cert_refresh_called == 1
    assert len(stub_wg_and_agent["up_calls"]) == 1


async def test_disconnect_runs_wg_down(
    auth: FakeAuth,
    stub_wg_and_agent: dict,
) -> None:
    c = Connection(auth)
    await c.start_connect(FakeServer())
    await c.start_disconnect()

    assert c.state is ConnectionState.DISCONNECTED
    assert c.active is None
    assert stub_wg_and_agent["down_calls"] == ["wg0"]


async def test_start_connect_while_busy_raises(
    auth: FakeAuth,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Stretch the wg_up call so the first connect remains in flight.
    async def slow_up(cfg) -> None:
        await asyncio.sleep(0.5)

    import pvpn_tui.connection as cm

    monkeypatch.setattr(cm, "wg_up", slow_up)

    c = Connection(auth)
    c.start_connect(FakeServer())
    await asyncio.sleep(0)  # let the task start
    with pytest.raises(RuntimeError, match="busy"):
        c.start_connect(FakeServer())


async def test_disconnect_cancels_in_flight_connect(
    auth: FakeAuth,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    cancelled = False

    async def slow_up(cfg) -> None:
        started.set()
        nonlocal cancelled
        try:
            await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            cancelled = True
            raise

    import pvpn_tui.connection as cm

    monkeypatch.setattr(cm, "wg_up", slow_up)

    c = Connection(auth)
    connect_task = c.start_connect(FakeServer())
    await started.wait()

    disc_task = c.start_disconnect()
    with pytest.raises(asyncio.CancelledError):
        await connect_task
    await disc_task

    assert cancelled
    assert c.state is ConnectionState.DISCONNECTED


async def test_connect_reports_error_when_no_physicals(auth: FakeAuth) -> None:
    server = FakeServer(physical_servers=())
    c = Connection(auth)
    with pytest.raises(RuntimeError, match="no physical servers"):
        await c.start_connect(server)
    assert c.state is ConnectionState.DISCONNECTED


async def test_connect_skips_disabled_physicals(auth: FakeAuth) -> None:
    server = FakeServer(
        physical_servers=(
            FakePhysical(enabled=False, entry_ip="9.9.9.9"),
            FakePhysical(enabled=True, entry_ip="1.1.1.1"),
        ),
    )
    c = Connection(auth)
    await c.start_connect(server)
    assert c.active is not None
    assert c.active.endpoint.startswith("1.1.1.1")


# ---- shutdown preserves the tunnel ---------------------------------------


async def test_shutdown_does_not_call_wg_down(
    auth: FakeAuth,
    stub_wg_and_agent: dict,
) -> None:
    c = Connection(auth)
    await c.start_connect(FakeServer())
    assert stub_wg_and_agent["link"] is True

    await c.shutdown()
    # shutdown() must NOT teardown wg0 — that's the explicit-disconnect path.
    assert stub_wg_and_agent["down_calls"] == []
    assert stub_wg_and_agent["link"] is True


# ---- ActiveConnection ----------------------------------------------------


def test_active_connection_defaults() -> None:
    ac = ActiveConnection(
        server_id="x",
        server_name="X#1",
        endpoint="1.2.3.4:51820",
        exit_country="US",
    )
    assert ac.forwarded_port is None
    assert ac.agent_state is None
    assert ac.agent_error is None
    assert ac.stats is None
    assert ac.connected_at == 0.0
