"""Deterministic offline fix proposal from the real repair commit."""

from __future__ import annotations

import subprocess
from pathlib import Path

from argus.contracts import ProposedFix
from argus.scenario.faults import FaultCatalogEntry

DEFAULT_DEMO_APP_PATH = Path(__file__).resolve().parents[3] / "demo-app"


def propose_fix(
    entry: FaultCatalogEntry,
    *,
    demo_app_path: Path = DEFAULT_DEMO_APP_PATH,
) -> ProposedFix:
    diff = subprocess.check_output(
        [
            "git",
            "-C",
            str(demo_app_path),
            "show",
            "--format=",
            "--no-ext-diff",
            entry.fix_commit,
            "--",
            entry.file,
        ],
        text=True,
    ).strip()
    if not diff:
        raise ValueError(f"repair commit {entry.fix_commit} has no diff for {entry.file}")
    return ProposedFix(
        summary=(
            f"Apply the verified repair for {entry.mechanism.replace('_', ' ')} in {entry.file}."
        ),
        diff=diff,
    )
