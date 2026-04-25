from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import DataTable, Header, Input, Label

from ..connection import Connection
from ..proton_api import AuthService, LogicalServer, ServerFeature
from ..widgets import HintBar

log = logging.getLogger(__name__)

# DataTable cost is dominated by add_row; keep the visible window small.
DISPLAY_LIMIT = 250
# How long after the last keystroke we redraw, in seconds.
FILTER_DEBOUNCE = 0.05


class SortKey(Enum):
    COUNTRY = "country"
    LOAD = "load"
    SCORE = "score"
    NAME = "name"


@dataclass(frozen=True)
class ServerRow:
    server_id: str
    country: str
    city: str
    name: str
    load: int
    score: float
    features: tuple[ServerFeature, ...]

    @property
    def features_str(self) -> str:
        if not self.features:
            return ""
        symbols = {
            ServerFeature.SECURE_CORE: "SC",
            ServerFeature.TOR: "Tor",
            ServerFeature.P2P: "P2P",
            ServerFeature.STREAMING: "Stream",
        }
        return " ".join(symbols.get(f, "") for f in self.features if f in symbols).strip()


def _build_rows(
    logicals: list[LogicalServer],
    user_tier: int,
) -> list[ServerRow]:
    rows: list[ServerRow] = []
    for s in logicals:
        if not s.enabled or s.under_maintenance:
            continue
        if s.tier > user_tier:
            continue
        rows.append(
            ServerRow(
                server_id=s.id,
                country=s.exit_country_name or s.exit_country or "?",
                city=s.city or "",
                name=s.name or "",
                load=int(s.load or 0),
                score=float(s.score or 0.0),
                features=tuple(s.features or ()),
            )
        )
    return rows


def _matches(row: ServerRow, needle: str) -> bool:
    if not needle:
        return True
    return (
        needle in row.country.lower()
        or needle in row.city.lower()
        or needle in row.name.lower()
    )


def _sort_keyfn(key: SortKey):
    if key is SortKey.COUNTRY:
        return lambda r: (r.country.lower(), r.city.lower(), r.load, r.name)
    if key is SortKey.LOAD:
        return lambda r: (r.load, r.score, r.country.lower(), r.name)
    if key is SortKey.SCORE:
        return lambda r: (r.score, r.load, r.country.lower(), r.name)
    return lambda r: r.name.lower()


