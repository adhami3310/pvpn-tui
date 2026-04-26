# pvpn-tui

A sane Proton VPN client for Linux, in your terminal. No NetworkManager.

## Why

The official Proton VPN Linux stack has a structural bug: every connect spawns a
sinkhole "kill-switch" NetworkManager connection at metric 98 and calls
`device.reapply_async(...)` on the carrier interface inside the same flow. NM's
reapply wipes the carrier's DHCP4 lease and starts a fresh transaction; with the
sinkhole as the only IPv4 default route, the unicast renewal can't reach the DHCP
server. The carrier has no IPv4 for the entire connect window, so `tcpcheck` and
the WireGuard handshake both fail. Even with `NM_DEVICE_REAPPLY_FLAGS_PRESERVE_EXTERNAL_IP`
(NM 1.42+), DHCP-managed leases are still tracked and still get wiped.

This tool brings up `wg0` directly via `ip link add` + `wg setconf` and never
touches NM. Single TUI process, single wg interface, no sinkhole, no daemon.

## What it does (and doesn't)

- Login via `proton.sso` (persists in your system keyring, like the GTK app).
- Browse Proton's server list with search + sort.
- Bring up `wg0` for one server at a time. `Address 10.2.0.2/32`. No default
  route, no DNS override.
- Talk to Proton's local agent inside the tunnel for **port forwarding**, surface
  the assigned port for you to paste into qBittorrent / etc.
- Live status: connection state, agent state, forwarded port, rx/tx bytes.
- Survives quit. The tunnel stays up after `q` / `^c`; relaunching the TUI
  reattaches.

What it deliberately doesn't do:

- No kill-switch.
- No app-based traffic steering (cgroup / eBPF / netns). Apps that want the VPN
  bind to `wg0` themselves.
- No multi-server failover, no auto-reconnect on suspend.
- No IPv6 (deferred).
- No system tray.

## Install

```sh
git clone https://github.com/adhami3310/pvpn-tui
cd pvpn-tui
git submodule update --init   # do NOT pass --recursive (see below)
uv sync
uv run pvpn
```

Both vendored submodules — [`local-agent-rs`](https://github.com/ProtonVPN/local-agent-rs)
and [`python-proton-vpn-api-core`](https://github.com/ProtonVPN/python-proton-vpn-api-core) —
have nested submodules (`scripts/devtools`, `ci-libraries-rust`) that point at
Proton's private GitLab and aren't published on GitHub. They're not needed to
build — pass `--init` only, never `--recursive`.

`uv sync` builds `proton-vpn-local-agent` from the Rust source at
[`vendor/local-agent-rs/`](vendor/local-agent-rs/), and installs
`proton-vpn-api-core` from the Python source at
[`vendor/python-proton-vpn-api-core/`](vendor/python-proton-vpn-api-core/).
That requires:

- `cargo` (install via [rustup](https://rustup.rs))
- a C linker (`gcc` or `clang`)
- `wireguard-tools` (`wg`), `iproute2` (`ip`), `polkit` (`pkexec`) for runtime
- Python 3.14 (uv handles this if missing)

Cold cargo build is ~1–2 min; subsequent runs reuse cargo's `target/` cache.

### Runtime requirements

- Python 3.14 (matches Proton's wheels).
- `wg`, `ip` (from `wireguard-tools` and `iproute2`).
- `pkexec` (from `polkit`) — used for the privileged `wg`/`ip` calls only. The
  TUI itself runs as your normal user.

## Usage

```sh
uv run pvpn                    # interactive TUI
uv run pvpn -c fastest         # auto-connect to fastest, then drop into TUI
uv run pvpn -c last            # reconnect to last server
uv run pvpn -c US              # fastest in country
uv run pvpn -c JP#42           # specific server name
uv run pvpn -v                 # debug logging
uv run pvpn --log-file PATH    # override log path
uv run pvpn --theme nord       # override Textual theme
```

Logs default to `$XDG_STATE_HOME/pvpn-tui/pvpn.log`.

### Keys

**Main screen:**
| key | action |
|-----|--------|
| `f` | connect to fastest |
| `r` | reconnect to last |
| `s` | open server browser |
| `p` | push forwarded port to qBittorrent (requires config) |
| `d` | disconnect (explicit teardown) |
| `L` | logout |
| `q` / `^c` | quit (tunnel stays up) |

**Server browser:**
| key | action |
|-----|--------|
| (just type) | filter by country / city / name |
| `/` | refocus filter input |
| `c` / `l` / `S` | sort by country / load / score |
| `r` | refresh server loads (one API call) |
| `Enter` (on a row) | connect to that server |
| `Esc` | filter → table → back to main |

### Once connected

Apps that should use the tunnel must bind to `wg0` themselves (we don't install
a default route). qBittorrent: Settings → Advanced → Network interface = `wg0`.
The MainScreen panel shows the **forwarded port** assigned by Proton's local
agent — paste it into qBittorrent's Connection settings, or press `p` to push
it via qBittorrent's Web API (see *Config* below).

### Config

Optional. The TUI reads `$XDG_CONFIG_HOME/pvpn-tui/config.toml`
(`~/.config/pvpn-tui/config.toml` by default). Currently the only section is
`[qbittorrent]`, which enables the `p` keybinding to set qBittorrent's
listen port to the agent-assigned forwarded port.

The first time you press `p` without a config, pvpn writes a starter file:

```toml
[qbittorrent]
url = "http://localhost:8080"
username = ""
password = ""
```

Fill in `username` and `password` (qBittorrent → Tools → Preferences → Web UI)
and press `p` again — pvpn re-reads the config on each press, so no restart.

## Architecture

Domain layer is frontend-agnostic:

- `pvpn_tui.proton_api` — facade over `proton.sso` / `proton.vpn.session` /
  `proton.vpn.local_agent`. Single seam; nothing else in the codebase imports
  `proton.*`.
- `pvpn_tui.connection.Connection` — single-tunnel orchestrator. Owns its own
  `asyncio.Task`, exposes `start_connect` / `start_disconnect` / `subscribe`,
  takes an `AuthProvider` Protocol so tests can fake it without inheriting.
- `pvpn_tui.wg` — `wg setconf` + `ip link` via `pkexec`. Stats via sysfs (no
  privileges).

Frontend (Textual screens in `pvpn_tui.screens.*`) just observes state and
dispatches user actions.

## Development

```sh
uv sync                          # install + dev deps
uv run pytest                    # 100+ tests
uv run ruff check src/ tests/    # lint
uv run ruff format src/ tests/   # format
uv run pyright                   # types
```

CI runs all four on every push. Pre-commit hooks (ruff lint + format) install
via:

```sh
uv run pre-commit install
```

## License

MIT. See [LICENSE](LICENSE).
