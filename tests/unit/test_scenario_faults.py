"""P3.4 real-commit fault cascades and operational-fault tests."""

from dataclasses import replace

import numpy as np
import pytest
from argus.config import CONFIG
from argus.scenario.base import build_scenario_header, generate_base_load
from argus.scenario.faults import (
    FaultSpec,
    OperationalFaultSpec,
    OperationalFaultType,
    apply_code_faults,
    apply_operational_faults,
    deploy_record,
    load_fault_catalog,
)

SCORED_FROM_TS = 1789430400.0


@pytest.fixture()
def base_world():
    config = replace(CONFIG.scenario, warmup_hours=0, scenario_hours=1)
    header = build_scenario_header(
        seed=31,
        profile="cascade_night",
        scored_from_ts=SCORED_FROM_TS,
        config=config,
    )
    return config, generate_base_load(np.random.default_rng(31), header, config=config)


def _fault(fault_id: str) -> FaultSpec:
    return FaultSpec(
        fault_id=fault_id,
        deploy_ts=SCORED_FROM_TS + 100,
        onset_ts=SCORED_FROM_TS + 300,
        end_ts=SCORED_FROM_TS + 700,
        severity=1.0,
    )


def test_deploy_records_use_real_materialized_hashes_and_citations():
    catalog = load_fault_catalog()
    record = deploy_record(catalog["F1"], _fault("F1"))

    assert len(record.commit) == 40
    assert record.commit == "45d03f4c223f73f50eefac8d010b9f533cc4c69c"
    assert record.files == ["payment_svc/retry.py"]
    assert catalog["F1"].line == 18


@pytest.mark.parametrize(
    ("fault_id", "service", "field"),
    [
        ("F1", "notify-svc", "rps"),
        ("F2", "auth-svc", "conn_active"),
        ("F3", "catalog-svc", "p99_ms"),
        ("F4", "notify-svc", "mem_pct"),
        ("F5", "catalog-svc", "cpu_pct"),
        ("F6", "edge-gw", "queue_depth"),
    ],
)
def test_each_code_fault_has_its_mechanistic_local_signature(
    base_world,
    fault_id: str,
    service: str,
    field: str,
):
    config, base = base_world
    result = apply_code_faults(base, [_fault(fault_id)], config=config)
    index = 500

    assert getattr(result.metrics[service], field)[index] > getattr(base[service], field)[index]
    assert result.deploys[0].commit == load_fault_catalog()[fault_id].commit
    assert result.logs[0].msg


def test_retry_storm_cascades_from_notify_through_payment_to_edge(base_world):
    config, base = base_world
    result = apply_code_faults(base, [_fault("F1")], config=config)
    index = 500

    assert result.metrics["notify-svc"].rps[index] > base["notify-svc"].rps[index]
    assert result.metrics["payment-svc"].err_rate[index] > base["payment-svc"].err_rate[index]
    assert result.metrics["edge-gw"].err_rate[index] > base["edge-gw"].err_rate[index]
    assert result.traces[0].caller == "payment-svc"
    assert result.traces[0].callee == "notify-svc"


def test_operational_capacity_loss_has_no_deploy_and_propagates(base_world):
    config, base = base_world
    spec = OperationalFaultSpec(
        fault_id="ops-capacity",
        fault_type=OperationalFaultType.CAPACITY_LOSS,
        onset_ts=SCORED_FROM_TS + 300,
        end_ts=SCORED_FROM_TS + 700,
        severity=1.0,
        service="catalog-svc",
    )
    result = apply_operational_faults(base, [spec], config=config)
    index = 500

    assert result.deploys == []
    assert result.metrics["catalog-svc"].p99_ms[index] > base["catalog-svc"].p99_ms[index]
    assert result.metrics["edge-gw"].p99_ms[index] > base["edge-gw"].p99_ms[index]
    assert result.metrics["catalog-svc"].p99_ms[0] == base["catalog-svc"].p99_ms[0]
    assert result.logs[0].template_id == "CAPACITY_LOSS"


def test_operational_link_brownout_emits_edge_trace(base_world):
    config, base = base_world
    spec = OperationalFaultSpec(
        fault_id="ops-link",
        fault_type=OperationalFaultType.LINK_BROWNOUT,
        onset_ts=SCORED_FROM_TS + 300,
        end_ts=SCORED_FROM_TS + 700,
        severity=0.8,
        caller="edge-gw",
        callee="catalog-svc",
    )
    result = apply_operational_faults(base, [spec], config=config)

    assert result.deploys == []
    assert result.traces[0].caller == "edge-gw"
    assert result.traces[0].callee == "catalog-svc"
    assert result.traces[0].err_rate > 0
