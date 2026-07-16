"""Materialize demo-app/.git from the scripted timeline — deterministically.

Applies demo-app/history/patches in manifest order with pinned author and
committer identities and dates, so every machine produces byte-identical
commit hashes. Because the timeline's last commit restores the tracked tree
(every fault commit is reverted), installing the resulting .git leaves the
checkout clean.

Outputs:
  demo-app/.git                  — the materialized history
  demo-app/.manifest.lock.json   — fault_id -> {commit, file, line, function, ...}
                                   with manifest ids resolved to real hashes;
                                   consumed by the scenario deploy feed and tests

Run directly or via `make setup`. Safe to re-run: the history is rebuilt
from scratch each time and verified against the tracked files before the
old .git (if any) is replaced.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
DEMO_APP = REPO / "demo-app"
HISTORY = DEMO_APP / "history"
LOCK_PATH = DEMO_APP / ".manifest.lock.json"

# Files under demo-app/ that belong to the outer repo, not the storefront's
# own history; the materialized repo ignores them via .git/info/exclude.
INNER_EXCLUDES = ["/history/", "/.manifest.lock.json", "__pycache__/"]


def run_git(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    cmd = ["git", "-c", "core.excludesfile=/dev/null", "-c", "commit.gpgsign=false", *args]
    res = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{res.stdout}{res.stderr}")
    return res.stdout


def tracked_tree(root: Path) -> dict[str, bytes]:
    """The demo-app files the storefront history must end at."""
    skip = {"history", ".git", "__pycache__", ".manifest.lock.json"}
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and not (set(p.relative_to(root).parts) & skip)
    }


def build(work: Path, manifest: dict) -> dict[str, str]:
    """Apply the timeline in `work`; return manifest id -> commit hash."""
    run_git(["init", "-q", "-b", "main"], work)
    authors = manifest["authors"]
    hashes: dict[str, str] = {}
    for commit in manifest["commits"]:
        patch = HISTORY / "patches" / commit["patch"]
        run_git(["apply", str(patch)], work)
        run_git(["add", "-A"], work)
        who = authors[commit["author"]]
        env = {
            "GIT_AUTHOR_NAME": who["name"],
            "GIT_AUTHOR_EMAIL": who["email"],
            "GIT_AUTHOR_DATE": commit["date"],
            "GIT_COMMITTER_NAME": who["name"],
            "GIT_COMMITTER_EMAIL": who["email"],
            "GIT_COMMITTER_DATE": commit["date"],
            # keep host git config out of the hash inputs
            "HOME": str(work),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "PATH": os.environ["PATH"],
        }
        message = commit["message"]
        if commit.get("body"):
            message += "\n\n" + commit["body"].rstrip("\n")
        run_git(["commit", "-q", "-m", message], work, env=env)
        hashes[commit["id"]] = run_git(["rev-parse", "HEAD"], work).strip()
    return hashes


def patch_files(patch_name: str) -> list[str]:
    """Paths a patch touches (from its `diff --git` headers)."""
    files = []
    for line in (HISTORY / "patches" / patch_name).read_text().splitlines():
        if line.startswith("diff --git a/"):
            files.append(line.split(" b/", 1)[1])
    return files


def build_lock(manifest: dict, hashes: dict[str, str]) -> dict:
    topology = yaml.safe_load((DEMO_APP / "topology.yaml").read_text())
    dir_to_service = {spec["dir"]: name for name, spec in topology["services"].items()}
    commits_by_id = {c["id"]: c for c in manifest["commits"]}
    faults = {}
    for fid, fault in manifest["faults"].items():
        fault_commit = commits_by_id[fault["commit"]]
        fix_commit = commits_by_id[fault["fix_commit"]]
        faults[fid] = {
            "sub_type": fault["sub_type"],
            "mechanism": fault["mechanism"],
            "commit": hashes[fault["commit"]],
            "fix_commit": hashes[fault["fix_commit"]],
            "file": fault["file"],
            "line": fault["line"],
            "function": fault["function"],
            "pattern": fault["pattern"],
            "service": dir_to_service[fault["file"].split("/", 1)[0]],
            "author": fault_commit["author"],
            "summary": fault_commit["message"],
            "files": patch_files(fault_commit["patch"]),
            "fix_summary": fix_commit["message"],
        }
    manifest_sha = hashlib.sha256((HISTORY / "manifest.yaml").read_bytes()).hexdigest()
    return {
        "generated_by": "scripts/build_demo_app.py",
        "manifest_sha256": manifest_sha,
        "head": hashes[manifest["commits"][-1]["id"]],
        "commits": hashes,
        "faults": faults,
    }


def main() -> None:
    manifest = yaml.safe_load((HISTORY / "manifest.yaml").read_text())
    expected = tracked_tree(DEMO_APP)

    with tempfile.TemporaryDirectory(prefix="demo-app-history-") as tmp:
        work = Path(tmp)
        hashes = build(work, manifest)

        built = tracked_tree(work)
        if built != expected:
            diff = sorted(set(built) ^ set(expected)) or sorted(
                rel for rel in expected if built.get(rel) != expected[rel]
            )
            raise SystemExit(
                "history does not end at the tracked demo-app tree "
                f"(every fault must be reverted). Mismatched files: {diff}"
            )

        if (DEMO_APP / ".git").exists():
            shutil.rmtree(DEMO_APP / ".git")
        shutil.move(str(work / ".git"), str(DEMO_APP / ".git"))

    exclude = DEMO_APP / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("".join(f"{line}\n" for line in INNER_EXCLUDES))

    dirty = run_git(["status", "--porcelain"], DEMO_APP).strip()
    if dirty:
        raise SystemExit(f"materialized demo-app checkout is not clean:\n{dirty}")

    lock = build_lock(manifest, hashes)
    LOCK_PATH.write_text(json.dumps(lock, indent=2) + "\n")

    print(f"demo-app history materialized: {len(hashes)} commits, HEAD {lock['head'][:12]}")
    for fid, fault in sorted(lock["faults"].items()):
        print(
            f"  {fid} {fault['sub_type']}: {fault['commit'][:12]} {fault['file']}:{fault['line']}"
        )


if __name__ == "__main__":
    sys.exit(main())
