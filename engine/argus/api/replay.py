"""Replay clock with speed control, pause and seek over scenario files."""

from __future__ import annotations

import asyncio
import gzip
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from argus.config import CONFIG
from argus.contracts import (
    ClockPayload,
    ClockState,
    ScenarioHeader,
    parse_scenario_line,
)
from argus.scenario.generate import generate

from .stream import OrderedStreamHub


class ScenarioReader:
    """Re-openable deterministic iterator over a compressed scenario."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            self.header = parse_scenario_line(next(stream))
        if not isinstance(self.header, ScenarioHeader):
            raise ValueError("scenario first line must be a header")

    def iter_from(self, sim_ts: float):
        with gzip.open(self.path, "rt", encoding="utf-8") as stream:
            next(stream)
            for raw in stream:
                record = parse_scenario_line(raw)
                if record.ts >= sim_ts:
                    yield record


@dataclass
class ReplayClock:
    speed: int = 60
    state: ClockState = ClockState.LOADING
    sim_ts: float = 0.0

    def snapshot(self) -> ClockPayload:
        return ClockPayload(speed=self.speed, state=self.state, sim_ts=self.sim_ts)

    def set_speed(self, speed: int) -> ClockPayload:
        if speed not in {1, 10, 60}:
            raise ValueError("speed must be 1, 10 or 60")
        self.speed = speed
        return self.snapshot()

    def play(self) -> ClockPayload:
        self.state = ClockState.PLAYING
        return self.snapshot()

    def pause(self) -> ClockPayload:
        self.state = ClockState.PAUSED
        return self.snapshot()

    def seek(self, sim_ts: float, header: ScenarioHeader) -> ClockPayload:
        if not header.start_ts <= sim_ts <= header.end_ts:
            raise ValueError("seek timestamp outside scenario")
        self.sim_ts = sim_ts
        return self.snapshot()


class ReplayController:
    """Own the loaded scenario, clock and background stream pump."""

    def __init__(self, hub: OrderedStreamHub | None = None) -> None:
        self.hub = hub or OrderedStreamHub()
        self.clock = ReplayClock()
        self.reader: ScenarioReader | None = None
        self._task: asyncio.Task[None] | None = None

    async def load_file(self, path: Path) -> ScenarioHeader:
        await self._cancel_task()
        self.reader = ScenarioReader(path)
        self.clock.state = ClockState.PAUSED
        # Warmup calibrates detectors during load; the visible replay starts at
        # scored_from_ts so 48 hours of coarse history are never wall-clock paced.
        self.clock.sim_ts = self.reader.header.scored_from_ts
        await self.hub.publish(self.clock.snapshot(), sim_ts=self.clock.sim_ts)
        return self.reader.header

    async def load_profile(
        self,
        *,
        profile: str,
        seed: int,
        output_dir: Path,
    ) -> ScenarioHeader:
        artifacts = await asyncio.to_thread(
            generate,
            seed=seed,
            profile=profile,
            output_dir=output_dir,
        )
        return await self.load_file(artifacts.scenario_path)

    async def play(self) -> ClockPayload:
        self._require_reader()
        payload = self.clock.play()
        await self.hub.publish(payload, sim_ts=payload.sim_ts)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())
        return payload

    async def pause(self) -> ClockPayload:
        payload = self.clock.pause()
        await self.hub.publish(payload, sim_ts=payload.sim_ts)
        return payload

    async def set_speed(self, speed: int) -> ClockPayload:
        payload = self.clock.set_speed(speed)
        await self.hub.publish(payload, sim_ts=payload.sim_ts)
        return payload

    async def seek(self, sim_ts: float) -> ClockPayload:
        reader = self._require_reader()
        was_playing = self.clock.state is ClockState.PLAYING
        await self._cancel_task()
        payload = self.clock.seek(sim_ts, reader.header)
        await self.hub.publish(payload, sim_ts=payload.sim_ts)
        if was_playing:
            self.clock.play()
            self._task = asyncio.create_task(self._run())
        return self.clock.snapshot()

    async def close(self) -> None:
        await self._cancel_task()

    def _require_reader(self) -> ScenarioReader:
        if self.reader is None:
            raise RuntimeError("no scenario loaded")
        return self.reader

    async def _cancel_task(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        reader = self._require_reader()
        previous_ts = self.clock.sim_ts
        try:
            for record in reader.iter_from(self.clock.sim_ts):
                while self.clock.state is ClockState.PAUSED:
                    await asyncio.sleep(CONFIG.replay.pause_poll_s)
                delay = max(0.0, (record.ts - previous_ts) / self.clock.speed)
                if delay:
                    await asyncio.sleep(delay)
                self.clock.sim_ts = record.ts
                previous_ts = record.ts
                await self.hub.publish(record, sim_ts=record.ts)
            self.clock.state = ClockState.ENDED
            await self.hub.publish(self.clock.snapshot(), sim_ts=self.clock.sim_ts)
        except asyncio.CancelledError:
            raise
