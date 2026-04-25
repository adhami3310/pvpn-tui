from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pvpn_tui.wg import (
    WGConfig,
    WGPeer,
    WGStats,
    _write_conf,
    link_exists,
    read_stats,
)


def _cfg(**overrides) -> WGConfig:
    base = {
        "private_key": "k" * 43 + "=",
        "address": "10.2.0.2/32",
        "peer": WGPeer(public_key="p" * 43 + "=", endpoint="1.2.3.4:51820"),
    }
    base.update(overrides)
    return WGConfig(**base)


def test_write_conf_writes_setconf_format(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    p = _write_conf(_cfg())
    body = p.read_text()
    assert "[Interface]" in body and "[Peer]" in body
    assert "PrivateKey = " in body
    assert "PublicKey = " in body
    assert "Endpoint = 1.2.3.4:51820" in body
    assert "AllowedIPs = 0.0.0.0/0" in body
    # wg setconf does NOT accept Address — make sure we don't write one.
    assert "Address" not in body


def test_write_conf_uses_runtime_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    p = _write_conf(_cfg())
    assert p.parent == tmp_path
    assert p.name.startswith("pvpn-wg-")
    assert p.suffix == ".conf"


def test_write_conf_is_user_only_readable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    p = _write_conf(_cfg())
    mode = p.stat().st_mode & 0o777
    assert mode == 0o600


def test_write_conf_includes_persistent_keepalive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    p = _write_conf(
        _cfg(
            peer=WGPeer(
                public_key="p",
                endpoint="1.2.3.4:51820",
                persistent_keepalive=15,
            )
        )
    )
    assert "PersistentKeepalive = 15" in p.read_text()


def test_read_stats_returns_none_when_missing() -> None:
    assert read_stats("definitely-not-a-real-interface-xyz") is None


@pytest.mark.skipif(
    not Path("/sys/class/net/lo/statistics/rx_bytes").exists(),
    reason="loopback sysfs not available",
)
def test_read_stats_returns_real_counters_for_loopback() -> None:
    s = read_stats("lo")
    assert s is not None
    # lo is always alive; counters are non-negative ints.
    assert s.rx_bytes >= 0
    assert s.tx_bytes >= 0
    assert isinstance(s, WGStats)


def test_read_stats_returns_none_when_counters_unparseable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    iface_dir = tmp_path / "stats"
    iface_dir.mkdir()
    (iface_dir / "rx_bytes").write_text("not-an-int")
    (iface_dir / "tx_bytes").write_text("0")
    import pvpn_tui.wg as wgmod

    monkeypatch.setattr(
        wgmod,
        "Path",
        lambda p: iface_dir if str(p).endswith("/fake/statistics") else Path(p),
    )
    assert read_stats("fake") is None


def test_link_exists_uses_ip_link_show(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        # Simulate "Device 'wg0' does not exist"
        return subprocess.CompletedProcess(args, returncode=1, stdout=b"", stderr=b"")

    monkeypatch.setattr("pvpn_tui.wg.subprocess.run", fake_run)
    assert link_exists("wg0") is False
    assert calls == [["ip", "link", "show", "wg0"]]


def test_link_exists_returns_true_when_ip_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pvpn_tui.wg.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(
            args=a[0],
            returncode=0,
            stdout=b"",
            stderr=b"",
        ),
    )
    assert link_exists("wg0") is True


def test_link_exists_handles_missing_ip_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*a, **k):
        raise FileNotFoundError("no ip on PATH")

    monkeypatch.setattr("pvpn_tui.wg.subprocess.run", fake_run)
    assert link_exists("wg0") is False
