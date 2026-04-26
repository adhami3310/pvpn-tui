from __future__ import annotations

import asyncio
from dataclasses import dataclass

from textual.app import App
from textual.widgets import Static

from pvpn_tui.connection import (
    ActiveConnection,
    Connection,
    ConnectionState,
)
from pvpn_tui.screens.main import MainScreen
from pvpn_tui.widgets import HintBar


@dataclass
class _LoggedInAuth:
    """Pose as an AuthService that's signed in."""

    @property
    def current_user(self):
        from pvpn_tui.proton_api import LoggedInUser

        return LoggedInUser(account_name="alice@example.com")

    @property
    def server_list(self):
        return None

    @property
    def wg_credentials(self):
        return None

    async def ensure_fresh_cert(self) -> None:
        return None


class _Host(App):
    def __init__(self, auth, connection: Connection) -> None:
        super().__init__()
        self._auth = auth
        self._connection = connection

    def on_mount(self) -> None:
        self.push_screen(MainScreen(self._auth, self._connection))


async def test_main_screen_shows_disconnected_initially() -> None:
    auth = _LoggedInAuth()
    conn = Connection(auth)
    async with _Host(auth, conn).run_test() as pilot:
        await pilot.pause()
        scr = pilot.app.screen
        assert isinstance(scr, MainScreen)

        state_line = scr.query_one("#state-line", Static)
        assert "Disconnected" in str(state_line.render())

        # Hint bar mounted.
        scr.query_one(HintBar)


async def test_main_screen_shows_user_email() -> None:
    auth = _LoggedInAuth()
    async with _Host(auth, Connection(auth)).run_test() as pilot:
        await pilot.pause()
        user_line = pilot.app.screen.query_one("#user", Static)
        assert "alice@example.com" in str(user_line.render())


async def test_main_screen_renders_connected_state() -> None:
    auth = _LoggedInAuth()
    conn = Connection(auth)
    async with _Host(auth, conn).run_test() as pilot:
        await pilot.pause()
        # Inject a connected state directly — skip the wg_up / agent paths.
        active = ActiveConnection(
            server_id="srv-1",
            server_name="US-CA#42",
            endpoint="1.2.3.4:51820",
            exit_country="US",
            forwarded_port=42424,
            connected_at=0.0,
        )
        conn._set(ConnectionState.CONNECTED, active=active, error=None)
        await pilot.pause()
        scr = pilot.app.screen

        assert "Connected" in str(scr.query_one("#state-line").render())
        assert "US-CA#42" in str(scr.query_one("#server-line").render())
        assert "1.2.3.4:51820" in str(scr.query_one("#endpoint").render())
        assert "42424" in str(scr.query_one("#port-value").render())


async def test_disconnect_binding_calls_start_disconnect() -> None:
    auth = _LoggedInAuth()
    conn = Connection(auth)
    called = asyncio.Event()

    def fake_start_disconnect():
        called.set()

        # Return a completed task so the type contract holds.
        async def _noop():
            return None

        return asyncio.ensure_future(_noop())

    conn.start_disconnect = fake_start_disconnect  # type: ignore[method-assign]

    async with _Host(auth, conn).run_test() as pilot:
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
        assert called.is_set()
