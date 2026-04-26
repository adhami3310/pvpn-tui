"""Optional user config at ``$XDG_CONFIG_HOME/pvpn-tui/config.toml``.

Entirely optional. If the file is missing or a section is unset, the
matching feature is just disabled — nothing in the TUI requires config
to exist.
"""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class QBittorrentConfig:
    url: str
    username: str
    password: str


@dataclass(frozen=True)
class Config:
    qbittorrent: QBittorrentConfig | None = None


def default_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "pvpn-tui" / "config.toml"


_QBITTORRENT_TEMPLATE = """\
# pvpn-tui config. Fill in the [qbittorrent] fields and press `p` in the
# TUI to push the agent-assigned forwarded port to qBittorrent.
# Enable Tools -> Preferences -> Web UI in qBittorrent first.

[qbittorrent]
url = "http://localhost:8080"
username = ""
password = ""
"""


def write_template(path: Path | None = None) -> bool:
    """Write a starter config to ``path`` (or the default) if absent.

    Returns ``True`` if the file was created, ``False`` if it already
    existed (we never overwrite a user-edited file).
    """
    p = path or default_path()
    if p.exists():
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_QBITTORRENT_TEMPLATE)
    return True


def load(path: Path | None = None) -> Config:
    p = path or default_path()
    if not p.exists():
        return Config()
    try:
        data = tomllib.loads(p.read_text())
    except OSError, tomllib.TOMLDecodeError:
        log.exception("failed to read %s", p)
        return Config()

    qbt = None
    section = data.get("qbittorrent")
    if isinstance(section, dict):
        url = section.get("url")
        user = section.get("username")
        pw = section.get("password")
        # Treat blank fields the same as absent — that's what the
        # write_template() starter file looks like, and we want the
        # caller to see "not configured" rather than "login refused".
        if (
            isinstance(url, str)
            and isinstance(user, str)
            and isinstance(pw, str)
            and url
            and user
            and pw
        ):
            qbt = QBittorrentConfig(url=url.rstrip("/"), username=user, password=pw)
        elif section:
            log.warning(
                "%s: [qbittorrent] needs non-empty url/username/password",
                p,
            )
    return Config(qbittorrent=qbt)
