from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FMT = logging.Formatter(
    "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def default_log_path() -> Path:
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "pvpn-tui" / "pvpn.log"


def setup_logging(*, verbose: bool, debug: bool, log_file: Path | None) -> Path:
    """Install a rotating file handler. Returns the resolved log path.

    Logging never goes to stderr while the TUI is up — it would corrupt
    the screen. Tail the returned file to follow live.
    """
    log_file = log_file or default_log_path()
    log_file.parent.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        log_file,
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(_FMT)

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if debug else logging.WARNING)

    pvpn = logging.getLogger("pvpn_tui")
    pvpn.setLevel(logging.DEBUG if (verbose or debug) else logging.INFO)

    if debug:
        for name in ("proton", "proton.session", "proton.vpn", "proton.vpn.session"):
            logging.getLogger(name).setLevel(logging.DEBUG)
    else:
        # third-party at WARN to keep noise down
        for name in ("urllib3", "requests", "asyncio"):
            logging.getLogger(name).setLevel(logging.WARNING)

    return log_file
