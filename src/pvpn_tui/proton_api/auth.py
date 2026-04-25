"""Auth + session lifecycle for Proton VPN.

This is the only place in the codebase that reaches into ``proton.sso``
and ``proton.vpn.session`` directly. Everything else talks to
``AuthService`` and the small dataclasses defined here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from proton.sso import ProtonSSO

from .types import LoginResult, ServerList, VPNSession

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoggedInUser:
    account_name: str


@dataclass(frozen=True)
class WGCredentials:
    """Everything Connection needs to bring up wg + auth the local agent.

    Plain strings + a float, no Proton types — so the connection layer
    never has to navigate ``vpn_account.vpn_credentials.pubkey_credentials``.
    """

    wg_private_key: str  # base64
    ed25519_sk_pem: str  # PEM-encoded ED25519 private key
    certificate_pem: str  # PEM-encoded X.509 certificate
    validity_remaining_s: float  # seconds until cert expiry


class AuthService:
    """Thin wrapper around ProtonSSO + VPNSession.

    All write paths go through SSO so credentials persist across
    restarts via the system keyring (proton-sso-* entries).
    """

    # Proton's API expects "linux-vpn-<client>@<version>". The platform
    # prefix is server-side allowlisted; "linux-vpn-tui" isn't registered,
    # so the server rejects it as outdated. We pose as the GTK app
    # (the actively-maintained Linux client) until/unless Proton adds us.
    APP_VERSION = "linux-vpn-gtk@4.15.2"
    USER_AGENT = "pvpn-tui/0.1.0"

    # WG cert ships with ~7 days of validity. Refresh well before it
    # actually expires so we don't fail mid-connect.
    CERT_REFRESH_THRESHOLD_S = 24 * 3600  # 1 day

    def __init__(self) -> None:
        self._sso = ProtonSSO(
            appversion=self.APP_VERSION,
            user_agent=self.USER_AGENT,
        )
        self._session: VPNSession | None = None

    # ----- session lifecycle ----------------------------------------------

    @property
    def known_accounts(self) -> list[str]:
        return list(self._sso.sessions)

    def restore_default_session(self) -> LoggedInUser | None:
        """Load the default persisted session, if any.

        Does not contact the API — only checks local state.
        """
        if not self._sso.sessions:
            log.info("restore: no persisted sessions")
            return None
        session: VPNSession = self._sso.get_default_session(
            override_class=VPNSession,
        )
        if not session.logged_in:
            log.info("restore: persisted session not logged in")
            self._session = session
            return None
        self._session = session
        log.info("restore: signed in as %s", session.AccountName)
        return LoggedInUser(account_name=session.AccountName or "")

    async def login(self, username: str, password: str) -> LoginResult:
        log.info("login: %s", username)
        session: VPNSession = self._sso.get_session(
            username,
            override_class=VPNSession,
        )
        self._session = session
        result = await session.login(username, password)
        log.info(
            "login result: success=%s authed=%s 2fa=%s",
            result.success,
            result.authenticated,
            result.twofa_required,
        )
        return result

    async def provide_2fa(self, code: str) -> LoginResult:
        if self._session is None:
            raise RuntimeError("login() must be called before provide_2fa()")
        log.info("2fa submit")
        result = await self._session.provide_2fa_code(code)
        log.info(
            "2fa result: success=%s authed=%s",
            result.success,
            result.authenticated,
        )
        return result

    async def logout(self) -> None:
        if self._session is None:
            return
        log.info("logout: %s", self._session.AccountName)
        await self._session.logout()
        self._session = None

    @property
    def current_user(self) -> LoggedInUser | None:
        if self._session is None or not self._session.logged_in:
            return None
        return LoggedInUser(account_name=self._session.AccountName or "")

    # ----- session data --------------------------------------------------

    async def ensure_session_data(self) -> ServerList | None:
        """Make sure the session has VPN account, server list, etc.

        Issues network calls only when the local cache is missing data.
        Server-load freshness is handled by ``refresh_server_loads``.
        """
        if self._session is None:
            raise RuntimeError("Not logged in")
        if not self._session.loaded:
            log.info("ensure_session_data: fetching from API")
            await self._session.fetch_session_data()
            log.info("ensure_session_data: loaded")
        return self._session.server_list

    async def refresh_server_loads(self) -> ServerList:
        """Pull just the load percentages — cheap, runs on a timer."""
        if self._session is None:
            raise RuntimeError("Not logged in")
        log.info("refresh_server_loads")
        sl = await self._session.update_server_loads()
        log.info("refresh_server_loads: %d logicals", len(sl.logicals))
        return sl

    @property
    def server_list(self) -> ServerList | None:
        return self._session.server_list if self._session else None

    @property
    def user_tier(self) -> int | None:
        sl = self.server_list
        return sl.user_tier if sl else None

    # ----- cert / WG credentials -----------------------------------------

    @property
    def wg_credentials(self) -> WGCredentials | None:
        """Snapshot the credentials needed to bring up wg + the agent.

        Returns ``None`` when the session isn't loaded. Otherwise a
        plain dataclass with no Proton types in it.
        """
        if self._session is None or self._session.vpn_account is None:
            return None
        creds = self._session.vpn_account.vpn_credentials.pubkey_credentials
        return WGCredentials(
            wg_private_key=creds.wg_private_key,
            ed25519_sk_pem=creds.get_ed25519_sk_pem(),
            certificate_pem=creds.certificate_pem,
            validity_remaining_s=float(creds.certificate_validity_remaining),
        )

    async def ensure_fresh_cert(self) -> None:
        """If our WG cert is close to expiry, fetch a new one.

        Called before every connect. Cheap when the cached cert is fresh.
        """
        if self._session is None:
            raise RuntimeError("Not logged in")
        creds = self.wg_credentials
        remaining = creds.validity_remaining_s if creds is not None else 0.0
        if remaining > self.CERT_REFRESH_THRESHOLD_S:
            log.debug("cert OK (%.0fs remaining)", remaining)
            return
        log.info(
            "cert refresh: %.0fs remaining < %ds threshold; fetching",
            remaining,
            self.CERT_REFRESH_THRESHOLD_S,
        )
        await self._session.fetch_session_data()
        new_creds = self.wg_credentials
        new_remaining = new_creds.validity_remaining_s if new_creds else 0.0
        log.info("cert refresh complete: %.0fs remaining", new_remaining)
