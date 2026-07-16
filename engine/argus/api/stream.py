"""Ordered WebSocket hub with sequence numbers and buffered catch-up."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from argus.config import CONFIG
from argus.contracts import WsEnvelope


@dataclass(frozen=True)
class StreamRegistration:
    queue: asyncio.Queue[WsEnvelope]
    backlog: tuple[WsEnvelope, ...]


class OrderedStreamHub:
    """Fan out one monotonic sequence with bounded reconnect history."""

    def __init__(self, buffer_size: int = CONFIG.replay.stream_buffer_size) -> None:
        if buffer_size < 1:
            raise ValueError("buffer_size must be positive")
        self._buffer: deque[WsEnvelope] = deque(maxlen=buffer_size)
        self._subscribers: set[asyncio.Queue[WsEnvelope]] = set()
        self._next_seq = 0
        self._lock = asyncio.Lock()

    @property
    def latest_seq(self) -> int:
        return self._next_seq - 1

    async def publish(self, payload: Any, *, sim_ts: float) -> WsEnvelope:
        async with self._lock:
            envelope = WsEnvelope(
                seq=self._next_seq,
                wall_ts=time.time(),
                sim_ts=sim_ts,
                payload=payload,
            )
            self._next_seq += 1
            self._buffer.append(envelope)
            subscribers = tuple(self._subscribers)
        for queue in subscribers:
            await queue.put(envelope)
        return envelope

    async def register(self, since_seq: int | None = None) -> StreamRegistration:
        """Atomically subscribe and snapshot messages after ``since_seq``."""
        queue: asyncio.Queue[WsEnvelope] = asyncio.Queue()
        async with self._lock:
            self._subscribers.add(queue)
            backlog = tuple(
                item for item in self._buffer if since_seq is None or item.seq > since_seq
            )
        return StreamRegistration(queue=queue, backlog=backlog)

    async def unregister(self, queue: asyncio.Queue[WsEnvelope]) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    def catch_up(self, since_seq: int) -> tuple[WsEnvelope, ...]:
        return tuple(item for item in self._buffer if item.seq > since_seq)