class ServerListScreen(Screen[None]):
    CSS = """
    #search {
        border: none;
        height: 1;
        padding: 0 1;
        background: $surface;
    }
    #search:focus {
        background: $boost;
    }
    #status-bar {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    DataTable { height: 1fr; }
    """

    BINDINGS = [
        Binding("escape", "escape", "back", priority=True),
        Binding("slash", "focus_filter", "filter", priority=True),
        Binding("c", "sort('country')", "sort country"),
        Binding("l", "sort('load')", "sort load"),
        Binding("S", "sort('score')", "sort score"),
        Binding("r", "refresh_loads", "refresh loads"),
    ]

    # Maps SortKey -> column index in the DataTable (0-based).
    _SORT_TO_COL = {
        SortKey.COUNTRY: 0,
        SortKey.LOAD: 3,
        SortKey.SCORE: -1,  # not a visible column; just affects row order
        SortKey.NAME: 2,
    }
    _COL_LABELS = ("Country", "City", "Server", "Load%", "Features")

    def __init__(self, auth: AuthService, connection: Connection) -> None:
        super().__init__()
        self._auth = auth
        self._connection = connection
        self._rows: list[ServerRow] = []  # already in current sort order
        self._sort: SortKey = SortKey.COUNTRY
        self._filter: str = ""
        self._debounce: Timer | None = None
        self._unsubscribe = lambda: None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Input(
                placeholder="Filter — country, city, or server name "
                "(start typing, or press / to focus)",
                id="search",
            )
            yield Label("Loading servers…", id="status-bar")
            yield DataTable(id="servers", cursor_type="row", zebra_stripes=True)
        yield HintBar()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns(*self._COL_LABELS)
        self._update_sort_indicator()
        # Re-render when the connection state changes — to highlight or
        # un-highlight the currently-active row.
        self._unsubscribe = self._connection.subscribe(lambda _c: self._redraw_table())
        self.run_worker(self._load(), exclusive=True, group="servers")

    def on_unmount(self) -> None:
        self._unsubscribe()

    async def _load(self) -> None:
        sl = self._auth.server_list
        if sl is None:
            self._set_status("Fetching session data…")
            try:
                sl = await self._auth.ensure_session_data()
            except Exception as exc:
                log.exception("server list fetch failed")
                self._set_status(f"Failed to load servers: {exc}")
                return

        if sl is None:
            self._set_status("No server list available.")
            return
        rows = _build_rows(list(sl.logicals), self._auth.user_tier or 0)
        rows.sort(key=_sort_keyfn(self._sort))
        self._rows = rows
        self._redraw_table()
        # Auto-focus the filter so the user sees the caret blinking there.
        self.query_one("#search", Input).focus()
        if sl.loads_expired:
            self._set_status(self._status_text() + "  (loads stale — press r)")

    # ------------------------------------------------------------------ filter

    def _visible_rows(self) -> tuple[list[ServerRow], int]:
        """Return at most DISPLAY_LIMIT rows in current sort order, plus
        the total number of matches (so the status bar can show '250 of N')."""
        needle = self._filter.lower()
        if not needle:
            return self._rows[:DISPLAY_LIMIT], len(self._rows)
        out: list[ServerRow] = []
        total = 0
        for r in self._rows:
            if _matches(r, needle):
                total += 1
                if len(out) < DISPLAY_LIMIT:
                    out.append(r)
        return out, total

    def _redraw_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        visible, total = self._visible_rows()
        active = self._connection.active
        active_id = active.server_id if active is not None else None
        for r in visible:
            if r.server_id == active_id:
                # Highlight the currently-connected server.
                cells = (
                    f"[b $success]● {r.country}[/]",
                    f"[b $success]{r.city}[/]",
                    f"[b $success]{r.name}[/]",
                    f"[b $success]{r.load}[/]",
                    f"[b $success]{r.features_str}[/]",
                )
            else:
                cells = (r.country, r.city, r.name, str(r.load), r.features_str)
            table.add_row(*cells, key=r.server_id)
        self._set_status(self._status_text(total))

    def _status_text(self, match_total: int | None = None) -> str:
        total = len(self._rows)
        tier = self._auth.user_tier
        tier_str = f" · tier {tier}" if tier is not None else ""
        sort_str = f"sort={self._sort.value}"
        if self._filter:
            mt = total if match_total is None else match_total
            shown = min(DISPLAY_LIMIT, mt)
            return (
                f"showing {shown} of {mt} matches for '{self._filter}' "
                f"· {sort_str}{tier_str}"
            )
        shown = min(DISPLAY_LIMIT, total)
        capped = "" if shown == total else "  (capped — type to filter)"
        return f"{shown} of {total} servers · {sort_str}{tier_str}{capped}"

    def _set_status(self, msg: str) -> None:
        self.query_one("#status-bar", Label).update(msg)

    # --------------------------------------------------------------- handlers

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "search":
            return
        self._filter = event.value
        if self._debounce is not None:
            self._debounce.stop()
        self._debounce = self.set_timer(FILTER_DEBOUNCE, self._redraw_table)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "search":
            return
        if self._debounce is not None:
            self._debounce.stop()
        self._redraw_table()
        self.query_one(DataTable).focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key is None or event.row_key.value is None:
            return
        sl = self._auth.server_list
        if sl is None:
            return
        try:
            server = sl.get_by_id(event.row_key.value)
        except Exception:
            self._set_status("Selected server not found.")
            return
        try:
            self._connection.start_connect(server)
        except RuntimeError as exc:
            self._set_status(str(exc))
            return
        self._set_status(f"Connecting to {server.name}…")
        self.dismiss()

    # ----------------------------------------------------------------- actions

    def action_sort(self, key: str) -> None:
        try:
            new = SortKey(key)
        except ValueError:
            return
        if new is self._sort:
            return
        self._sort = new
        self._rows.sort(key=_sort_keyfn(new))
        self._update_sort_indicator()
        self._redraw_table()

    def _update_sort_indicator(self) -> None:
        """Add an arrow to the active column header."""
        try:
            table = self.query_one(DataTable)
        except Exception:
            return
        active_idx = self._SORT_TO_COL.get(self._sort, -1)
        for idx, col_key in enumerate(table.columns):
            base = self._COL_LABELS[idx] if idx < len(self._COL_LABELS) else ""
            label = f"{base} ↑" if idx == active_idx else base
            table.columns[col_key].label = label
        # Re-render the header row.
        table.refresh()

    def action_focus_filter(self) -> None:
        self.query_one("#search", Input).focus()

    def action_escape(self) -> None:
        # Esc on filter → focus the table; Esc on the table → dismiss screen.
        if isinstance(self.focused, Input):
            self.query_one(DataTable).focus()
        else:
            self.dismiss()

    def action_refresh_loads(self) -> None:
        self.run_worker(self._do_refresh_loads(), exclusive=True, group="servers")

    async def _do_refresh_loads(self) -> None:
        self._set_status("Refreshing loads…")
        try:
            await self._auth.refresh_server_loads()
        except Exception as exc:
            log.exception("refresh_server_loads failed")
            self._set_status(f"Refresh failed: {exc}")
            return
        sl = self._auth.server_list
        if sl is not None:
            rows = _build_rows(list(sl.logicals), self._auth.user_tier or 0)
            rows.sort(key=_sort_keyfn(self._sort))
            self._rows = rows
        self._redraw_table()
