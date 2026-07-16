"""Bulk deterministic scenario generation for evaluation seeds."""

from __future__ import annotations

import argparse
from pathlib import Path

from argus.scenario.generate import generate
from argus.scenario.profiles import PROFILE_BUILDERS


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--start-seed", type=int, default=1)
    parser.add_argument("--profile", choices=PROFILE_BUILDERS, default="match_night")
    parser.add_argument("--output-dir", type=Path, default=Path("scenarios"))
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be at least one")

    for seed in range(args.start_seed, args.start_seed + args.count):
        artifacts = generate(
            seed=seed,
            profile=args.profile,
            output_dir=args.output_dir,
        )
        print(artifacts.scenario_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
