"""P3.7 replay clock, ordered catch-up and API skeleton tests."""

import asyncio
from dataclasses import replace

from argus.api.app import create_app
from argus.api.replay import ReplayClock, ReplayController, ScenarioReader
from argus.api.stream import OrderedStreamHub
from argus.config import CONFIG
from argus.contracts import ClockState, MetricRecord, ScenarioHeader
from argus.scenario.generate import generate


def test_clock_speed_pause_play_and_bounded_seek():
    header = ScenarioHeader(
        contract="v1.0",
        seed=1,
        profile="quiet_day",
        start_ts=0.0,
        scored_from_ts=10.0,
        end_ts=20.0,
        resolution_s=1.0,
        warmup_resolution_s=5.0,
        services=["edge-gw"],
        demo_app_manifest=".manifest.lock.json",
    )
    clock = ReplayClock()

    assert clock.pause().state is ClockState.PAUSED
    assert clock.play().state is ClockState.PLAYING
    assert clock.set_speed(10).speed == 10
    assert clock.seek(15.0, header).sim_ts == 15.0


def test_ordered_hub_catch_up_is_monotonic_and_bounded():
    async def exercise():
        hub = OrderedStreamHub(buffer_size=3)
        for ts in range(5):
            await hub.publish(
                MetricRecord(ts=ts, service="edge-gw", name="rps", value=1.0),
                sim_ts=ts,
            )
        registration = await hub.register(since_seq=2)
        await hub.unregister(registration.queue)
        return hub, registration

    hub, registration = asyncio.run(exercise())
    assert [item.seq for item in registration.backlog] == [3, 4]
    assert [item.seq for item in hub.catch_up(0)] == [2, 3, 4]


def test_reader_replays_same_order_from_seek_point(tmp_path):
    config = replace(
        CONFIG.scenario,
        warmup_hours=0,
        scenario_hours=1,
        resolution_s=60,
    )
    artifacts = generate(
        seed=5,
        profile="quiet_day",
        output_dir=tmp_path,
        config=config,
    )
    reader = ScenarioReader(artifacts.scenario_path)
    records = list(reader.iter_from(reader.header.scored_from_ts + 120))

    assert records
    assert records[0].ts == reader.header.scored_from_ts + 120
    assert all(left.ts <= right.ts for left, right in zip(records, records[1:], strict=False))


def test_controller_loads_file_and_publishes_clock(tmp_path):
    config = replace(
        CONFIG.scenario,
        warmup_hours=0,
        scenario_hours=1,
        resolution_s=60,
    )
    artifacts = generate(
        seed=6,
        profile="quiet_day",
        output_dir=tmp_path,
        config=config,
    )

    async def exercise():
        controller = ReplayController()
        header = await controller.load_file(artifacts.scenario_path)
        return controller, header

    controller, header = asyncio.run(exercise())
    assert controller.clock.state is ClockState.PAUSED
    assert controller.hub.latest_seq == 0
    assert header.seed == 6


def test_app_exposes_required_replay_and_stream_routes():
    app = create_app()
    paths = {route.path for route in app.routes}

    assert {
        "/api/health",
        "/api/version",
        "/api/replay/load",
        "/api/replay/play",
        "/api/replay/pause",
        "/api/replay/speed",
        "/api/replay/seek",
        "/ws/stream",
    } <= paths
