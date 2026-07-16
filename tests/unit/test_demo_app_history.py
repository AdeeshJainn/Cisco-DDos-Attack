"""demo-app history: determinism and fault-citation integrity.

The scripted timeline (demo-app/history/) must materialize to byte-stable
commit hashes on every machine, every fault's file:line citation must hold
in the tree as of its fault commit, and the lock file must agree with the
actual git log. The pinned HEAD hash makes CI (a different machine) prove
cross-machine stability on every run.
"""

import hashlib
import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
DEMO_APP = REPO / "demo-app"
SCRIPT = REPO / "scripts" / "build_demo_app.py"
LOCK_PATH = DEMO_APP / ".manifest.lock.json"

# Byte-stable across machines by construction; changes only when the
# timeline itself is deliberately edited (update alongside the manifest).
EXPECTED_HEAD = "31553e3d797f1b4073e7cac82f69841b3bcb80f7"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_demo_app", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = _load_builder()


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture(scope="module")
def manifest() -> dict:
    with open(DEMO_APP / "history" / "manifest.yaml") as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def built(manifest, tmp_path_factory) -> tuple[Path, dict[str, str]]:
    work = tmp_path_factory.mktemp("demo_app_build")
    hashes = builder.build(work, manifest)
    return work, hashes


def test_double_build_gives_identical_pinned_head(manifest, built, tmp_path):
    work, hashes = built
    second = tmp_path / "second"
    second.mkdir()
    hashes2 = builder.build(second, manifest)
    assert hashes == hashes2
    assert git(work, "rev-parse", "HEAD") == EXPECTED_HEAD
    assert git(second, "rev-parse", "HEAD") == EXPECTED_HEAD


def test_pinned_dates_and_identities(manifest, built):
    work, hashes = built
    authors = manifest["authors"]
    for commit in manifest["commits"]:
        who = authors[commit["author"]]
        shown = git(work, "show", "-s", "--format=%an|%ae|%aI|%cI", hashes[commit["id"]])
        name, email, author_date, committer_date = shown.split("|")
        assert (name, email) == (who["name"], who["email"]), commit["id"]
        assert author_date == committer_date == commit["date"], commit["id"]


def test_fault_citations_hold_in_faulted_trees(manifest, built):
    work, hashes = built
    for fid, fault in manifest["faults"].items():
        tree = git(work, "show", f"{hashes[fault['commit']]}:{fault['file']}")
        line = tree.splitlines()[fault["line"] - 1]
        assert re.search(fault["pattern"], line), (
            f"{fid}: {fault['file']}:{fault['line']} = {line!r}"
        )


def test_fix_commits_restore_the_tracked_baseline(manifest, built):
    work, hashes = built
    for fid, fault in manifest["faults"].items():
        fixed = git(work, "show", f"{hashes[fault['fix_commit']]}:{fault['file']}")
        baseline = (DEMO_APP / fault["file"]).read_text()
        assert fixed + "\n" == baseline, f"{fid}: fix does not restore {fault['file']}"


def test_lock_agrees_with_git_log(manifest, built):
    work, hashes = built
    lock = builder.build_lock(manifest, hashes)
    log_oldest_first = git(work, "log", "--reverse", "--format=%H").splitlines()
    assert list(lock["commits"].values()) == log_oldest_first
    assert lock["head"] == log_oldest_first[-1]
    for fid, fault in lock["faults"].items():
        assert fault["commit"] in log_oldest_first, fid
        assert fault["file"].startswith(
            tuple(
                f"{d}/" for d in ("edge_gw", "auth_svc", "catalog_svc", "payment_svc", "notify_svc")
            )
        ), fid


@pytest.mark.skipif(not LOCK_PATH.exists(), reason="demo-app not materialized (run make setup)")
def test_installed_lock_is_current(manifest):
    lock = json.loads(LOCK_PATH.read_text())
    manifest_sha = hashlib.sha256((DEMO_APP / "history" / "manifest.yaml").read_bytes()).hexdigest()
    assert lock["manifest_sha256"] == manifest_sha, "stale lock: re-run make setup"
    assert lock["head"] == EXPECTED_HEAD
    if (DEMO_APP / ".git").exists():
        assert git(DEMO_APP, "rev-parse", "HEAD") == lock["head"]
