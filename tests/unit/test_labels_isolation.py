"""The labels-isolation lint keeps the argus tree clean today and provably
catches imports of the ground-truth writer and label-path literals."""

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "lint_labels_isolation", REPO / "scripts" / "lint_labels_isolation.py"
)
lint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lint)


def _write(tmp_path: Path, rel: str, source: str) -> None:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_argus_tree_is_clean():
    assert lint.find_violations() == []


def test_catches_from_import_of_labels(tmp_path):
    _write(tmp_path, "detection/peek.py", "from argus.scenario import labels\n")
    violations = lint.find_violations(tmp_path)
    assert len(violations) == 1
    assert "imports labels module" in str(violations[0])


def test_catches_dotted_import_of_labels(tmp_path):
    _write(tmp_path, "verdict/rules.py", "import argus.scenario.labels as gt\n")
    assert lint.find_violations(tmp_path)


def test_catches_relative_import_of_labels(tmp_path):
    _write(tmp_path, "rca/incidents.py", "from .labels import everything\n")
    assert lint.find_violations(tmp_path)


def test_catches_labels_path_literal(tmp_path):
    _write(tmp_path, "rca/collapse.py", 'PATH = "match_night.labels.json"\n')
    violations = lint.find_violations(tmp_path)
    assert len(violations) == 1
    assert "label path" in str(violations[0])


def test_catches_steplabels_path_literal(tmp_path):
    _write(tmp_path, "policy/decide.py", 'FRAME = load("match_night.steplabels.parquet")\n')
    assert lint.find_violations(tmp_path)


def test_producer_package_is_exempt(tmp_path):
    _write(tmp_path, "scenario/labels.py", 'SUFFIX = ".labels.json"\n')
    _write(tmp_path, "scenario/generate.py", "from argus.scenario import labels\n")
    assert lint.find_violations(tmp_path) == []
