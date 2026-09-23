"""close_app with psutil, on a process of our own with a unique name (never touches others)."""

import asyncio
import sys
import uuid
from datetime import timedelta

import psutil
import pytest

from kse.engine.processes import PsutilProcesses


def running_names() -> set[str]:
    return {process.info["name"] for process in psutil.process_iter(["name"])}


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="renames itself via /proc")
async def test_closes_our_uniquely_named_process() -> None:
    name = f"kse{uuid.uuid4().hex[:8]}"  # under 16 characters: fits /proc/<pid>/comm
    script = f"open('/proc/self/comm', 'w').write({name!r}); import time; time.sleep(60)"
    process = await asyncio.create_subprocess_exec(sys.executable, "-c", script)
    try:
        for _ in range(500):
            if name in running_names():
                break
            await asyncio.sleep(0.01)
        assert name in running_names(), "the test process did not start"
        assert await PsutilProcesses().close(name, timedelta(seconds=5)) == 1
        assert await asyncio.wait_for(process.wait(), 5) is not None
        assert name not in running_names()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def test_nothing_to_close() -> None:
    name = f"kse{uuid.uuid4().hex[:8]}"
    assert await PsutilProcesses().close(name, timedelta(seconds=1)) == 0
