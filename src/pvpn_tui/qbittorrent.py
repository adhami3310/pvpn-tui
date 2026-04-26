"""Tiny qBittorrent Web API client — just enough to push the listen port.

Uses stdlib ``urllib`` in a worker thread so we don't drag aiohttp into
the import surface for a single endpoint pair. The blocking helpers are
private; ``push_listen_port`` is the only public entry point.
"""

from __future__ import annotations

import http.cookiejar
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from asyncio import to_thread

from .config import QBittorrentConfig

log = logging.getLogger(__name__)

_TIMEOUT = 5.0


class QBittorrentError(Exception):
    """Raised when login or setPreferences fails for any reason."""


def _login(opener: urllib.request.OpenerDirector, cfg: QBittorrentConfig) -> None:
    data = urllib.parse.urlencode(
        {"username": cfg.username, "password": cfg.password}
    ).encode()
    req = urllib.request.Request(
        f"{cfg.url}/api/v2/auth/login",
        data=data,
        # qBittorrent rejects login POSTs whose Referer isn't the same
        # origin, even with valid creds. Match it explicitly.
        headers={"Referer": cfg.url},
    )
    try:
        with opener.open(req, timeout=_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace").strip()
    except urllib.error.URLError as exc:
        raise QBittorrentError(f"login failed: {exc.reason}") from exc
    if body != "Ok.":
        # qBittorrent returns "Fails." (note the period) for bad creds.
        raise QBittorrentError(f"login refused: {body!r}")


def _set_listen_port(
    opener: urllib.request.OpenerDirector,
    cfg: QBittorrentConfig,
    port: int,
) -> None:
    data = urllib.parse.urlencode({"json": json.dumps({"listen_port": port})}).encode()
    req = urllib.request.Request(
        f"{cfg.url}/api/v2/app/setPreferences",
        data=data,
        headers={"Referer": cfg.url},
    )
    try:
        with opener.open(req, timeout=_TIMEOUT) as resp:
            resp.read()
    except urllib.error.URLError as exc:
        raise QBittorrentError(f"setPreferences failed: {exc.reason}") from exc


def _push_blocking(cfg: QBittorrentConfig, port: int) -> None:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    _login(opener, cfg)
    _set_listen_port(opener, cfg, port)


async def push_listen_port(cfg: QBittorrentConfig, port: int) -> None:
    """Log in to qBittorrent and set ``listen_port`` to ``port``.

    Raises ``QBittorrentError`` on any failure.
    """
    log.info("qbittorrent: pushing listen port %d to %s", port, cfg.url)
    await to_thread(_push_blocking, cfg, port)
