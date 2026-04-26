"""Type stubs for the proton.vpn.local_agent Rust extension.

The actual ``.abi3.so`` is compiled by maturin from
``vendor/local-agent-rs/python-proton-vpn-local-agent``. PyO3 doesn't
emit Python type stubs, so we hand-write them here for the surface our
wrapper in ``pvpn_tui.proton_api`` actually uses.

Maintained by hand: bump when upstream adds methods we care about.
"""

from collections.abc import Awaitable, Callable
from typing import Any, ClassVar, final


# ---------------------------------------------------------------- exceptions

class LocalAgentError(Exception):
    """General exception raised by the local agent."""

class APIError(LocalAgentError):
    """Raised when an error message is read from the socket."""

class PolicyAPIError(APIError):
    """Raised when there is a policy error using the api."""

class SyntaxAPIError(APIError):
    """Raised when there is a syntax error using the api."""

class ExpiredCertificateError(LocalAgentError):
    """Raised when the passed certificate is expired."""


# ---------------------------------------------------------------- enum-likes


@final
class State:
    CONNECTED: ClassVar["State"]
    HARD_JAILED: ClassVar["State"]


@final
class ReasonCode:
    BAD_CERT_SIGNATURE: ClassVar["ReasonCode"]
    CERTIFICATE_EXPIRED: ClassVar["ReasonCode"]
    CERTIFICATE_REVOKED: ClassVar["ReasonCode"]
    CERT_NOT_PROVIDED: ClassVar["ReasonCode"]
    GUEST_SESSION: ClassVar["ReasonCode"]
    KEY_USED_MULTIPLE_TIMES: ClassVar["ReasonCode"]
    MAX_SESSIONS_BASIC: ClassVar["ReasonCode"]
    MAX_SESSIONS_FREE: ClassVar["ReasonCode"]
    MAX_SESSIONS_PLUS: ClassVar["ReasonCode"]
    MAX_SESSIONS_PRO: ClassVar["ReasonCode"]
    MAX_SESSIONS_UNKNOWN: ClassVar["ReasonCode"]
    MAX_SESSIONS_VISIONARY: ClassVar["ReasonCode"]
    POLICY_VIOLATION_DELINQUENT: ClassVar["ReasonCode"]
    POLICY_VIOLATION_LOW_PLAN: ClassVar["ReasonCode"]
    REASON_CODE_2FA_EXPIRED: ClassVar["ReasonCode"]
    REASON_CODE_2FA_SITUATION_CHANGED: ClassVar["ReasonCode"]
    REASON_CODE_2FA_UNSPECIFIED: ClassVar["ReasonCode"]
    RESTRICTED_SERVER: ClassVar["ReasonCode"]
    SERVER_ERROR: ClassVar["ReasonCode"]
    UNKNOWN: ClassVar["ReasonCode"]
    USER_BAD_BEHAVIOR: ClassVar["ReasonCode"]
    USER_TORRENT_NOT_ALLOWED: ClassVar["ReasonCode"]


# ---------------------------------------------------------------- data types


@final
class AgentFeatures:
    bouncing: str | None
    forwarded_port: int | None
    jail: bool | None
    netshield_level: int | None
    port_forwarding: bool | None
    randomized_nat: bool | None
    split_tcp: bool | None

    def __init__(
        self,
        *,
        bouncing: str | None = ...,
        forwarded_port: int | None = ...,
        jail: bool | None = ...,
        netshield_level: int | None = ...,
        port_forwarding: bool | None = ...,
        randomized_nat: bool | None = ...,
        split_tcp: bool | None = ...,
    ) -> None: ...


@final
class Reason:
    code: ReasonCode
    description: str
    is_final: bool


@final
class ConnectionDetails:
    device_country: str | None
    device_ip: str | None
    server_ipv4: str | None
    server_ipv6: str | None


@final
class Status:
    state: State
    reason: Reason | None
    features: AgentFeatures | None
    connection_details: ConnectionDetails | None


# ---------------------------------------------------------------- connection


_StatusCallback = Callable[[Status], Any]
_ErrorCallback = Callable[[Exception], Any]


@final
class AgentConnection:
    def close(self) -> Awaitable[None]: ...
    def read(self) -> Awaitable[Status]: ...
    def request_features(self, features: AgentFeatures) -> Awaitable[None]: ...
    def request_status(self) -> Awaitable[None]: ...


@final
class AgentConnector:
    @classmethod
    def connect(
        cls,
        domain: str,
        key: str,
        cert: str,
        timeout_in_seconds: int = ...,
    ) -> Awaitable[AgentConnection]: ...

    @classmethod
    def playback(cls, *args: Any, **kwargs: Any) -> Any: ...


@final
class Listener:
    @classmethod
    def connect(
        cls,
        domain: str,
        key: str,
        cert: str,
        timeout_in_seconds: int = ...,
    ) -> Awaitable["Listener"]: ...

    @classmethod
    def playback(cls, *args: Any, **kwargs: Any) -> Any: ...

    # Returns a future-like handle (asyncio.Future-compatible) that
    # iterates status_callback / error_callback. Cancel to stop.
    def listen(
        self,
        status_callback: _StatusCallback,
        error_callback: _ErrorCallback,
    ) -> Any: ...

    def request_features(self, features: AgentFeatures) -> Awaitable[None]: ...


# ---------------------------------------------------------------- module-level


def init_logger(*args: Any, **kwargs: Any) -> None: ...
