from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from enum import Enum

from .proton_api import (
    AuthService,
    ExpiredCertificateError,
    LocalAgentClient,
    LogicalServer,
    WGCredentials,
)
from .state import AppState
from .wg import (
    WGConfig,
    WGPeer,
    WGStats,
    down as wg_down,
    link_exists,
    read_stats,
    up as wg_up,
)

log = logging.getLogger(__name__)


class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"


@dataclass(frozen=True)
class ActiveConnection:
    server_id: str
    server_name: str
    endpoint: str  # "ip:port"
    exit_country: str
    domain: str = ""  # TLS SNI for local agent
    peer_pubkey: str = ""  # base64; needed to find this peer in wg show dump
    forwarded_port: int | None = None
    agent_state: str | None = None  # "CONNECTED" / "HARD_JAILED" / etc.
    agent_error: str | None = None
    stats: WGStats | None = None
    connected_at: float = 0.0  # epoch; 0 if unknown (e.g. attached on startup)


Listener = Callable[["Connection"], None]


class Connection:
    """Single-tunnel orchestrator. Owns its own asyncio task — frontend
    code never holds it. UIs call ``start_connect`` / ``start_disconnect``
    and ``subscribe`` to render state. No NetworkManager involvement.
    """

    DEFAULT_PORT = 51820
    OUR_ADDRESS = "10.2.0.2/32"
    IFACE = "wg0"

    def __init__(self, auth: AuthService) -> None:
        self._auth = auth
        self._state = ConnectionState.DISCONNECTED
        self._active: ActiveConnection | None = None
        self._target_name: str | None = None
        self._last_error: str | None = None
        self._task: asyncio.Task[object] | None = None
        self._listeners: list[Listener] = []
        self._agent: LocalAgentClient | None = None
        self._stats_task: asyncio.Task[object] | None = None

    # ---- read-only state -------------------------------------------------

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def active(self) -> ActiveConnection | None:
        return self._active

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def target_name(self) -> str | None:
        """Set during CONNECTING; cleared once active is populated."""
        return self._target_name

    @property
    def link_present(self) -> bool:
        return link_exists(self.IFACE)

    @property
    def is_busy(self) -> bool:
        return self._state in (
            ConnectionState.CONNECTING,
            ConnectionState.DISCONNECTING,
        )

    def attach_existing(self) -> bool:
        """If wg0 is already up (left over from a previous run), rehydrate
        ``active`` from the persisted last-server-id and resume the stats
        + agent loops. Returns True on success.
        """
        if not link_exists(self.IFACE):
            return False
        if self._state is ConnectionState.CONNECTED and self._active is not None:
            return True
        last_id = AppState.load().last_server_id
        if last_id is None:
            log.info("attach_existing: wg0 up but no last_server_id known")
            return False
        sl = self._auth.server_list
        if sl is None:
            log.info("attach_existing: server list not loaded yet")
            return False
        try:
            server = sl.get_by_id(last_id)
        except Exception:
            log.warning("attach_existing: last_server_id %r not found", last_id[:12])
            return False
        physicals = [p for p in (server.physical_servers or []) if p.enabled]
        if not physicals:
            return False
        physical = physicals[0]
        active = ActiveConnection(
            server_id=server.id,
            server_name=server.name or "?",
            endpoint=f"{physical.entry_ip}:{self.DEFAULT_PORT}",
            exit_country=server.exit_country or "",
            domain=physical.domain or "",
            peer_pubkey=physical.x25519_pk,
        )
        log.info(
            "attach_existing: rehydrated %s (%s)",
            active.server_name,
            active.exit_country,
        )
        self._set(ConnectionState.CONNECTED, active=active, error=None)
        # Resume the stats poller against the existing link.
        self._stats_task = asyncio.create_task(
            self._consume_stats(self.IFACE),
            name="wg-stats",
        )
        # Re-attach the local agent (best effort — port may already be
        # assigned and will reappear in the first status callback).
        if self._auth.wg_credentials is not None:
            asyncio.create_task(
                self._start_agent(physical.domain or ""),
                name="agent-reattach",
            )
        return True

    # ---- observer pattern ------------------------------------------------

    def subscribe(self, callback: Listener) -> Callable[[], None]:
        """Register a state-change callback. Returns an unsubscriber."""
        self._listeners.append(callback)

        def unsubscribe() -> None:
            with suppress(ValueError):
                self._listeners.remove(callback)

        return unsubscribe

    def _emit(self) -> None:
        for cb in list(self._listeners):
            try:
                cb(self)
            except Exception:
                log.exception("connection listener raised")

    def _set(
        self,
        state: ConnectionState,
        *,
        active: ActiveConnection | None | type = ...,
        error: str | None | type = ...,
    ) -> None:
        self._state = state
        if active is not ...:
            self._active = active  # type: ignore[assignment]
        if error is not ...:
            self._last_error = error  # type: ignore[assignment]
        log.debug(
            "state -> %s active=%s error=%s",
            state.value,
            self._active,
            self._last_error,
        )
        self._emit()

    # ---- task entry points ----------------------------------------------

    def start_connect(self, server: LogicalServer) -> asyncio.Task[object]:
        """Schedule a connect. Raises if a task is already in flight."""
        if self._task is not None and not self._task.done():
            raise RuntimeError(f"connection busy ({self._state.value})")
        self._task = asyncio.create_task(
            self._connect(server),
            name=f"connect:{server.name or server.id}",
        )
        return self._task

    def start_disconnect(self) -> asyncio.Task[object]:
        """Schedule a disconnect. Cancels any in-flight connect first."""
        if self._task is not None and not self._task.done():
            log.info("disconnect: cancelling in-flight task %s", self._task.get_name())
            self._task.cancel()
        self._task = asyncio.create_task(self._disconnect(), name="disconnect")
        return self._task

    async def shutdown(self) -> None:
        """Detach from the running tunnel without taking it down.

        Cancels in-flight tasks and closes our local-agent socket, but
        leaves wg0 in place so the tunnel keeps carrying traffic after
        the TUI exits. Use ``start_disconnect`` for an explicit teardown.
        """
        log.info("connection shutdown (tunnel preserved)")
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        if self._stats_task is not None and not self._stats_task.done():
            self._stats_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._stats_task
            self._stats_task = None
        if self._agent is not None:
            with suppress(Exception):
                await self._agent.stop()
            self._agent = None

    # ---- internal coroutines ---------------------------------------------

    async def _connect(self, server: LogicalServer) -> ActiveConnection:
        physicals = [p for p in (server.physical_servers or []) if p.enabled]
        if not physicals:
            raise RuntimeError(f"no physical servers available for {server.name}")
        physical = physicals[0]

        # WG cert expires in ~7 days. Refresh before each connect; this
        # is a no-op when the cached cert is still fresh.
        try:
            await self._auth.ensure_fresh_cert()
        except Exception as exc:
            log.exception("cert refresh failed; attempting connect anyway")
            self._set(
                ConnectionState.DISCONNECTED,
                active=None,
                error=f"cert refresh failed: {exc}",
            )
            raise

        creds = self._auth.wg_credentials
        if creds is None:
            raise RuntimeError("no WG credentials (session not loaded)")
        cfg = WGConfig(
            private_key=creds.wg_private_key,
            address=self.OUR_ADDRESS,
            peer=WGPeer(
                public_key=physical.x25519_pk,
                endpoint=f"{physical.entry_ip}:{self.DEFAULT_PORT}",
            ),
            iface=self.IFACE,
        )
        log.info(
            "connect: %s (%s) via %s",
            server.name,
            server.exit_country,
            cfg.peer.endpoint,
        )
        self._target_name = server.name or "?"
        self._set(ConnectionState.CONNECTING, active=None, error=None)
        try:
            await wg_up(cfg)
        except asyncio.CancelledError:
            log.info("connect cancelled")
            self._target_name = None
            self._set(ConnectionState.DISCONNECTED, active=None, error="cancelled")
            raise
        except Exception as exc:
            log.exception("connect failed for %s", server.name)
            self._target_name = None
            self._set(ConnectionState.DISCONNECTED, active=None, error=str(exc))
            raise

        active = ActiveConnection(
            server_id=server.id,
            server_name=server.name or "?",
            endpoint=cfg.peer.endpoint,
            exit_country=server.exit_country or "",
            domain=physical.domain or "",
            peer_pubkey=cfg.peer.public_key,
            connected_at=time.time(),
        )
        self._target_name = None
        self._set(ConnectionState.CONNECTED, active=active, error=None)
        log.info("connected: %s", active.server_name)
        # Remember for next launch's --connect=last.
        try:
            state = AppState.load()
            state.last_server_id = server.id
            state.save()
        except Exception:
            log.exception("failed to persist last_server_id (non-fatal)")

        # Bring up the local agent. Failures here don't kill the tunnel —
        # apps bound to wg0 still work without port forwarding.
        await self._start_agent(physical.domain or "")
        # Start the sysfs poller. No privileges needed; reads
        # /sys/class/net/wg0/statistics/{rx,tx}_bytes once a second.
        self._stats_task = asyncio.create_task(
            self._consume_stats(self.IFACE),
            name="wg-stats",
        )
        return active

    async def _disconnect(self) -> None:
        prior = self._active
        log.info("disconnect (prior=%s)", prior and prior.server_name)
        self._set(ConnectionState.DISCONNECTING)
        if self._stats_task is not None and not self._stats_task.done():
            self._stats_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._stats_task
            self._stats_task = None
        if self._agent is not None:
            with suppress(Exception):
                await self._agent.stop()
            self._agent = None
        try:
            await wg_down(self.IFACE)
        except asyncio.CancelledError:
            self._set(
                ConnectionState.DISCONNECTED, active=None, error="disconnect cancelled"
            )
            raise
        except Exception as exc:
            log.exception("disconnect failed")
            self._set(ConnectionState.DISCONNECTED, active=None, error=str(exc))
            raise
        else:
            self._set(ConnectionState.DISCONNECTED, active=None, error=None)

    async def _start_agent(self, domain: str) -> None:
        if not domain:
            log.warning("no domain on physical server; skipping local agent")
            return
        creds = self._auth.wg_credentials
        if creds is None:
            log.warning("no WG credentials available; skipping local agent")
            return

        agent = LocalAgentClient()
        try:
            await self._agent_connect(agent, domain, creds)
        except ExpiredCertificateError:
            log.warning("local agent: cert expired, refreshing and retrying")
            with suppress(Exception):
                await agent.stop()
            try:
                await self._auth.ensure_fresh_cert()
            except Exception:
                log.exception("cert refresh after agent rejection failed")
                self._update_agent_state(error="certificate expired")
                return
            fresh = self._auth.wg_credentials
            if fresh is None:
                self._update_agent_state(error="lost session during refresh")
                return
            agent = LocalAgentClient()
            try:
                await self._agent_connect(agent, domain, fresh)
            except Exception as exc:
                log.exception("local agent retry after cert refresh failed")
                with suppress(Exception):
                    await agent.stop()
                self._update_agent_state(error=str(exc))
                return
        except Exception as exc:
            log.exception("local agent startup failed")
            with suppress(Exception):
                await agent.stop()
            self._update_agent_state(error=str(exc))
            return
        self._agent = agent

    async def _agent_connect(
        self,
        agent: LocalAgentClient,
        domain: str,
        creds: WGCredentials,
    ) -> None:
        await agent.connect(
            domain=domain,
            private_key_pem=creds.ed25519_sk_pem,
            certificate_pem=creds.certificate_pem,
            on_status=self._on_agent_status,
            on_error=self._on_agent_error,
        )
        await agent.request_port_forwarding()

    def _on_agent_status(self, status: object) -> None:
        if self._active is None:
            return
        state_obj = getattr(status, "state", None)
        features = getattr(status, "features", None)
        forwarded = getattr(features, "forwarded_port", None) if features else None
        agent_state = str(state_obj) if state_obj is not None else None
        prev = self._active
        if (
            forwarded == prev.forwarded_port
            and agent_state == prev.agent_state
            and prev.agent_error is None
        ):
            return
        new_active = replace(
            prev,
            forwarded_port=forwarded,
            agent_state=agent_state,
            agent_error=None,
        )
        self._active = new_active
        self._emit()
        if forwarded and forwarded != prev.forwarded_port:
            log.info("forwarded port assigned: %s", forwarded)

    def _on_agent_error(self, error: Exception) -> None:
        self._update_agent_state(error=str(error))

    def _update_agent_state(self, *, error: str | None) -> None:
        if self._active is None:
            return
        new = replace(self._active, agent_error=error)
        self._active = new
        self._emit()

    async def _consume_stats(self, iface: str) -> None:
        try:
            while True:
                if self._active is None:
                    break
                stats = read_stats(iface)
                if stats is None:
                    log.debug("stats: %s gone, stopping poller", iface)
                    break
                if stats != self._active.stats:
                    self._active = replace(self._active, stats=stats)
                    self._emit()
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            log.debug("stats consumer cancelled")
            raise
        except Exception:
            log.exception("stats consumer crashed")
