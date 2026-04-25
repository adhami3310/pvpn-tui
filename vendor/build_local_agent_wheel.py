"""Build a wheel for `proton-vpn-local-agent` by vendoring the system .so.

The PyPI release of `proton-vpn-local-agent` (0.1.1) is a 1.4 KB stub —
Proton ships the Rust extension via distro packages instead. On Arch the
artifact lives at:

    /usr/lib/python3.14/site-packages/proton/vpn/local_agent.abi3.so

This script wraps that file in a proper wheel so uv can pick it up via
`[tool.uv.sources]`. Run from the project root:

    python vendor/build_local_agent_wheel.py

Re-run when bumping Python or the Arch package version.
"""

from __future__ import annotations

import base64
import hashlib
import sys
import zipfile
from pathlib import Path

# Default location of the Arch python-proton-vpn-local-agent install.
DEFAULT_SO = Path("/usr/lib/python3.14/site-packages/proton/vpn/local_agent.abi3.so")
VERSION = "0.1.1"
PROJECT = "proton_vpn_local_agent"


def b64sha(data: bytes) -> tuple[str, int]:
    h = hashlib.sha256(data).digest()
    return (
        "sha256=" + base64.urlsafe_b64encode(h).rstrip(b"=").decode(),
        len(data),
    )


def build(so_path: Path, out_dir: Path, py_tag: str = "cp314") -> Path:
    if not so_path.exists():
        raise SystemExit(f"local_agent .so not found at {so_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    wheel_name = f"{PROJECT}-{VERSION}-{py_tag}-abi3-linux_x86_64.whl"
    out = out_dir / wheel_name
    dist_info = f"{PROJECT}-{VERSION}.dist-info"

    so_data = so_path.read_bytes()
    metadata = (
        "Metadata-Version: 2.1\n"
        f"Name: proton-vpn-local-agent\n"
        f"Version: {VERSION}\n"
        "Summary: Local agent library (vendored from system .so)\n"
        "Home-page: https://github.com/ProtonVPN/local-agent-rs\n"
        f"Requires-Python: >={py_tag[2:3]}.{py_tag[3:]}\n"
    )
    wheel_md = (
        "Wheel-Version: 1.0\n"
        "Generator: pvpn-tui-vendor (build_local_agent_wheel.py)\n"
        "Root-Is-Purelib: false\n"
        f"Tag: {py_tag}-abi3-linux_x86_64\n"
    )
    top_level = "proton\n"

    files = [
        ("proton/vpn/local_agent.abi3.so", so_data),
        (f"{dist_info}/METADATA", metadata.encode()),
        (f"{dist_info}/WHEEL", wheel_md.encode()),
        (f"{dist_info}/top_level.txt", top_level.encode()),
    ]

    record_lines = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for arcname, data in files:
            z.writestr(arcname, data)
            digest, size = b64sha(data)
            record_lines.append(f"{arcname},{digest},{size}")
        record_lines.append(f"{dist_info}/RECORD,,")
        z.writestr(f"{dist_info}/RECORD", "\n".join(record_lines) + "\n")

    return out


if __name__ == "__main__":
    so = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SO
    repo_root = Path(__file__).resolve().parent.parent
    out = build(so, repo_root / "vendor" / "wheels")
    print(f"built {out}")
