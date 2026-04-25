import asyncio
import logging

from textual.app import App
from textual.binding import Binding

from .connection import Connection
from .proton_api import AuthService
from .resolver import resolve as resolve_server
from .screens.login import LoginScreen
from .screens.main import MainScreen
from .state import AppState

log = logging.getLogger(__name__)


class PvpnApp(App[None]):
    TITLE = "pvpn-tui"
    SUB_TITLE = "Proton VPN, without the NetworkManager rodeo"

    # Use the terminal's own ANSI palette so we inherit whatever
    # light/dark theme the user has set system-wide. Textual's auto
    # detect-the-bg-via-OSC-11 doesn't fire reliably on every terminal.
    DEFAULT_THEME = "textual-ansi"

    # Suppress the built-in `^p palette` and other framework defaults
    # so the Footer only shows our actual key bindings.
    ENABLE_COMMAND_PALETTE = False

    # Textual's stock Footer/Header force theme-tinted backgrounds even
    # under textual-ansi (with magenta key letters). Strip them down to
    # plain terminal-default — see HintBar widget below for the custom
    # key hint footer.
    CSS = """
    Header, HeaderIcon, HeaderTitle, HeaderClockSpace {
        background: transparent;
        color: auto;
    }
    HintBar {
        dock: bottom;
        height: 1;
        background: transparent;
        color: $text-muted;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
        Binding("ctrl+q", "quit", "Quit", show=False),
    ]

    def __init__(
        self,
        connect_selector: str | None = None,
        theme: str | None = None,
    ) -> None:
        super().__init__()
        self.auth = AuthService()
        self.connection = Connection(self.auth)
        self._connect_selector = connect_selector
        self._initial_theme = theme or self.DEFAULT_THEME

    def on_mount(self) -> None:
        try:
            self.theme = self._initial_theme
        except Exception:
            log.exception("failed to apply theme %r", self._initial_theme)
        if self.auth.restore_default_session():
            log.debug("startup: pushing MainScreen (session restored)")
            self.push_screen(MainScreen(self.auth, self.connection))
            # If wg0 is still up from a prior run, resume tracking it.
            if self.connection.attach_existing():
                log.debug("startup: attached to existing wg0")
            if self._connect_selector:
                asyncio.create_task(
                    self._auto_connect(self._connect_selector),
                    name="auto-connect",
                )
        else:
            log.debug("startup: pushing LoginScreen")
            self.push_screen(LoginScreen(self.auth), self._on_login_done)

    def _on_login_done(self, _: object) -> None:
        log.debug("login complete: pushing MainScreen")
        self.push_screen(MainScreen(self.auth, self.connection))
        if self._connect_selector:
            asyncio.create_task(
                self._auto_connect(self._connect_selector),
                name="auto-connect",
            )

    async def _auto_connect(self, selector: str) -> None:
        await self.connect_by_selector(selector)

    async def connect_by_selector(self, selector: str) -> tuple[bool, str]:
        """Resolve a selector and kick off ``Connection.start_connect``.

        Returns ``(ok, message)``. ``message`` is human-readable: server
        name on success, or the reason we couldn't dispatch.
        """
        log.info("connect_by_selector: %r", selector)
        try:
            sl = await self.auth.ensure_session_data()
        except Exception as exc:
            log.exception("connect_by_selector: ensure_session_data failed")
            return False, f"session fetch failed: {exc}"
        if sl is None:
            return False, "no server list"
        state = AppState.load()
        server = resolve_server(selector, sl, last_server_id=state.last_server_id)
        if server is None:
            return False, f"no match for {selector!r}"
        log.info(
            "connect_by_selector: %r -> %s (%s)",
            selector,
            server.name,
            server.exit_country,
        )
        try:
            self.connection.start_connect(server)
        except RuntimeError as exc:
            return False, str(exc)
        return True, server.name or server.id

    async def on_unmount(self) -> None:
        log.debug("app on_unmount: connection.shutdown()")
        await self.connection.shutdown()


def main() -> None:
    PvpnApp().run()


if __name__ == "__main__":
    main()
