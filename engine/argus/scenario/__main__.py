"""Command line interface for scenario generation."""

from __future__ import annotations

import argparse
from pathlib import Path

from argus.scenario.generate import generate
from argus.scenario.profiles import PROFILE_BUILDERS


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m argus.scenario")
    subcommands = parser.add_subparsers(dest="command", required=True)
    generate_parser = subcommands.add_parser("generate")
    generate_parser.add_argument("--seed", type=int, required=True)
    generate_parser.add_argument("--profile", choices=PROFILE_BUILDERS, required=True)
    generate_parser.add_argument("--output-dir", type=Path, default=Path("scenarios"))
    args = parser.parse_args()

    artifacts = generate(
        seed=args.seed,
        profile=args.profile,
        output_dir=args.output_dir,
    )
    print(artifacts.scenario_path)
    print(artifacts.labels_path)
    print(artifacts.step_labels_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
