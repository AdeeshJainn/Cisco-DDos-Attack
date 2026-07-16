"""Guard: the argus pipeline must never read ground-truth labels.

The scenario generator (argus/scenario/) authors ground truth by
construction, so it is the only package allowed to reference label modules
and label file paths. Everything else under argus/ — detection, verdict,
rca, policy, audit, api and the root modules — must neither import a labels
module nor mention *.labels.* / *steplabels* paths. Scoring and tests
consume labels from outside argus/, so they are out of scope here.

Usage: python scripts/lint_labels_isolation.py [root]
Exits 0 when clean, 1 with one "path:line: offence" per finding otherwise.
"""

import argparse
import ast
import sys
from pathlib import Path
from typing import NamedTuple

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "engine" / "argus"

# Module segments that identify the ground-truth writer and its artifacts.
FORBIDDEN_SEGMENTS = frozenset({"labels", "steplabels"})
# Substrings that identify label files on disk (see the scenario contract:
# <name>.labels.json and <name>.steplabels.parquet).
FORBIDDEN_PATH_FRAGMENTS = (".labels.", "steplabels")
# The producer package, relative to the argus root.
PRODUCER_PACKAGE = "scenario"


class Violation(NamedTuple):
    path: Path
    line: int
    offence: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.offence}"


def _module_segments(module: str | None) -> set[str]:
    return set(module.split(".")) if module else set()


def _check_tree(path: Path, tree: ast.AST) -> list[Violation]:
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _module_segments(alias.name) & FORBIDDEN_SEGMENTS:
                    violations.append(
                        Violation(path, node.lineno, f"imports labels module '{alias.name}'")
                    )
        elif isinstance(node, ast.ImportFrom):
            hit = _module_segments(node.module) & FORBIDDEN_SEGMENTS
            hit |= {alias.name for alias in node.names} & FORBIDDEN_SEGMENTS
            if hit:
                source = node.module or "."
                violations.append(
                    Violation(path, node.lineno, f"imports labels module (from {source})")
                )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            for fragment in FORBIDDEN_PATH_FRAGMENTS:
                if fragment in node.value:
                    violations.append(
                        Violation(path, node.lineno, f"references label path {node.value!r}")
                    )
    return violations


def find_violations(root: Path = DEFAULT_ROOT) -> list[Violation]:
    violations: list[Violation] = []
    for source_file in sorted(root.rglob("*.py")):
        relative = source_file.relative_to(root)
        if relative.parts and relative.parts[0] == PRODUCER_PACKAGE:
            continue
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        violations.extend(_check_tree(relative, tree))
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()

    violations = find_violations(args.root)
    for violation in violations:
        print(violation, file=sys.stderr)
    if violations:
        print(f"labels isolation: {len(violations)} violation(s)", file=sys.stderr)
        return 1
    print("labels isolation: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
