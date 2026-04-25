"""Resolve a string selector into a LogicalServer.

Accepts:
  - ``fastest``  → ServerList.get_fastest()
  - ``last``     → last_server_id from AppState (if any and still present)
  - 2-letter country code (``US``, ``JP``) → fastest in country
  - server name (``US-NY#42``)
  - server id

Used by the ``--connect`` CLI flag. Pure: no side effects, no I/O.
"""

from __future__ import annotations

from proton.vpn.session import ServerList
from proton.vpn.session.servers import LogicalServer


def resolve(
    selector: str,
    server_list: ServerList,
    *,
    last_server_id: str | None = None,
) -> LogicalServer | None:
    sel = selector.strip()
    if not sel:
        return None
    low = sel.lower()
    if low == "fastest":
        try:
            return server_list.get_fastest()
        except Exception:
            return None
    if low == "last":
        if last_server_id is None:
            return None
        try:
            return server_list.get_by_id(last_server_id)
        except Exception:
            return None
    # 2-letter country code
    if len(sel) == 2 and sel.isalpha():
        try:
            return server_list.get_fastest_in_country(sel.upper())
        except Exception:
            pass
    # explicit server name
    try:
        return server_list.get_by_name(sel)
    except Exception:
        pass
    # server id (base64-ish blob)
    try:
        return server_list.get_by_id(sel)
    except Exception:
        return None
