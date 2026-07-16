"""Localize deploy-correlated failures through real demo-app diffs."""

from __future__ import annotations

import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from argus.config import CONFIG, RcaConfig
from argus.contracts import CodeFaultFinding, DeployRecord
from argus.scenario.faults import FaultCatalogEntry, load_fault_catalog

from .fixer import DEFAULT_DEMO_APP_PATH, propose_fix


@dataclass(frozen=True)
class LocalizationCandidate:
    entry: FaultCatalogEntry
    score: float
    config_value: str | None


def localize(
    *,
    service: str,
    onset_ts: float,
    deploys: list[DeployRecord],
    demo_app_path: Path = DEFAULT_DEMO_APP_PATH,
    config: RcaConfig = CONFIG.rca,
) -> CodeFaultFinding:
    catalog = {entry.commit: entry for entry in load_fault_catalog().values()}
    candidates = []
    for deploy in deploys:
        age = onset_ts - deploy.ts
        entry = catalog.get(deploy.commit)
        if (
            deploy.service != service
            or entry is None
            or age < 0.0
            or age > config.deploy_lookback_s
        ):
            continue
        source = subprocess.check_output(
            [
                "git",
                "-C",
                str(demo_app_path),
                "show",
                f"{entry.commit}:{entry.file}",
            ],
            text=True,
        )
        match = re.search(entry.pattern, source, re.MULTILINE)
        pattern_hit = float(match is not None)
        overlap = float(entry.file in deploy.files)
        recency = math.exp(-age / config.deploy_decay_s)
        candidates.append(
            LocalizationCandidate(
                entry=entry,
                score=pattern_hit * overlap * recency,
                config_value=match.group(0).strip() if match else None,
            )
        )
    if not candidates:
        raise ValueError(f"no localizable deploy for {service} before {onset_ts}")
    winner = max(candidates, key=lambda item: (item.score, item.entry.commit))
    if winner.score <= 0.0:
        raise ValueError(f"deploy candidates for {service} did not match their diffs")
    entry = winner.entry
    return CodeFaultFinding(
        commit=entry.commit,
        file=entry.file,
        line=entry.line,
        function=entry.function,
        config_value=winner.config_value,
        mechanism=entry.mechanism.replace("_", " "),
        proposed_fix=propose_fix(entry, demo_app_path=demo_app_path),
    )
