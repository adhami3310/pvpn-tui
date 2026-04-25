"""Type re-exports from the proton-* packages.

The rest of the codebase imports VPN-domain types from here instead of
the upstream `proton.*` modules. That way, ``proton_api/`` is the only
seam where Proton-specific code is touched.
"""

from __future__ import annotations

from proton.vpn.local_agent import (
    AgentFeatures,
    ExpiredCertificateError,
    Listener as AgentListener,
    LocalAgentError,
    Reason as AgentReason,
    ReasonCode as AgentReasonCode,
    State as AgentState,
    Status as AgentStatus,
)
from proton.vpn.session import ServerList, VPNSession
from proton.vpn.session.dataclasses.login_result import LoginResult
from proton.vpn.session.servers import (
    LogicalServer,
    PhysicalServer,
    ServerFeatureEnum as ServerFeature,
)

__all__ = [
    "AgentFeatures",
    "AgentListener",
    "AgentReason",
    "AgentReasonCode",
    "AgentState",
    "AgentStatus",
    "ExpiredCertificateError",
    "LocalAgentError",
    "LogicalServer",
    "LoginResult",
    "PhysicalServer",
    "ServerFeature",
    "ServerList",
    "VPNSession",
]
