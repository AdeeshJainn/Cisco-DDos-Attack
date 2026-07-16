"""FastAPI application factory for replay control and ordered streaming."""

from __future__ import annotations

import os
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, model_validator

from argus import CONTRACT_VERSION
from argus.api.replay import ReplayController
from argus.scenario.profiles import PROFILE_BUILDERS


class ReplayLoadRequest(BaseModel):
    profile: str | None = None
    seed: int = 0
    file: Path | None = None

    @model_validator(mode="after")
    def _one_source(self) -> ReplayLoadRequest:
        if (self.profile is None) == (self.file is None):
            raise ValueError("provide exactly one of profile or file")
        if self.profile is not None and self.profile not in PROFILE_BUILDERS:
            raise ValueError(f"unknown profile: {self.profile}")
        return self


class ReplaySpeedRequest(BaseModel):
    speed: int


class ReplaySeekRequest(BaseModel):
    sim_ts: float


def _git_sha() -> str:
    configured = os.getenv("ARGUS_GIT_SHA")
    if configured:
        return configured
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def create_app(controller: ReplayController | None = None) -> FastAPI:
    replay = controller or ReplayController()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        profile = os.getenv("ARGUS_PROFILE")
        if profile:
            await replay.load_profile(
                profile=profile,
                seed=int(os.getenv("ARGUS_SEED", "0")),
                output_dir=Path(os.getenv("ARGUS_SCENARIO_DIR", "var/scenarios")),
            )
            await replay.set_speed(int(os.getenv("ARGUS_SPEED", "60")))
            await replay.play()
        yield
        await replay.close()

    app = FastAPI(title="Argus", version="0.1.0", lifespan=lifespan)
    app.state.replay = replay

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/version")
    async def version():
        return {"version": app.version, "contract": CONTRACT_VERSION, "git_sha": _git_sha()}

    @app.post("/api/replay/load")
    async def load(request: ReplayLoadRequest):
        try:
            if request.file is not None:
                header = await replay.load_file(request.file)
            else:
                header = await replay.load_profile(
                    profile=request.profile or "quiet_day",
                    seed=request.seed,
                    output_dir=Path("var/scenarios"),
                )
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return header.model_dump(mode="json")

    @app.post("/api/replay/play")
    async def play():
        try:
            return (await replay.play()).model_dump(mode="json")
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/replay/pause")
    async def pause():
        return (await replay.pause()).model_dump(mode="json")

    @app.post("/api/replay/speed")
    async def speed(request: ReplaySpeedRequest):
        try:
            return (await replay.set_speed(request.speed)).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/replay/seek")
    async def seek(request: ReplaySeekRequest):
        try:
            return (await replay.seek(request.sim_ts)).model_dump(mode="json")
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.websocket("/ws/stream")
    async def stream(websocket: WebSocket, since_seq: int | None = Query(default=None)):
        await websocket.accept()
        registration = await replay.hub.register(since_seq)
        try:
            for envelope in registration.backlog:
                await websocket.send_json(envelope.model_dump(mode="json"))
            while True:
                envelope = await registration.queue.get()
                await websocket.send_json(envelope.model_dump(mode="json"))
        except WebSocketDisconnect:
            pass
        finally:
            await replay.hub.unregister(registration.queue)

    return app


app = create_app()
