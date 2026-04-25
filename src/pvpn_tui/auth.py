from __future__ import annotations

import logging
from dataclasses import dataclass

from proton.sso import ProtonSSO
from proton.vpn.session import ServerList, VPNSession
from proton.vpn.session.dataclasses.login_result import LoginResult

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoggedInUser:
    account_name: str


class AuthService:
    """Thin wrapper around ProtonSSO + VPNSession.

    All write paths go through SSO so credentials persist across
    restarts via the system keyring (proton-sso-* entries).
    """

    # Proton's API expects "linux-vpn-<client>@<version>". The platform
    # prefix is server-side allowlisted; "linux-vpn-tui" isn't registered,
    # so the server rejects it as outdated. We pose as the GTK app
    # (the actively-maintained Linux client) until/unless Proton adds us.
    # See proton.vpn.core.session_holder._get_app_version_header_value.
    APP_VERSION = "linux-vpn-gtk@4.15.2"
    USER_AGENT = "pvpn-tui/0.1.0"

    def __init__(self) -> None:
        self._sso = ProtonSSO(
            appversion=self.APP_VERSION,
            user_agent=self.USER_AGENT,
        )
        self._session: VPNSession | None = None

    @property
    def session(self) -> VPNSession | None:
        return self._session

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

    async def ensure_session_data(self) -> ServerList:
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

    # WG cert ships with ~7 days of validity. Refresh well before it
    # actually expires so we don't fail mid-connect.
    CERT_REFRESH_THRESHOLD_S = 24 * 3600  # 1 day

    async def ensure_fresh_cert(self) -> None:
        """If our WG cert is close to expiry, fetch a new one.

        Called before every connect. Cheap when the cached cert is fresh.
        """
        if self._session is None:
            raise RuntimeError("Not logged in")
        creds = (
            self._session.vpn_account.vpn_credentials.pubkey_credentials
            if self._session.vpn_account is not None
            else None
        )
        remaining = (
            float(creds.certificate_validity_remaining) if creds is not None else 0.0
        )
        if remaining > self.CERT_REFRESH_THRESHOLD_S:
            log.debug("cert OK (%.0fs remaining)", remaining)
            return
        log.info(
            "cert refresh: %.0fs remaining < %ds threshold; fetching",
            remaining,
            self.CERT_REFRESH_THRESHOLD_S,
        )
        await self._session.fetch_session_data()
        new_remaining = (
            float(
                self._session.vpn_account.vpn_credentials.pubkey_credentials.certificate_validity_remaining
            )
            if self._session.vpn_account is not None
            else 0.0
        )
        log.info("cert refresh complete: %.0fs remaining", new_remaining)

    @property
    def server_list(self) -> ServerList | None:
        return self._session.server_list if self._session else None

    @property
    def user_tier(self) -> int | None:
        sl = self.server_list
        return sl.user_tier if sl else None
