from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from pvpn_tui.proton_api import LoggedInUser, WGCredentials
from pvpn_tui.proton_api.auth import AuthService


def test_wg_credentials_is_frozen() -> None:
    c = WGCredentials(
        wg_private_key="wg",
        ed25519_sk_pem="-----BEGIN-----\n",
        certificate_pem="-----BEGIN CERTIFICATE-----\n",
        validity_remaining_s=42.0,
    )
    with pytest.raises(FrozenInstanceError):
        c.validity_remaining_s = 0  # type: ignore[misc]


def test_logged_in_user_is_frozen() -> None:
    u = LoggedInUser(account_name="x@example.com")
    assert u.account_name == "x@example.com"
    with pytest.raises(FrozenInstanceError):
        u.account_name = "y"  # type: ignore[misc]


def test_app_version_format_for_proton_api() -> None:
    # Proton's API gates on the platform prefix in the appversion string.
    # Anything other than "linux-vpn-<client>@<version>" gets a 400.
    assert AuthService.APP_VERSION.startswith("linux-vpn-")
    assert "@" in AuthService.APP_VERSION


def test_cert_refresh_threshold_under_seven_days() -> None:
    # WG certs expire in ~7 days; threshold must trigger before that.
    seven_days = 7 * 24 * 3600
    assert 0 < AuthService.CERT_REFRESH_THRESHOLD_S < seven_days


async def test_provide_2fa_without_login_raises() -> None:
    auth = AuthService()
    with pytest.raises(RuntimeError, match="login"):
        await auth.provide_2fa("123456")


async def test_logout_when_not_signed_in_is_a_noop() -> None:
    auth = AuthService()
    # Shouldn't raise even though there's no session.
    await auth.logout()


async def test_ensure_session_data_without_session_raises() -> None:
    auth = AuthService()
    with pytest.raises(RuntimeError, match="Not logged in"):
        await auth.ensure_session_data()


async def test_refresh_server_loads_without_session_raises() -> None:
    auth = AuthService()
    with pytest.raises(RuntimeError, match="Not logged in"):
        await auth.refresh_server_loads()


async def test_ensure_fresh_cert_without_session_raises() -> None:
    auth = AuthService()
    with pytest.raises(RuntimeError, match="Not logged in"):
        await auth.ensure_fresh_cert()


def test_wg_credentials_is_none_when_no_session() -> None:
    auth = AuthService()
    assert auth.wg_credentials is None


def test_current_user_is_none_when_no_session() -> None:
    auth = AuthService()
    assert auth.current_user is None


def test_server_list_is_none_when_no_session() -> None:
    auth = AuthService()
    assert auth.server_list is None


def test_user_tier_is_none_when_no_session() -> None:
    auth = AuthService()
    assert auth.user_tier is None
