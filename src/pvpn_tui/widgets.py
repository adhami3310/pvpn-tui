"""Small reusable widgets that don't fit in screens/."""

from __future__ import annotations

from textual.widgets import Static


class HintBar(Static):
    """Drop-in replacement for ``textual.widgets.Footer`` that doesn't
    fight us over background colours.

    Reads visible bindings off the parent screen + app and renders them
    as plain text styled by our App.CSS. Uses the terminal's default
    foreground/background so it follows whatever theme the terminal has.
    """

    def __init__(self) -> None:
        super().__init__("", markup=True)

    def on_mount(self) -> None:
        self._refresh_hints()
        # If bindings change at runtime (rare for us), pick that up.
        self.set_interval(2.0, self._refresh_hints)

    def _refresh_hints(self) -> None:
        screen = self.screen
        app = self.app
        # Collect bindings from the focused screen first, then app-level.
        seen: set[str] = set()
        parts: list[str] = []
        for source in (screen, app):
            for binding in getattr(source, "BINDINGS", ()):
                if not getattr(binding, "show", True):
                    continue
                key = getattr(binding, "key", "")
                desc = getattr(binding, "description", "")
                if not key or not desc or key in seen:
                    continue
                seen.add(key)
                parts.append(f"[b]{_pretty_key(key)}[/] {desc}")
        self.update("  ·  ".join(parts) if parts else "")


def _pretty_key(key: str) -> str:
    # "ctrl+q" → "^q", "escape" → "esc", "slash" → "/", etc.
    table = {
        "escape": "esc",
        "slash": "/",
        "enter": "↵",
        "space": "␣",
        "tab": "⇥",
        "up": "↑",
        "down": "↓",
        "left": "←",
        "right": "→",
    }
    if key in table:
        return table[key]
    if key.startswith("ctrl+"):
        return "^" + key[len("ctrl+") :]
    return key
