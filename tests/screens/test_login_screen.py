from __future__ import annotations

from textual.app import App
from textual.widgets import Button, Input

from pvpn_tui.proton_api.auth import AuthService
from pvpn_tui.screens.login import LoginScreen
from pvpn_tui.widgets import HintBar


class _Host(App):
    def __init__(self, auth: AuthService) -> None:
        super().__init__()
        self._auth = auth

    def on_mount(self) -> None:
        self.push_screen(LoginScreen(self._auth))


async def test_login_screen_mounts_with_inputs_and_button() -> None:
    auth = AuthService()
    async with _Host(auth).run_test() as pilot:
        await pilot.pause()
        scr = pilot.app.screen
        assert isinstance(scr, LoginScreen)
        ids = {w.id for w in scr.query(Input)}
        assert {"username", "password", "twofa"} <= ids
        # Submit button present.
        scr.query_one("#submit", Button)
        # HintBar (custom Footer) is mounted.
        scr.query_one(HintBar)


async def test_login_screen_focuses_username_on_mount() -> None:
    auth = AuthService()
    async with _Host(auth).run_test() as pilot:
        await pilot.pause()
        focused = pilot.app.focused
        assert isinstance(focused, Input)
        assert focused.id == "username"


async def test_login_screen_twofa_starts_disabled() -> None:
    auth = AuthService()
    async with _Host(auth).run_test() as pilot:
        await pilot.pause()
        scr = pilot.app.screen
        twofa = scr.query_one("#twofa", Input)
        assert twofa.disabled is True


async def test_login_screen_shows_error_when_fields_blank() -> None:
    auth = AuthService()
    async with _Host(auth).run_test() as pilot:
        await pilot.pause()
        scr = pilot.app.screen
        # Trigger submit without typing — should show an error in the
        # status label, not crash.
        scr.query_one("#submit", Button).press()
        await pilot.pause()
        status = scr.query_one("#login-status")
        assert "required" in str(status.render()).lower()
