"""Messages out of the computer (push), questions with buttons (ask) and the steps that run
when a step fails, against a simulated HTTP server and the fake backend."""

import json
import stat
from pathlib import Path
from typing import Any

import httpx
import pytest

from powerclock.config import Paths, read_secrets, write_secret
from powerclock.engine.clock import FakeClock, settle
from powerclock.engine.evaluator import Evaluator
from powerclock.engine.executor import Executor
from powerclock.platform.fake import FakePlatform
from support import MADRID, rule


class Server:
    """Records requests and answers them (a stand-in for ntfy, Telegram or a webhook)."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.requests: list[httpx.Request] = []

    def client(self) -> httpx.AsyncClient:
        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(self.status, text="nope" if self.status >= 400 else "ok")

        return httpx.AsyncClient(transport=httpx.MockTransport(handle))


@pytest.fixture
def server() -> Server:
    return Server()


@pytest.fixture
def secrets() -> dict[str, str]:
    return {"telegram_token": "123:abc"}


@pytest.fixture
async def notifier(
    fake: FakePlatform,
    evaluator: Evaluator,
    clock: FakeClock,
    server: Server,
    secrets: dict[str, str],
) -> Any:
    executor = Executor(fake, evaluator, clock, secrets=lambda: secrets, http=server.client)
    yield executor
    await executor.shutdown()


async def run_steps(executor: Executor, *steps: dict[str, Any], **fields: Any) -> Any:
    started = executor.start(rule(actions=list(steps), **fields), MADRID, cause="manual")
    return await executor.wait(started.id)


# ── push ──────────────────────────────────────────────────────────────────────


async def test_ntfy(notifier: Executor, server: Server) -> None:
    step = {
        "type": "push",
        "url": "https://ntfy.sh/mi-tema",
        "title": "Copia {date}",
        "message": "Terminada: {rule}",
        "priority": "high",
    }
    run = await run_steps(notifier, step)
    assert run.state == "done"
    assert run.steps[0].detail == "mi-tema"
    [request] = server.requests
    assert str(request.url) == "https://ntfy.sh/mi-tema"
    assert request.content == b"Terminada: test"
    assert (request.headers["Title"], request.headers["Priority"]) == ("Copia 2026-09-24", "4")


async def test_ntfy_titles_with_accents(notifier: Executor, server: Server) -> None:
    await run_steps(notifier, {"type": "push", "url": "https://ntfy.sh/t", "title": "Medicación"})
    assert server.requests[0].headers["Title"].startswith("=?UTF-8?B?")


async def test_telegram_uses_the_secret_token(notifier: Executor, server: Server) -> None:
    await run_steps(
        notifier, {"type": "push", "service": "telegram", "chat": "42", "title": "Hola"}
    )
    [request] = server.requests
    assert str(request.url) == "https://api.telegram.org/bot123:abc/sendMessage"
    assert json.loads(request.content) == {"chat_id": "42", "text": "Hola"}


async def test_telegram_without_a_token(
    notifier: Executor, secrets: dict[str, str], server: Server
) -> None:
    secrets.clear()
    run = await run_steps(notifier, {"type": "push", "service": "telegram", "chat": "42"})
    assert run.state == "failed"
    assert "powerclock secrets set telegram_token" in (run.reason or "")
    assert server.requests == []


async def test_webhook_and_a_refusal(notifier: Executor, server: Server) -> None:
    await run_steps(
        notifier,
        {
            "type": "push",
            "service": "webhook",
            "url": "http://ha.local:8123/api/webhook/x",
            "message": "m",
        },
    )
    assert json.loads(server.requests[0].content) == {
        "title": "PowerClock",
        "message": "m",
        "rule": "test",
    }
    server.status = 500
    run = await run_steps(notifier, {"type": "push", "url": "https://ntfy.sh/t"})
    assert run.state == "failed"
    assert "ntfy answered 500" in (run.reason or "")


# ── if a step fails ───────────────────────────────────────────────────────────


async def test_failure_steps_get_the_error(notifier: Executor, server: Server) -> None:
    run = await run_steps(
        notifier,
        {"type": "run", "cmd": ["false"]},
        {"type": "notify", "title": "not reached"},
        on_failure=[{"type": "push", "url": "https://ntfy.sh/t", "message": "{rule}: {error}"}],
    )
    assert run.state == "failed"
    assert [(s.type, s.on_failure) for s in run.steps] == [("run", False), ("push", True)]
    assert server.requests[0].content.decode() == "test: step 1 (run) failed: exit code 1"


async def test_no_failure_no_failure_steps(notifier: Executor, server: Server) -> None:
    run = await run_steps(
        notifier,
        {"type": "notify", "title": "fine"},
        on_failure=[{"type": "push", "url": "https://ntfy.sh/t"}],
    )
    assert run.state == "done"
    assert server.requests == []


# ── ask ───────────────────────────────────────────────────────────────────────


async def test_ask_goes_on_with_the_right_answer(notifier: Executor, fake: FakePlatform) -> None:
    fake.notify_response = "0"  # the first button
    ask = {"type": "ask", "title": "¿Unirte?", "buttons": ["Unirme", "Ahora no"], "go_on": "Unirme"}
    run = await run_steps(notifier, ask, {"type": "open", "target": "https://meet"})
    assert run.state == "done"
    assert run.steps[0].detail == "answered 'Unirme'"
    assert fake.calls_to("open")


async def test_ask_stops_with_another_answer(notifier: Executor, fake: FakePlatform) -> None:
    fake.notify_response = "1"
    ask = {"type": "ask", "title": "¿Unirte?", "buttons": ["Unirme", "Ahora no"], "go_on": "Unirme"}
    run = await run_steps(notifier, ask, {"type": "open", "target": "https://meet"})
    assert run.state == "done"
    assert run.steps[0].detail == "answered 'Ahora no': the rule stops here"
    assert fake.calls_to("open") == []


async def test_ask_reminds_until_the_timeout(
    notifier: Executor, fake: FakePlatform, clock: FakeClock
) -> None:
    fake.notify_response = None  # closed without an answer
    ask = {
        "type": "ask",
        "title": "Pastilla",
        "buttons": ["Hecho"],
        "repeat": "5m",
        "timeout": "15m",
    }
    run = notifier.start(rule(actions=[ask]), MADRID, cause="manual")
    for _ in range(3):
        await clock.advance(300)
        await settle()
    assert run.state == "done"
    assert len(fake.calls_to("notify")) == 3  # shown again every 5 minutes
    assert run.steps[0].detail == "no answer after 15m: the rule stops here"


# ── secrets ───────────────────────────────────────────────────────────────────


def test_secrets_file(tmp_path: Path) -> None:
    paths = Paths(tmp_path, tmp_path)
    assert read_secrets(paths) == {}
    write_secret(paths, "telegram_token", "123:abc")
    assert read_secrets(paths) == {"telegram_token": "123:abc"}
    assert stat.S_IMODE(paths.secrets.stat().st_mode) == 0o600
    write_secret(paths, "telegram_token", None)
    assert read_secrets(paths) == {}
    with pytest.raises(ValueError, match="lowercase"):
        write_secret(paths, "../x", "y")


def test_push_needs_where() -> None:
    with pytest.raises(ValueError, match="ntfy needs the url"):
        rule(actions=[{"type": "push"}])
    with pytest.raises(ValueError, match="telegram needs the chat"):
        rule(actions=[{"type": "push", "service": "telegram"}])
    with pytest.raises(ValueError, match="go_on must be one of the buttons"):
        rule(actions=[{"type": "ask", "title": "x", "buttons": ["A"], "go_on": "B"}])
