"""`powerclock-daemon`: runs the API and the engine in the foreground (systemd supervises it)."""

import argparse
import logging
import socket
import sys

import uvicorn

from powerclock.config import Paths, SettingsError, load_settings
from powerclock.daemon.core import Daemon
from powerclock.platform import dry_run_requested, get_backend
from powerclock.platform.base import NotSupported


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="powerclock-daemon", description="PowerClock daemon")
    parser.add_argument(
        "--foreground", action="store_true", help="accepted for clarity: it always is"
    )
    parser.add_argument("--port", type=int, help="override the port in daemon.json")
    parser.add_argument("--dry-run", action="store_true", help="only log power actions")
    parser.add_argument("--log-level", choices=["debug", "info", "warning", "error"])
    args = parser.parse_args(argv)

    paths = Paths.default()
    try:
        settings = load_settings(paths)
    except SettingsError as exc:
        sys.exit(str(exc))
    updates = {
        key: value for key, value in (("port", args.port), ("log_level", args.log_level)) if value
    }
    settings = settings.model_copy(update=updates)
    logging.basicConfig(
        level=settings.log_level.upper(), format="%(levelname)s %(name)s: %(message)s"
    )
    dry_run = settings.dry_run or args.dry_run or dry_run_requested()
    try:
        backend = get_backend(dry_run=dry_run)
    except NotSupported as exc:
        sys.exit(f"{exc} ({exc.fix_hint})" if exc.fix_hint else str(exc))
    _check_port(settings.port)
    daemon = Daemon(backend, paths=paths, settings=settings, dry_run=dry_run)
    config = uvicorn.Config(
        daemon.app,
        host="127.0.0.1",  # never reachable from other machines
        port=settings.port,
        log_level="warning",
        access_log=False,
        ws="websockets-sansio",
        lifespan="on",
    )
    uvicorn.Server(config).run()


def _check_port(port: int) -> None:
    """Say who is in the way before uvicorn prints its own error: another PowerClock is the
    usual answer, and starting a second one is never what the user wanted."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            sys.exit(
                f"PowerClock is already running on port {port} "
                f"(powerclock status), or something else is using it "
                f"(change `port` in {Paths.default().settings})."
            )
