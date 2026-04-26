from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from textual.app import App
from textual.widgets import DataTable, Input, Label

from pvpn_tui.connection import Connection
from pvpn_tui.proton_api import ServerFeature
from pvpn_tui.screens.servers import DISPLAY_LIMIT, ServerListScreen
from pvpn_tui.widgets import HintBar

# ---- minimal proton-shaped fakes ----------------------------------------


@dataclass
class FakePhysical:
    enabled: bool = True
    x25519_pk: str = "peer-pubkey"
    entry_ip: str = "1.2.3.4"
    domain: str = "node-x.protonvpn.net"


@dataclass
class FakeLogical:
    id: str
    name: str
    exit_country: str = "US"
    exit_country_name: str = "United States"
    city: str = "San Francisco"
    load: int = 30
    score: float = 1.5
    features: tuple = (ServerFeature.P2P,)
    enabled: bool = True
    under_maintenance: bool = False
    tier: int = 0
    physical_servers: tuple = (FakePhysical(),)


class FakeServerList:
    LOADS_REFRESH_INTERVAL = 900

    def __init__(self, logicals: list[FakeLogical], user_tier: int = 2) -> None:
        self.logicals = logicals
        self.user_tier = user_tier
        self.loads_expired = False

    def get_by_id(self, sid: str) -> FakeLogical:
        for s in self.logicals:
            if s.id == sid:
                return s
        raise LookupError(sid)


class FakeAuth:
    def __init__(self, sl: FakeServerList) -> None:
        self._sl = sl

    @property
    def server_list(self) -> FakeServerList:
        return self._sl

    @property
    def user_tier(self) -> int:
        return self._sl.user_tier

    @property
    def wg_credentials(self) -> Any:
        return None

    async def ensure_session_data(self) -> FakeServerList:
        return self._sl

    async def refresh_server_loads(self) -> FakeServerList:
        return self._sl

    async def ensure_fresh_cert(self) -> None:
        return None


class _Host(App):
    def __init__(self, auth: FakeAuth, connection: Connection) -> None:
        super().__init__()
        self._auth = auth
        self._connection = connection

    def on_mount(self) -> None:
        self.push_screen(ServerListScreen(self._auth, self._connection))


@pytest.fixture
def host():
    logicals = [
        FakeLogical(id=f"id-{i}", name=f"US#{i}", load=10 + i) for i in range(20)
    ] + [
        FakeLogical(
            id="jp-1",
            name="JP#1",
            exit_country="JP",
            exit_country_name="Japan",
            city="Tokyo",
            load=5,
        ),
    ]
    sl = FakeServerList(logicals)
    auth = FakeAuth(sl)
    return _Host(auth, Connection(auth))


# ---- tests ---------------------------------------------------------------


async def test_servers_screen_mounts_with_columns(host: _Host) -> None:
    async with host.run_test() as pilot:
        await pilot.pause()
        scr = pilot.app.screen
        assert isinstance(scr, ServerListScreen)

        table = scr.query_one(DataTable)
        # Column headers wired up.
        labels = [str(c.label) for c in table.columns.values()]
        assert any("Country" in lbl for lbl in labels)
        assert any("Load" in lbl for lbl in labels)

        # Search input + status bar + hint bar.
        scr.query_one("#search", Input)
        scr.query_one("#status-bar", Label)
        scr.query_one(HintBar)


async def test_servers_screen_loads_rows(host: _Host) -> None:
    async with host.run_test() as pilot:
        await pilot.pause()
        scr = pilot.app.screen
        assert isinstance(scr, ServerListScreen)
        # Wait for the worker to finish loading.
        for _ in range(40):
            await pilot.pause(0.05)
            if scr._rows:
                break
        assert len(scr._rows) == 21  # all 20 US + 1 JP


async def test_servers_screen_caps_visible_rows(host: _Host) -> None:
    async with host.run_test() as pilot:
        await pilot.pause()
        scr = pilot.app.screen
        assert isinstance(scr, ServerListScreen)
        for _ in range(40):
            await pilot.pause(0.05)
            if scr._rows:
                break
        table = scr.query_one(DataTable)
        # Pool is small (21) so cap doesn't kick in here, but the cap
        # constant is the right shape — assert the contract.
        assert table.row_count <= DISPLAY_LIMIT
        assert table.row_count == len(scr._rows)


async def test_servers_screen_filter_narrows_rows(host: _Host) -> None:
    async with host.run_test() as pilot:
        await pilot.pause()
        scr = pilot.app.screen
        assert isinstance(scr, ServerListScreen)
        for _ in range(40):
            await pilot.pause(0.05)
            if scr._rows:
                break
        scr.query_one("#search", Input).value = "japan"
        # debounce window
        await pilot.pause(0.2)
        table = scr.query_one(DataTable)
        assert table.row_count == 1


async def test_servers_screen_sort_indicator_updates(host: _Host) -> None:
    async with host.run_test() as pilot:
        await pilot.pause()
        scr = pilot.app.screen
        assert isinstance(scr, ServerListScreen)
        for _ in range(40):
            await pilot.pause(0.05)
            if scr._rows:
                break
        scr.action_sort("load")
        await pilot.pause()
        table = scr.query_one(DataTable)
        labels = [str(c.label) for c in table.columns.values()]
        assert any("↑" in lbl and "Load" in lbl for lbl in labels)


async def test_servers_screen_escape_dismisses_when_table_focused(
    host: _Host,
) -> None:
    async with host.run_test() as pilot:
        await pilot.pause()
        scr = pilot.app.screen
        assert isinstance(scr, ServerListScreen)
        for _ in range(40):
            await pilot.pause(0.05)
            if scr._rows:
                break
        # Move focus to table (filter is auto-focused).
        scr.query_one(DataTable).focus()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        # Screen has popped — host's default screen returns.
        assert not isinstance(pilot.app.screen, ServerListScreen)
