"""FastAPI application factory for replay control and ordered streaming."""

from __future__ import annotations

import asyncio
import os
import subprocess
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, model_validator

from argus import CONTRACT_VERSION
from argus.api.replay import ReplayController
from argus.contracts import MetricName
from argus.demo import build_demo_snapshot
from argus.detection.residual import DecompStore
from argus.pipeline import analyze_profile
from argus.policy.approvals import ApprovalStore, ApprovalVerdict
from argus.scenario.profiles import PROFILE_BUILDERS

REPO_ROOT = Path(__file__).resolve().parents[3]


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


class ApprovalRequest(BaseModel):
    verdict: ApprovalVerdict
    by: str


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


def create_app(
    controller: ReplayController | None = None,
    decomp_store: DecompStore | None = None,
) -> FastAPI:
    replay = controller or ReplayController()
    decompositions = decomp_store or DecompStore()
    approvals = ApprovalStore()

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
    app.state.decomp_store = decompositions
    app.state.approvals = approvals

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

    @app.get("/api/decomp")
    async def decomp(
        service: str,
        signal: MetricName,
        from_ts: float,
        to_ts: float,
        max_points: int = 2000,
    ):
        if max_points < 1:
            raise HTTPException(status_code=422, detail="max_points must be positive")
        return [
            frame.model_dump(mode="json")
            for frame in decompositions.query(
                service=service,
                signal=signal,
                from_ts=from_ts,
                to_ts=to_ts,
                max_points=max_points,
            )
        ]

    @app.get("/api/demo")
    async def demo():
        return build_demo_snapshot()

    @app.get("/api/analyze")
    async def analyze_seed(profile: str = "combo_night", seed: int = 424242):
        if profile not in PROFILE_BUILDERS:
            raise HTTPException(status_code=422, detail=f"unknown profile: {profile}")
        findings = await asyncio.to_thread(
            analyze_profile,
            profile=profile,
            seed=seed,
        )
        return [finding.model_dump() for finding in findings]

    @app.get("/api/incidents")
    async def incidents():
        return [item["incident"] for item in build_demo_snapshot()["incidents"]]

    @app.get("/api/incidents/{incident_id}")
    async def incident_detail(incident_id: str):
        for item in build_demo_snapshot()["incidents"]:
            if item["incident"]["incident_id"] == incident_id:
                return item
        raise HTTPException(status_code=404, detail=f"unknown incident: {incident_id}")

    @app.get("/api/incidents/{incident_id}/report", response_class=PlainTextResponse)
    async def incident_report(incident_id: str):
        for item in build_demo_snapshot()["incidents"]:
            if item["incident"]["incident_id"] == incident_id and "report" in item:
                return item["report"]
        raise HTTPException(status_code=404, detail=f"no report for incident: {incident_id}")

    @app.get("/api/audit/actions")
    async def audit_actions(incident_id: str | None = None):
        rows = build_demo_snapshot()["audit"]
        if incident_id is None:
            return rows
        return [row for row in rows if row.get("incident_id") == incident_id]

    @app.get("/api/audit/export.ndjson", response_class=PlainTextResponse)
    async def audit_export():
        return (
            "\n".join(
                __import__("json").dumps(row, sort_keys=True)
                for row in build_demo_snapshot()["audit"]
            )
            + "\n"
        )

    @app.get("/api/mttr")
    async def mttr():
        return [build_demo_snapshot()["mttr"]]

    @app.post("/api/approvals/{decision_id}")
    async def approve(decision_id: str, request: ApprovalRequest):
        decisions = {
            item["decision"]["decision_id"]: item["decision"]
            for item in build_demo_snapshot()["incidents"]
        }
        if decision_id not in decisions:
            raise HTTPException(status_code=404, detail=f"unknown decision: {decision_id}")
        try:
            approval = approvals.resolve(
                decision_id,
                verdict=request.verdict,
                by=request.by,
                ts=float(decisions[decision_id]["ts"]),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return asdict(approval)

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

    dashboard_dist = REPO_ROOT / "dashboard" / "dist"
    if dashboard_dist.is_dir():
        app.mount("/", StaticFiles(directory=dashboard_dist, html=True), name="dashboard")

    return app


app = create_app()
