from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__
from ._logging import default_log_path, setup_logging


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pvpn",
        description="Proton VPN TUI client (no NetworkManager).",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="DEBUG logging for pvpn_tui itself",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="DEBUG logging including proton-core internals",
    )
    p.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help=f"override log file (default: {default_log_path()})",
    )
    p.add_argument(
        "-c",
        "--connect",
        metavar="SELECTOR",
        default=None,
        help=(
            "auto-connect on launch. SELECTOR may be: 'fastest', 'last', a "
            "2-letter country code (US, JP), a server name (US-NY#42), or a "
            "server id"
        ),
    )
    p.add_argument(
        "--theme",
        metavar="NAME",
        default=None,
        help=(
            "override the Textual theme. Default: 'textual-ansi' (inherits "
            "the terminal's palette). Other examples: 'textual-dark', "
            "'textual-light', 'nord', 'gruvbox', 'tokyo-night'."
        ),
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"pvpn-tui {__version__}",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    log_path = setup_logging(
        verbose=args.verbose,
        debug=args.debug,
        log_file=args.log_file,
    )
    log = logging.getLogger("pvpn_tui.cli")
    log.info(
        "pvpn-tui %s starting (verbose=%s debug=%s)",
        __version__,
        args.verbose,
        args.debug,
    )
    print(f"pvpn-tui logging to {log_path}", file=sys.stderr)

    try:
        from .app import PvpnApp

        PvpnApp(
            connect_selector=args.connect,
            theme=args.theme,
        ).run()
    except KeyboardInterrupt:
        log.info("interrupted by user")
        return 130
    except Exception:
        log.exception("fatal error")
        raise
    finally:
        log.info("pvpn-tui exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
