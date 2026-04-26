from __future__ import annotations

import pytest

from pvpn_tui.proton_api.auth import AuthService


@pytest.fixture(autouse=True)
def _isolate_keyring(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Stop tests from touching the user's real keyring or state file.

    ``ProtonSSO`` reads the system keyring at construction; replace its
    invocation with a no-op so screen mounting doesn't depend on the
    machine's auth state.
    """

    def fake_init(self, **kwargs) -> None:
        self._sso = None  # screens don't read this directly
        self._session = None

    monkeypatch.setattr(AuthService, "__init__", fake_init)
    monkeypatch.setattr(
        AuthService,
        "restore_default_session",
        lambda self: None,
    )
    # Send any state file writes into the temp dir.
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
