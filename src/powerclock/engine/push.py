"""Messages out of the computer (the push step): ntfy, Telegram or any webhook, over HTTPS
with httpx. Nothing here depends on the operating system."""

import base64
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from powerclock.engine import variables
from powerclock.models import PushStep

TIMEOUT = 20.0  # seconds
NTFY_PRIORITY = {"low": "2", "default": "3", "high": "4", "urgent": "5"}
TELEGRAM = "https://api.telegram.org/bot{token}/sendMessage"

ClientFactory = Callable[[], httpx.AsyncClient]


class PushError(Exception):
    """The service did not take the message (the reason goes to the history)."""


def default_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True)


async def push(
    step: PushStep,
    values: Mapping[str, str],
    secrets: Mapping[str, str],
    client: ClientFactory = default_client,
) -> str:
    """Send it; returns where it went (for the history). Raises PushError."""
    title = variables.expand(step.title, values)
    message = variables.expand(step.message, values) or title
    async with client() as http:
        try:
            match step.service:
                case "ntfy":
                    assert step.url is not None
                    headers = {"Title": _header(title), "Priority": NTFY_PRIORITY[step.priority]}
                    reply = await http.post(step.url, content=message.encode(), headers=headers)
                    where = step.url.rsplit("/", 1)[-1]
                case "telegram":
                    token = secrets.get("telegram_token")
                    if not token:
                        raise PushError(
                            "there is no telegram_token: powerclock secrets set telegram_token"
                        )
                    text = f"{title}\n{message}" if message != title else title
                    body: dict[str, Any] = {"chat_id": step.chat, "text": text}
                    reply = await http.post(TELEGRAM.format(token=token), json=body)
                    where = f"telegram {step.chat}"
                case "webhook":
                    assert step.url is not None
                    body = {"title": title, "message": message, "rule": values.get("rule")}
                    reply = await http.post(step.url, json=body)
                    where = httpx.URL(step.url).host
        except httpx.HTTPError as exc:
            raise PushError(f"{step.service}: {exc}") from exc
    if reply.status_code >= 400:
        raise PushError(f"{step.service} answered {reply.status_code}: {reply.text[:200]}")
    return where


def _header(text: str) -> str:
    """HTTP header values go as ASCII: ntfy reads other titles written as RFC 2047."""
    if text.isascii():
        return text
    return "=?UTF-8?B?" + base64.b64encode(text.encode()).decode() + "?="
