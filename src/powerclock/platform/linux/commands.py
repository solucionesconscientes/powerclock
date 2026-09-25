"""External programs (kscreen-doctor, xdg-open…), behind a protocol so tests can fake them."""

import asyncio
import contextlib
import os
import shutil
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

RUN_LIMIT = 15.0  # seconds before a helper program is considered stuck
SPAWN_SETTLE = 3.0  # seconds to wait for a launcher (xdg-open) to fail fast


class Commands(Protocol):
    def which(self, name: str) -> str | None: ...

    async def run(
        self, argv: Sequence[str], env: Mapping[str, str] | None = None, limit: float | None = None
    ) -> tuple[int, str]:
        """Run to completion (at most `limit` seconds, RUN_LIMIT by default); return (exit
        code, combined output). Raises OSError."""
        ...

    async def spawn(self, argv: Sequence[str], env: Mapping[str, str] | None = None) -> int | None:
        """Start a launcher; return its exit code if it ends quickly, else None (still running)."""
        ...


class SystemCommands:
    def __init__(self) -> None:
        self._background: set[asyncio.Task[Any]] = set()

    def which(self, name: str) -> str | None:
        return shutil.which(name)

    async def run(
        self, argv: Sequence[str], env: Mapping[str, str] | None = None, limit: float | None = None
    ) -> tuple[int, str]:
        limit = RUN_LIMIT if limit is None else limit
        process = await asyncio.create_subprocess_exec(
            *argv,
            env=_merged(env),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            async with asyncio.timeout(limit):
                output, _ = await process.communicate()
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
            raise OSError(f"{argv[0]} did not finish within {limit:.0f} s") from None
        return process.returncode or 0, output.decode(errors="replace").strip()

    async def spawn(self, argv: Sequence[str], env: Mapping[str, str] | None = None) -> int | None:
        process = await asyncio.create_subprocess_exec(
            *argv,
            env=_merged(env),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        waiter = asyncio.ensure_future(process.wait())
        done, _ = await asyncio.wait({waiter}, timeout=SPAWN_SETTLE)
        if waiter in done:
            return waiter.result()
        self._background.add(waiter)
        waiter.add_done_callback(self._background.discard)
        return None


def _merged(env: Mapping[str, str] | None) -> dict[str, str] | None:
    return {**os.environ, **env} if env else None
