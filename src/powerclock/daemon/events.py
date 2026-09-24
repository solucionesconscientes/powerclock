"""Fan-out of engine and daemon events to every /events WebSocket client."""

import asyncio
import contextlib
from collections.abc import Iterator

from powerclock.engine.runs import Event

QUEUE_SIZE = 256


class EventHub:
    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[Event]] = set()

    def publish(self, event: Event) -> None:
        for queue in list(self._queues):
            if queue.full():  # a slow client loses its oldest events, never blocks the daemon
                queue.get_nowait()
            queue.put_nowait(event)

    @contextlib.contextmanager
    def subscribe(self) -> Iterator[asyncio.Queue[Event]]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._queues.add(queue)
        try:
            yield queue
        finally:
            self._queues.discard(queue)

    @property
    def subscribers(self) -> int:
        return len(self._queues)
