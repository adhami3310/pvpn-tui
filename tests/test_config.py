from __future__ import annotations

from pathlib import Path

import pytest

from pvpn_tui.config import QBittorrentConfig, default_path, load, write_template


@pytest.fixture
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path / "pvpn-tui" / "config.toml"


def test_default_path_uses_xdg_config_home(config_home: Path) -> None:
    assert default_path() == config_home


def test_load_returns_empty_when_missing(config_home: Path) -> None:
    cfg = load()
    assert cfg.qbittorrent is None


def test_load_parses_qbittorrent_section(config_home: Path) -> None:
    config_home.parent.mkdir(parents=True)
    config_home.write_text(
        "[qbittorrent]\n"
        'url = "http://localhost:8080/"\n'
        'username = "admin"\n'
        'password = "secret"\n'
    )
    cfg = load()
    assert cfg.qbittorrent == QBittorrentConfig(
        url="http://localhost:8080",
        username="admin",
        password="secret",
    )


def test_load_ignores_section_with_missing_fields(
    config_home: Path,
) -> None:
    config_home.parent.mkdir(parents=True)
    config_home.write_text('[qbittorrent]\nurl = "http://x"\n')
    assert load().qbittorrent is None


def test_load_ignores_corrupt_file(config_home: Path) -> None:
    config_home.parent.mkdir(parents=True)
    config_home.write_text("not toml = = =")
    assert load().qbittorrent is None


def test_load_explicit_path(tmp_path: Path) -> None:
    p = tmp_path / "alt.toml"
    p.write_text('[qbittorrent]\nurl = "http://h:1"\nusername = "u"\npassword = "p"\n')
    cfg = load(p)
    assert cfg.qbittorrent is not None
    assert cfg.qbittorrent.url == "http://h:1"


def test_write_template_creates_file_and_parents(config_home: Path) -> None:
    assert not config_home.exists()
    assert write_template() is True
    assert config_home.exists()
    text = config_home.read_text()
    assert "[qbittorrent]" in text
    assert "username" in text
    assert "password" in text


def test_write_template_does_not_overwrite_existing(config_home: Path) -> None:
    config_home.parent.mkdir(parents=True)
    config_home.write_text("# my own config\n")
    assert write_template() is False
    assert config_home.read_text() == "# my own config\n"


def test_write_template_load_returns_none(config_home: Path) -> None:
    # Template ships with blank username/password — load() must treat
    # that as "not configured" so the caller can prompt the user to
    # fill it in instead of attempting a guaranteed-401 login.
    write_template()
    assert load().qbittorrent is None


def test_load_blank_credentials_treated_as_unset(config_home: Path) -> None:
    config_home.parent.mkdir(parents=True)
    config_home.write_text(
        '[qbittorrent]\nurl = "http://x"\nusername = ""\npassword = ""\n'
    )
    assert load().qbittorrent is None
