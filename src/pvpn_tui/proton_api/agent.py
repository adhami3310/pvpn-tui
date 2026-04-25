"""Wrapper around proton.vpn.local_agent (Rust extension).

Connects to the local agent at 10.2.0.1 over the active WireGuard tunnel
to request feature toggles like port forwarding. The actual TCP+TLS
plumbing is in the Rust crate (`local-agent-rs`); we just bridge to the
asyncio API the extension exposes.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress

from .types import (
    AgentFeatures,
    AgentListener,
    AgentStatus,
    ExpiredCertificateError,
)

log = logging.getLogger(__name__)


StatusHandler = Callable[[AgentStatus], None]
ErrorHandler = Callable[[Exception], None]


class LocalAgentClient:
    """Manages the lifetime of a single local-agent connection."""

    def __init__(self) -> None:
        self._listener: AgentListener | None = None
        self._listen_future: asyncio.Future | None = None
        self._on_status: StatusHandler | None = None
        self._on_error: ErrorHandler | None = None

    @property
    def connected(self) -> bool:
        return self._listener is not None

    async def connect(
        self,
        *,
        domain: str,
        private_key_pem: str,
        certificate_pem: str,
        on_status: StatusHandler,
        on_error: ErrorHandler | None = None,
        timeout_seconds: int = 10,
    ) -> None:
        log.info("local agent connect: domain=%s", domain)
        self._on_status = on_status
        self._on_error = on_error
        try:
            listener = await AgentListener.connect(
                domain,
                private_key_pem,
                certificate_pem,
                timeout_in_seconds=int(timeout_seconds),
            )
        except ExpiredCertificateError:
            log.warning("local agent: certificate expired")
            raise
        self._listener = listener
        log.info("local agent: connected, starting listener loop")
        self._listen_future = listener.listen(
            self._on_status_proxy,
            self._on_error_proxy,
        )

    async def request_port_forwarding(self) -> None:
        if self._listener is None:
            raise RuntimeError("local agent not connected")
        features = AgentFeatures(port_forwarding=True)
        log.info("local agent: request port_forwarding=True")
        await self._listener.request_features(features)

    async def stop(self) -> None:
        if self._listen_future is not None:
            with suppress(Exception):
                self._listen_future.cancel()
            with suppress(Exception, asyncio.CancelledError):
                await self._listen_future
        self._listener = None
        self._listen_future = None
        self._on_status = None
        self._on_error = None
        log.info("local agent: stopped")

    def _on_status_proxy(self, status: AgentStatus) -> None:
        log.debug(
            "agent status: state=%s reason=%s features=%s",
            getattr(status, "state", None),
            getattr(status, "reason", None),
            self._features_repr(getattr(status, "features", None)),
        )
        if self._on_status is not None:
            try:
                self._on_status(status)
            except Exception:
                log.exception("agent status handler raised")

    def _on_error_proxy(self, error: Exception) -> None:
        log.warning("agent error: %s", error)
        if self._on_error is not None:
            try:
                self._on_error(error)
            except Exception:
                log.exception("agent error handler raised")

    @staticmethod
    def _features_repr(features: AgentFeatures | None) -> str:
        if features is None:
            return "None"
        try:
            return (
                f"port_forwarding={features.port_forwarding} "
                f"forwarded_port={features.forwarded_port}"
            )
        except Exception:
            return repr(features)
