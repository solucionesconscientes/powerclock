"""The `run` action with real (harmless) subprocesses: the current Python interpreter."""

import asyncio
import sys
from pathlib import Path

import psutil

from kse.engine.clock import FakeClock
from kse.engine.executor import Executor
from kse.engine.runs import Run
from support import MADRID, rule, until_sleeping

PY = sys.executable


def command(*cmd: str, **options: object) -> dict[str, object]:
    return {"type": "run", "cmd": list(cmd), **options}


async def run_steps(executor: Executor, *steps: dict[str, object]) -> Run:
    run = executor.start(rule(actions=list(steps)), MADRID, cause="manual")
    return await executor.wait(run.id)


async def test_success_keeps_the_output(executor: Executor) -> None:
    run = await run_steps(executor, command(PY, "-c", "print('hola'); print('adiós')"))
    assert run.state == "done"
    assert run.steps[0].detail == "hola\nadiós"


async def test_non_zero_exit_fails(executor: Executor) -> None:
    run = await run_steps(executor, command(PY, "-c", "import sys; print('boom'); sys.exit(3)"))
    assert run.state == "failed"
    assert run.steps[0].detail == "exit code 3: boom"


async def test_missing_program_fails(executor: Executor) -> None:
    run = await run_steps(executor, command("/nonexistent/kse-command"))
    assert run.state == "failed"
    assert "No such file" in (run.steps[0].detail or "")


async def test_cwd_and_env(executor: Executor, tmp_path: Path) -> None:
    script = "import os; print(os.getcwd()); print(os.environ['KSE_TEST'])"
    step = command(PY, "-c", script, cwd=str(tmp_path), env={"KSE_TEST": "valor"})
    run = await run_steps(executor, step)
    assert run.steps[0].detail == f"{tmp_path}\nvalor"


async def test_shell(executor: Executor) -> None:
    run = await run_steps(executor, command("echo uno && echo dos", shell=True))
    assert run.steps[0].detail == "uno\ndos"


async def test_no_wait_runs_in_the_background(executor: Executor) -> None:
    run = await run_steps(executor, command(PY, "-c", "pass", wait=False))
    assert run.state == "done"
    assert (run.steps[0].detail or "").startswith("started in the background")
    for _ in range(200):  # let the background command end before the test does
        if not executor.background:
            break
        await asyncio.sleep(0.01)
    assert executor.background == 0


async def test_timeout_stops_the_command(executor: Executor, clock: FakeClock) -> None:
    run = executor.start(
        rule(actions=[command(PY, "-c", "import time; time.sleep(60)", timeout="1m")]),
        MADRID,
        cause="manual",
    )
    await until_sleeping(clock)  # the command is running and its timer is armed
    await clock.advance(60)
    run = await executor.wait(run.id)
    assert run.state == "failed"
    assert run.steps[0].detail == "timed out after 1m"


async def test_cancel_stops_the_command(
    executor: Executor, clock: FakeClock, tmp_path: Path
) -> None:
    pid_file = tmp_path / "pid"
    script = (
        f"import os, time; open({str(pid_file)!r}, 'w').write(str(os.getpid())); time.sleep(60)"
    )
    run = executor.start(
        rule(actions=[command(PY, "-c", script, timeout="1h")]), MADRID, cause="manual"
    )
    await until_sleeping(clock)
    for _ in range(200):
        if pid_file.exists() and pid_file.read_text():
            break
        await asyncio.sleep(0.01)
    pid = int(pid_file.read_text())
    assert executor.cancel(run.id)
    run = await executor.wait(run.id)
    assert run.state == "cancelled"
    assert not psutil.pid_exists(pid)
