from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, cast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Header, Static

if TYPE_CHECKING:
    from ..app import PvpnApp

from ..connection import Connection, ConnectionState
from ..proton_api import AuthService
from ..state import AppState
from ..widgets import HintBar
from .servers import ServerListScreen

log = logging.getLogger(__name__)


def _human_bytes(n: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    f = float(n)
    for u in units:
        if f < 1024 or u == units[-1]:
            return f"{f:,.1f} {u}" if u != "B" else f"{int(f)} B"
        f /= 1024
    return f"{f:.1f} TiB"


def _human_uptime(seconds: float) -> str:
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


_STATE_LABEL = {
    ConnectionState.CONNECTED: ("connected", "● Connected"),
    ConnectionState.DISCONNECTING: ("disconnecting", "◑ Disconnecting…"),
    ConnectionState.DISCONNECTED: ("disconnected", "○ Disconnected"),
}


class MainScreen(Screen[None]):
    CSS = """
    MainScreen {
        align: center middle;
    }

    #panel {
        width: 60;
        max-width: 90%;
        height: auto;
        padding: 1 2;
        border: round $primary;
    }

    .hidden { display: none; }

    #user {
        color: $text-muted;
        height: 1;
        margin-bottom: 1;
    }

    #state-line {
        text-style: bold;
        height: 1;
    }
    #state-line.connected     { color: $success; }
    #state-line.connecting    { color: $warning; }
    #state-line.disconnecting { color: $warning; }
    #state-line.disconnected  { color: $text-muted; }
    #state-line.error         { color: $error; }

    #server-line {
        text-style: bold;
        height: 1;
    }
    #endpoint {
        color: $text-muted;
        height: 1;
    }

    #port-card {
        border: round $success;
        height: auto;
        padding: 0 1;
        margin-top: 1;
    }
    #port-card.error   { border: round $error; }
    #port-card.pending { border: round $warning; }
    #port-label {
        height: 1;
        text-align: center;
        color: $success;
        text-style: bold;
    }
    #port-card.error   > #port-label { color: $error; }
    #port-card.pending > #port-label { color: $warning; }
    #port-value {
        height: 1;
        text-align: center;
        text-style: bold;
    }

    #stats {
        color: $text-muted;
        height: 1;
        margin-top: 1;
    }

    #last-hint {
        color: $text-muted;
        height: 1;
        margin-top: 1;
    }

    """

    BINDINGS = [
        Binding("f", "quick_connect('fastest')", "fastest"),
        Binding("r", "quick_connect('last')", "reconnect"),
        Binding("s", "servers", "servers"),
        Binding("d", "disconnect", "disconnect"),
        Binding("L", "logout", "logout"),
        Binding("q", "app.quit", "quit"),
    ]

    def __init__(self, auth: AuthService, connection: Connection) -> None:
        super().__init__()
        self._auth = auth
        self._connection = connection
        self._unsubscribe = lambda: None
        self._tick_timer = None

    def compose(self) -> ComposeResult:
        yield Header()
        user = self._auth.current_user
        with Vertical(id="panel"):
            yield Static(
                f"signed in as [b]{user.account_name}[/b]" if user else "signed in",
                id="user",
            )
            yield Static("", id="state-line")
            yield Static("", id="server-line", classes="hidden")
            yield Static("", id="endpoint", classes="hidden")
            with Vertical(id="port-card", classes="hidden"):
                yield Static("FORWARDED PORT", id="port-label")
                yield Static("—", id="port-value")
            yield Static("", id="stats", classes="hidden")
            yield Static("", id="last-hint", classes="hidden")
        yield HintBar()

    def on_mount(self) -> None:
        self._unsubscribe = self._connection.subscribe(self._on_state_change)
        self._tick_timer = self.set_interval(1.0, self._refresh_status)
        self._refresh_status()

    def on_unmount(self) -> None:
        self._unsubscribe()
        if self._tick_timer is not None:
            self._tick_timer.stop()

    def on_screen_resume(self) -> None:
        self._refresh_status()

    def _on_state_change(self, _: Connection) -> None:
        # Listener fires from the same asyncio loop Textual runs on.
        self._refresh_status()

    # ------------------------------------------------------------------ render

    def _refresh_status(self) -> None:
        state = self._connection.state
        active = self._connection.active

        # state line — for CONNECTING, include the target server name.
        sl_widget = self.query_one("#state-line", Static)
        if state is ConnectionState.CONNECTING:
            target = self._connection.target_name
            label = f"◐ Connecting to {target}…" if target else "◐ Connecting…"
            sl_widget.set_classes("state-line connecting")
            sl_widget.update(label)
        else:
            cls, label = _STATE_LABEL.get(
                state,
                ("disconnected", "○ Disconnected"),
            )
            sl_widget.set_classes(f"state-line {cls}")
            sl_widget.update(label)

        # server line — only when there's something useful
        server_w = self.query_one("#server-line", Static)
        ep_w = self.query_one("#endpoint", Static)
        if active is not None and state is ConnectionState.CONNECTED:
            country = active.exit_country or "?"
            server_w.update(f"{active.server_name} · {country}")
            server_w.remove_class("hidden")
            ep_w.update(active.endpoint)
            ep_w.remove_class("hidden")
        elif self._connection.link_present and state is ConnectionState.DISCONNECTED:
            server_w.update("[$warning]stale wg0 detected — press d to remove[/]")
            server_w.remove_class("hidden")
            ep_w.add_class("hidden")
        elif self._connection.last_error and state is ConnectionState.DISCONNECTED:
            server_w.update(f"[$error]{self._connection.last_error}[/]")
            server_w.remove_class("hidden")
            ep_w.add_class("hidden")
        else:
            server_w.add_class("hidden")
            ep_w.add_class("hidden")

        # forwarded port card — only while connected
        port_card = self.query_one("#port-card")
        port_value = self.query_one("#port-value", Static)
        port_label = self.query_one("#port-label", Static)
        if active is None or state is not ConnectionState.CONNECTED:
            port_card.set_classes("hidden")
        elif active.forwarded_port is not None:
            port_card.set_classes("")
            port_label.update("FORWARDED PORT")
            port_value.update(f"[b]{active.forwarded_port}[/]")
        elif active.agent_error:
            port_card.set_classes("error")
            port_label.update("AGENT ERROR")
            port_value.update(active.agent_error)
        else:
            port_card.set_classes("pending")
            port_label.update("FORWARDED PORT")
            port_value.update("[dim]waiting…[/]")

        # stats + uptime — only while connected
        stats_w = self.query_one("#stats", Static)
        if active and state is ConnectionState.CONNECTED:
            parts: list[str] = []
            if active.connected_at > 0:
                parts.append(f"up {_human_uptime(time.time() - active.connected_at)}")
            if active.stats and (active.stats.rx_bytes or active.stats.tx_bytes):
                parts.append(f"↓ {_human_bytes(active.stats.rx_bytes)}")
                parts.append(f"↑ {_human_bytes(active.stats.tx_bytes)}")
            if parts:
                stats_w.remove_class("hidden")
                stats_w.update("   ".join(parts))
            else:
                stats_w.add_class("hidden")
        else:
            stats_w.add_class("hidden")

        # last-server hint (only when fully idle and we know one)
        last_w = self.query_one("#last-hint", Static)
        last_id = AppState.load().last_server_id
        show_last = last_id is not None and state is ConnectionState.DISCONNECTED
        if show_last:
            sl_obj = self._auth.server_list
            name = None
            if sl_obj is not None:
                try:
                    name = sl_obj.get_by_id(last_id).name  # type: ignore[arg-type]
                except Exception:
                    name = None
            if name:
                last_w.remove_class("hidden")
                last_w.update(f"last: [b]{name}[/]  ·  press [b]r[/] to reconnect")
            else:
                last_w.add_class("hidden")
        else:
            last_w.add_class("hidden")

    # ----------------------------------------------------------------- actions

    def action_servers(self) -> None:
        self.app.push_screen(ServerListScreen(self._auth, self._connection))

    def action_quick_connect(self, selector: str) -> None:
        # Show feedback in the state line until the connect dispatches.
        sl_widget = self.query_one("#state-line", Static)
        sl_widget.set_classes("state-line connecting")
        sl_widget.update(f"◐ resolving {selector}…")
        asyncio.create_task(self._do_quick_connect(selector), name=f"qc:{selector}")

    async def _do_quick_connect(self, selector: str) -> None:
        app = cast("PvpnApp", self.app)
        ok, msg = await app.connect_by_selector(selector)
        if not ok:
            sl_widget = self.query_one("#state-line", Static)
            sl_widget.set_classes("state-line error")
            sl_widget.update(f"x quick-connect failed: {msg}")

    def action_disconnect(self) -> None:
        try:
            self._connection.start_disconnect()
        except RuntimeError as exc:
            sl_widget = self.query_one("#state-line", Static)
            sl_widget.set_classes("state-line error")
            sl_widget.update(f"x {exc}")

    def action_logout(self) -> None:
        # Long-running logout owned by the app, not this screen.
        asyncio.create_task(self._do_logout(), name="logout")

    async def _do_logout(self) -> None:
        # Logout implies the user is done — drop the tunnel first.
        if self._connection.link_present or self._connection.active is not None:
            try:
                await self._connection.start_disconnect()
            except Exception:
                log.exception("logout: disconnect failed (continuing)")
        try:
            await self._auth.logout()
        except Exception:
            log.exception("logout: auth.logout failed (continuing)")
        self.app.exit()
