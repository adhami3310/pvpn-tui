from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Button, Header, Input, Label, Static

from ..proton_api import AuthService
from ..widgets import HintBar


class LoginScreen(Screen[None]):
    CSS = """
    #login-card {
        width: 56;
        height: auto;
        padding: 1 2;
        border: round $primary;
    }
    #login-title { text-style: bold; padding-bottom: 1; }
    #login-status { color: $error; padding-top: 1; min-height: 1; }
    #login-buttons { padding-top: 1; height: auto; }
    Input { margin-bottom: 1; }
    """

    BINDINGS = [
        Binding("escape", "app.quit", "Quit"),
    ]

    def __init__(self, auth: AuthService) -> None:
        super().__init__()
        self._auth = auth
        self._twofa_pending = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Center(), Vertical(id="login-card"):
            yield Static("Sign in to Proton VPN", id="login-title")
            yield Input(placeholder="username or email", id="username")
            yield Input(placeholder="password", password=True, id="password")
            yield Input(
                placeholder="2FA code",
                id="twofa",
                disabled=True,
                max_length=8,
            )
            yield Label("", id="login-status")
            with Center(id="login-buttons"):
                yield Button("Sign in", id="submit", variant="primary")
        yield HintBar()

    def on_mount(self) -> None:
        self.query_one("#username", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit":
            self._submit()

    def _submit(self) -> None:
        if self._twofa_pending:
            code = self.query_one("#twofa", Input).value.strip()
            if not code:
                self._set_status("Enter your 2FA code.")
                return
            self.run_worker(self._do_2fa(code), exclusive=True, group="auth")
            return

        username = self.query_one("#username", Input).value.strip()
        password = self.query_one("#password", Input).value
        if not username or not password:
            self._set_status("Username and password are required.")
            return
        self.run_worker(
            self._do_login(username, password),
            exclusive=True,
            group="auth",
        )

    async def _do_login(self, username: str, password: str) -> None:
        self._set_busy("Signing in…")
        try:
            result = await self._auth.login(username, password)
        except Exception as exc:
            self._set_status(f"Login failed: {exc}")
            self._set_form_disabled(False)
            return

        if result.twofa_required:
            self._twofa_pending = True
            self._set_status("Enter your 2FA code.", error=False)
            self._set_form_disabled(False)
            twofa = self.query_one("#twofa", Input)
            twofa.disabled = False
            twofa.focus()
            return

        if result.success and result.authenticated:
            self.dismiss()
            return

        self._set_status("Invalid username or password.")
        self._set_form_disabled(False)

    async def _do_2fa(self, code: str) -> None:
        self._set_busy("Verifying code…")
        try:
            result = await self._auth.provide_2fa(code)
        except Exception as exc:
            self._set_status(f"2FA failed: {exc}")
            self._set_form_disabled(False)
            return

        if result.success and result.authenticated:
            self.dismiss()
            return

        self._set_status("Invalid 2FA code.")
        self._set_form_disabled(False)
        self.query_one("#twofa", Input).value = ""

    def _set_status(self, msg: str, *, error: bool = True) -> None:
        label = self.query_one("#login-status", Label)
        label.update(msg)
        label.styles.color = "red" if error else "white"

    def _set_busy(self, msg: str) -> None:
        self._set_status(msg, error=False)
        self._set_form_disabled(True)

    def _set_form_disabled(self, disabled: bool) -> None:
        for ident in ("username", "password", "submit"):
            self.query_one(f"#{ident}").disabled = disabled
        if self._twofa_pending:
            self.query_one("#twofa", Input).disabled = disabled
