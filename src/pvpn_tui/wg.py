from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


class WGError(RuntimeError):
    pass


@dataclass(frozen=True)
class WGPeer:
    public_key: str  # base64
    endpoint: str  # "ip:port"
    allowed_ips: str = "0.0.0.0/0"
    persistent_keepalive: int = 25


@dataclass(frozen=True)
class WGConfig:
    private_key: str  # base64
    address: str  # CIDR, e.g. "10.2.0.2/32"
    peer: WGPeer
    iface: str = "wg0"
    # IPs that must reach the peer (e.g. the local agent at 10.2.0.1).
    # Single /32 routes added on the wg interface — never a default route.
    pinned_routes: tuple[str, ...] = ("10.2.0.1/32",)


def _runtime_dir() -> Path:
    rt = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    p = Path(rt)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _write_conf(cfg: WGConfig) -> Path:
    """Write a wg-setconf-compatible config file (no Address, no DNS)."""
    fd, path = tempfile.mkstemp(
        prefix="pvpn-wg-",
        suffix=".conf",
        dir=str(_runtime_dir()),
    )
    os.fchmod(fd, 0o600)
    body = (
        "[Interface]\n"
        f"PrivateKey = {cfg.private_key}\n"
        "\n"
        "[Peer]\n"
        f"PublicKey = {cfg.peer.public_key}\n"
        f"Endpoint = {cfg.peer.endpoint}\n"
        f"AllowedIPs = {cfg.peer.allowed_ips}\n"
        f"PersistentKeepalive = {cfg.peer.persistent_keepalive}\n"
    )
    with os.fdopen(fd, "w") as f:
        f.write(body)
    return Path(path)


async def _pkexec_sh(script: str) -> None:
    log.debug("pkexec script:\n%s", script)
    proc = await asyncio.create_subprocess_exec(
        "pkexec",
        "/bin/sh",
        "-c",
        script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await proc.communicate()
    except asyncio.CancelledError:
        log.warning("pkexec cancelled, killing pid %s", proc.pid)
        with suppress(ProcessLookupError):
            proc.kill()
        with suppress(TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        raise
    log.debug(
        "pkexec rc=%s stdout=%r stderr=%r",
        proc.returncode,
        out.decode(errors="replace"),
        err.decode(errors="replace"),
    )
    if proc.returncode != 0:
        msg = (
            err.decode().strip()
            or out.decode().strip()
            or f"pkexec exit {proc.returncode}"
        )
        raise WGError(msg)


async def up(cfg: WGConfig) -> None:
    """Bring up `wg0` against `cfg.peer`. Tears down a stale link first."""
    log.info(
        "wg up: iface=%s address=%s peer=%s endpoint=%s",
        cfg.iface,
        cfg.address,
        cfg.peer.public_key[:8] + "…",
        cfg.peer.endpoint,
    )
    conf = _write_conf(cfg)
    route_lines = "".join(
        f"ip route add {r} dev {cfg.iface}\n" for r in cfg.pinned_routes
    )
    script = (
        "set -eu\n"
        f"ip link del {cfg.iface} 2>/dev/null || true\n"
        f"ip link add {cfg.iface} type wireguard\n"
        f"wg setconf {cfg.iface} {conf}\n"
        f"ip addr add {cfg.address} dev {cfg.iface}\n"
        f"ip link set {cfg.iface} up\n" + route_lines
    )
    try:
        await _pkexec_sh(script)
    finally:
        with suppress(FileNotFoundError):
            conf.unlink()
    log.info("wg up: %s active", cfg.iface)


async def down(iface: str = "wg0") -> None:
    """Delete the wg link if it exists. Idempotent."""
    if not link_exists(iface):
        log.debug("wg down: %s already absent", iface)
        return
    log.info("wg down: %s", iface)
    await _pkexec_sh(f"ip link del {iface}")


def link_exists(iface: str = "wg0") -> bool:
    try:
        result = subprocess.run(
            ["ip", "link", "show", iface],
            capture_output=True,
            check=False,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


@dataclass(frozen=True)
class WGStats:
    rx_bytes: int = 0
    tx_bytes: int = 0


def read_stats(iface: str = "wg0") -> WGStats | None:
    """Read rx/tx counters from sysfs (world-readable, no privileges).

    Returns None if the interface is gone. Handshake age + endpoint live
    only in the wg netlink API which requires CAP_NET_ADMIN, so we skip
    them here — agent state already tells us the tunnel is alive.
    """
    base = Path(f"/sys/class/net/{iface}/statistics")
    try:
        rx = int((base / "rx_bytes").read_text().strip())
        tx = int((base / "tx_bytes").read_text().strip())
    except OSError, ValueError:
        return None
    return WGStats(rx_bytes=rx, tx_bytes=tx)
