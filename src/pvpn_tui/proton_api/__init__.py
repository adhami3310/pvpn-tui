"""Single-seam facade over the upstream ``proton.*`` packages.

Anything outside ``proton_api/`` should import VPN-domain types and
services from here, never directly from ``proton.sso`` /
``proton.vpn.session`` / ``proton.vpn.local_agent``. Keeps the
third-party surface in one place — easier to swap, mock, or replace.
"""

from __future__ import annotations

from .agent import ErrorHandler, LocalAgentClient, StatusHandler
from .auth import AuthService, LoggedInUser, WGCredentials
from .types import (
    AgentFeatures,
    AgentListener,
    AgentReason,
    AgentReasonCode,
    AgentState,
    AgentStatus,
    ExpiredCertificateError,
    LocalAgentError,
    LogicalServer,
    LoginResult,
    PhysicalServer,
    ServerFeature,
    ServerList,
    VPNSession,
)

__all__ = [
    "AgentFeatures",
    "AgentListener",
    "AgentReason",
    "AgentReasonCode",
    "AgentState",
    "AgentStatus",
    "AuthService",
    "ErrorHandler",
    "ExpiredCertificateError",
    "LocalAgentClient",
    "LocalAgentError",
    "LoggedInUser",
    "LogicalServer",
    "LoginResult",
    "PhysicalServer",
    "ServerFeature",
    "ServerList",
    "StatusHandler",
    "VPNSession",
    "WGCredentials",
]
