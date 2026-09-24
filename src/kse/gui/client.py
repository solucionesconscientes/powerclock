"""The GUI's link with the daemon: async requests and the /events stream, turned into Qt
signals. Nothing here blocks the Qt thread."""

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol

import httpx
from PySide6.QtCore import QObject, Signal
from websockets.asyncio.client import connect

from kse.connection import (
    TIMEOUT,
    ApiError,
    DaemonUnavailable,
    Endpoint,
    endpoint,
    error_from,
    unavailable,
)

log = logging.getLogger(__name__)

RETRY_MAX = 10.0  # seconds between attempts to reach a daemon that is not running
DEBOUNCE = 0.15  # seconds: a burst of events causes one refresh

EventStream = Callable[[], AsyncIterator[dict[str, Any]]]


class Api(Protocol):
    async def request(self, method: str, path: str, **kwargs: Any) -> Any: ...

    async def get(self, path: str, **kwargs: Any) -> Any: ...

    async def post(self, path: str, **kwargs: Any) -> Any: ...

    async def put(self, path: str, **kwargs: Any) -> Any: ...

    async def delete(self, path: str, **kwargs: Any) -> Any: ...


class HttpApi:
    """Requests to the daemon. Its address and token are read again after a failure: the
    daemon may have been restarted in the meantime."""

    def __init__(
        self,
        locate: Callable[[], Endpoint] = endpoint,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._locate = locate
        self._transport = transport
        self._http: httpx.AsyncClient | None = None

    def endpoint(self) -> Endpoint:
        return self._locate()

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        http = self._client()
        try:
            response = await http.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            await self.close()
            raise unavailable(exc) from None
        if response.status_code == 401:
            await self.close()  # a new token: read it again next time
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = None
            raise error_from(response.status_code, body, response.text)
        return response.json() if response.content else None

    async def get(self, path: str, **kwargs: Any) -> Any:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> Any:
        return await self.request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> Any:
        return await self.request("PUT", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> Any:
        return await self.request("DELETE", path, **kwargs)

    async def close(self) -> None:
        if self._http is not None:
            http, self._http = self._http, None
            await http.aclose()

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            where = self._locate()  # DaemonUnavailable if it has never run
            self._http = httpx.AsyncClient(
                base_url=where.base_url,
                headers=where.headers,
                timeout=TIMEOUT,
                transport=self._transport,
            )
        return self._http


def event_stream(locate: Callable[[], Endpoint] = endpoint) -> EventStream:
    """Messages of /events; the first one, {"type": "connected"}, marks the connection."""

    async def stream() -> AsyncIterator[dict[str, Any]]:
        where = locate()
        async with connect(
            where.events_url, additional_headers=where.headers, proxy=None, open_timeout=5
        ) as websocket:
            yield {"type": "connected"}
            async for message in websocket:
                yield json.loads(message)

    return stream


class DaemonLink(QObject):
    """Keeps the GUI in step with the daemon: whether it answers, its /health and /pending,
    and every event. The tray and the window only listen to these signals."""

    changed = Signal()  # online, health or pending changed
    event = Signal(dict)  # each /events message (ticks included)

    def __init__(self, api: Api, stream: EventStream | None, debounce: float = DEBOUNCE) -> None:
        super().__init__()
        self.api = api
        self.online = False
        self.error: str | None = None
        self.health: dict[str, Any] | None = None
        self.pending: dict[str, Any] = {"next": [], "active": [], "watching": [], "wake": {}}
        self.fetched_at = 0.0  # time.monotonic() when the current /pending was requested
        self._stream = stream
        self._debounce = debounce
        self._task: asyncio.Task[None] | None = None
        self._refreshing: asyncio.Task[None] | None = None
        self._again = False

    def start(self) -> None:
        if self._stream is not None and self._task is None:
            self._task = asyncio.ensure_future(self._listen())
        self.refresh()

    async def stop(self) -> None:
        for task in (self._task, self._refreshing):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._task = self._refreshing = None

    def refresh(self) -> None:
        """Fetch /health and /pending again soon (several calls in a row cause one fetch;
        a call during a fetch causes another one after it, so nothing is missed)."""
        if self._refreshing is None or self._refreshing.done():
            self._refreshing = asyncio.ensure_future(self._refresh())
        else:
            self._again = True

    async def _refresh(self) -> None:
        while True:
            self._again = False
            await asyncio.sleep(self._debounce)
            started = time.monotonic()
            try:
                health = await self.api.get("/health")
                pending = await self.api.get("/pending")
            except (DaemonUnavailable, ApiError) as exc:
                self._offline(str(exc))
                return
            self.online, self.error, self.health, self.pending = True, None, health, pending
            self.fetched_at = started
            self.changed.emit()
            if not self._again:
                return

    async def _listen(self) -> None:
        assert self._stream is not None
        delay = 1.0
        while True:
            try:
                async for message in self._stream():
                    delay = 1.0
                    if message.get("type") != "tick":
                        self.refresh()  # connected, a run started or ended, a rule changed…
                    self.event.emit(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # refused, closed, no token yet…
                log.debug("event stream: %s", exc)
                self._offline(str(exc))
            await asyncio.sleep(delay)
            delay = min(delay * 2, RETRY_MAX)

    def _offline(self, error: str) -> None:
        if self.online or self.error != error:
            self.online, self.error = False, error
            self.changed.emit()
