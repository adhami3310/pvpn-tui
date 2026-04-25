"""Tiny on-disk state file: things we want to remember across runs that
aren't credentials. Lives at $XDG_STATE_HOME/pvpn-tui/state.json.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)


def _state_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "pvpn-tui" / "state.json"


@dataclass
class AppState:
    last_server_id: str | None = None

    @classmethod
    def load(cls) -> AppState:
        p = _state_path()
        try:
            data = json.loads(p.read_text())
        except FileNotFoundError:
            return cls()
        except OSError, json.JSONDecodeError:
            log.warning("state file unreadable at %s; starting fresh", p)
            return cls()
        return cls(last_server_id=data.get("last_server_id"))

    def save(self) -> None:
        p = _state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            p.write_text(json.dumps(asdict(self), indent=2))
        except OSError:
            log.exception("failed to write state file at %s", p)
