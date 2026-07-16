"""Consistency checks for demo-app/topology.yaml.

The topology file is the single world model: the scenario generator reads
per-service scale and capacity from it, and root-cause analysis walks its
call edges. These tests pin the properties both consumers assume, and tie
the service names to the frozen contract fixtures.
"""

import json
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
DEMO_APP = REPO / "demo-app"
HEADER_FIXTURE = REPO / "tests" / "fixtures" / "contracts" / "scenario_header.json"


@pytest.fixture(scope="module")
def topology() -> dict:
    with open(DEMO_APP / "topology.yaml") as fh:
        return yaml.safe_load(fh)


def test_services_match_contract_header_fixture(topology):
    with open(HEADER_FIXTURE) as fh:
        header = json.load(fh)
    assert set(topology["services"]) == set(header["services"])


def test_service_dirs_exist_with_code(topology):
    for name, spec in topology["services"].items():
        service_dir = DEMO_APP / spec["dir"]
        assert service_dir.is_dir(), f"{name}: missing directory {spec['dir']}"
        assert list(service_dir.glob("*.py")), f"{name}: no python files in {spec['dir']}"


def test_service_numbers_sane(topology):
    ports = []
    for name, spec in topology["services"].items():
        assert spec["replicas"] >= 1, name
        assert spec["base_rps"] > 0, name
        assert spec["capacity_rps"] > spec["base_rps"], f"{name}: no headroom over base load"
        assert spec["max_conns"] > 0, name
        ports.append(spec["port"])
    assert len(ports) == len(set(ports)), "service ports must be unique"


def test_edges_reference_declared_services(topology):
    services = set(topology["services"])
    for edge in topology["edges"]:
        assert edge["caller"] in services, edge
        assert edge["callee"] in services, edge
        assert edge["caller"] != edge["callee"], f"self-edge: {edge}"
        assert 0 < edge["calls_per_request"] <= 1.0, edge


def test_call_graph_shape(topology):
    edges = {(edge["caller"], edge["callee"]) for edge in topology["edges"]}
    assert edges == {
        ("edge-gw", "auth-svc"),
        ("edge-gw", "catalog-svc"),
        ("edge-gw", "payment-svc"),
        ("payment-svc", "notify-svc"),
    }


def test_base_rates_consistent_with_call_ratios(topology):
    """Each callee's base_rps ≈ traffic implied by its incoming edges."""
    services = topology["services"]
    implied: dict[str, float] = {}
    for edge in topology["edges"]:
        caller_rps = services[edge["caller"]]["base_rps"]
        implied[edge["callee"]] = (
            implied.get(edge["callee"], 0.0) + caller_rps * edge["calls_per_request"]
        )
    for callee, rps in implied.items():
        declared = services[callee]["base_rps"]
        assert abs(rps - declared) / declared < 0.25, (
            f"{callee}: declared base_rps {declared} vs {rps:.0f} implied by call ratios"
        )
