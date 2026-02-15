#!/usr/bin/env python3
"""Org baseline policy verifier.

Machine-truth source: northroot-workspaces/baselines/registry.json

Commands:
  schema         Validate registry shape.
  verify-tags    Verify pinned tags resolve and are annotated tags.
  check-publish  Enforce protected-branch publish policy for one repo/ref.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def run(cmd: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(cmd)}\n{result.stderr.strip()}"
        )
    return result.stdout.strip()


@dataclass
class Registry:
    path: Path
    data: dict[str, Any]

    @property
    def policy(self) -> dict[str, Any]:
        return self.data["policy"]

    @property
    def repos(self) -> dict[str, Any]:
        return self.data["repos"]

    @property
    def buckets(self) -> dict[str, Any]:
        return self.data["buckets"]


def load_registry(path: Path) -> Registry:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return Registry(path=path, data=data)


def validate_schema(reg: Registry) -> None:
    required_top = {"schema_version", "org", "policy", "buckets", "repos"}
    missing = required_top - set(reg.data.keys())
    if missing:
        raise ValueError(f"registry missing keys: {sorted(missing)}")

    if not isinstance(reg.data["schema_version"], int):
        raise ValueError("schema_version must be int")

    policy = reg.policy
    for k in (
        "require_annotated_tags",
        "protected_branch_patterns",
        "default_required_bucket_for_protected",
    ):
        if k not in policy:
            raise ValueError(f"policy missing key: {k}")

    if not isinstance(policy["protected_branch_patterns"], list):
        raise ValueError("policy.protected_branch_patterns must be list")

    if policy["default_required_bucket_for_protected"] not in reg.buckets:
        raise ValueError("default_required_bucket_for_protected not present in buckets")

    if not isinstance(reg.repos, dict) or not reg.repos:
        raise ValueError("repos must be a non-empty object")

    for repo_name, repo_cfg in reg.repos.items():
        if "/" not in repo_name:
            raise ValueError(f"repo key must look like org/repo: {repo_name}")
        if "pins" not in repo_cfg:
            raise ValueError(f"{repo_name}: missing pins")
        req_bucket = repo_cfg.get(
            "required_bucket_for_protected", policy["default_required_bucket_for_protected"]
        )
        if req_bucket not in reg.buckets:
            raise ValueError(f"{repo_name}: unknown required bucket {req_bucket}")
        if not isinstance(repo_cfg["pins"], dict):
            raise ValueError(f"{repo_name}: pins must be object")

        for bucket_name, pin in repo_cfg["pins"].items():
            if bucket_name not in reg.buckets:
                raise ValueError(f"{repo_name}: unknown bucket in pins: {bucket_name}")
            if not isinstance(pin, dict):
                raise ValueError(f"{repo_name}:{bucket_name} pin must be object")
            if "tag" not in pin or "sha" not in pin:
                raise ValueError(f"{repo_name}:{bucket_name} pin must contain tag and sha")


def repo_local_path(workspace_root: Path, repo_full_name: str) -> Path:
    _, repo_name = repo_full_name.split("/", 1)
    return workspace_root / "repos" / repo_name


def resolve_tag_commit(repo_dir: Path, tag_name: str, require_annotated: bool) -> str:
    tag_ref = f"refs/tags/{tag_name}"
    obj_type = run(["git", "cat-file", "-t", tag_ref], cwd=repo_dir)
    if require_annotated and obj_type != "tag":
        raise ValueError(
            f"{repo_dir.name}: tag {tag_name} is {obj_type}; annotated tags required"
        )
    commit_sha = run(["git", "rev-list", "-n", "1", tag_name], cwd=repo_dir)
    if not commit_sha:
        raise ValueError(f"{repo_dir.name}: unable to resolve commit for tag {tag_name}")
    return commit_sha


def verify_tags(reg: Registry, workspace_root: Path) -> None:
    require_annotated = bool(reg.policy["require_annotated_tags"])
    checked = 0
    for repo_full_name, repo_cfg in reg.repos.items():
        repo_dir = repo_local_path(workspace_root, repo_full_name)
        if not repo_dir.exists():
            continue
        pins = repo_cfg.get("pins", {})
        for bucket_name, pin in pins.items():
            tag_name = (pin.get("tag") or "").strip()
            expected_sha = (pin.get("sha") or "").strip()
            if not tag_name:
                continue
            commit_sha = resolve_tag_commit(repo_dir, tag_name, require_annotated)
            if expected_sha and commit_sha != expected_sha:
                raise ValueError(
                    f"{repo_full_name}:{bucket_name} expected {expected_sha}, got {commit_sha} "
                    f"from tag {tag_name}"
                )
            checked += 1
    print(f"verify-tags: ok ({checked} pinned tag(s) checked)")


def is_protected_branch(reg: Registry, branch_name: str) -> bool:
    for pattern in reg.policy["protected_branch_patterns"]:
        if fnmatch.fnmatch(branch_name, pattern):
            return True
    return False


def check_publish(
    reg: Registry,
    workspace_root: Path,
    repo_full_name: str,
    branch: str,
    head: str,
    fetch_remote: bool,
) -> None:
    repo_cfg = reg.repos.get(repo_full_name)
    if not repo_cfg:
        raise ValueError(f"repo not found in registry: {repo_full_name}")

    if not is_protected_branch(reg, branch):
        print(f"check-publish: non-protected branch {branch}; policy not required")
        return

    req_bucket = repo_cfg.get(
        "required_bucket_for_protected",
        reg.policy["default_required_bucket_for_protected"],
    )
    pin = repo_cfg.get("pins", {}).get(req_bucket)
    if not pin:
        raise ValueError(
            f"{repo_full_name}: missing pin for required bucket {req_bucket} on protected branch"
        )

    tag_name = (pin.get("tag") or "").strip()
    expected_sha = (pin.get("sha") or "").strip()
    if not tag_name:
        raise ValueError(f"{repo_full_name}:{req_bucket} pin missing tag")
    if not expected_sha:
        raise ValueError(f"{repo_full_name}:{req_bucket} pin missing sha")

    repo_dir = repo_local_path(workspace_root, repo_full_name)
    if not repo_dir.exists():
        raise ValueError(f"local repo path missing: {repo_dir}")

    if fetch_remote:
        run(["git", "fetch", "--prune", "--tags", "origin"], cwd=repo_dir)

    pin_sha = resolve_tag_commit(repo_dir, tag_name, bool(reg.policy["require_annotated_tags"]))
    if pin_sha != expected_sha:
        raise ValueError(
            f"{repo_full_name}:{req_bucket} pin sha mismatch: expected {expected_sha}, tag resolved {pin_sha}"
        )

    head_sha = run(["git", "rev-parse", head], cwd=repo_dir)
    # Ensure the baseline pin is ancestor of the commit being pushed.
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", pin_sha, head_sha],
        cwd=str(repo_dir),
        check=False,
    )
    if proc.returncode != 0:
        raise ValueError(
            f"{repo_full_name}: head {head_sha} is not descendant of {req_bucket} baseline {pin_sha}"
        )

    print(
        f"check-publish: ok ({repo_full_name} {branch} head={head_sha} "
        f"descends-from {req_bucket}:{pin_sha})"
    )


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Verify org baseline policy")
    p.add_argument(
        "--workspace-root",
        default=os.environ.get("NORTHROOT_WORKSPACE", "."),
        help="Workspace root path (default: NORTHROOT_WORKSPACE or .)",
    )
    p.add_argument(
        "--registry",
        default="northroot-workspaces/baselines/registry.json",
        help="Path to baseline registry JSON (relative to workspace root unless absolute)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("schema", help="Validate registry schema")
    sub.add_parser("verify-tags", help="Verify pinned tags/sha integrity")

    pub = sub.add_parser("check-publish", help="Check protected-branch publish gate")
    pub.add_argument("--repo", required=True, help="Repo full name, e.g. Northroot-Labs/clearlyops")
    pub.add_argument("--branch", required=True, help="Branch name, e.g. main")
    pub.add_argument("--head", default="HEAD", help="Head ref/sha to validate (default HEAD)")
    pub.add_argument(
        "--no-fetch",
        action="store_true",
        help="Disable remote fetch before protected-branch checks (default fetches origin)",
    )
    return p


def main() -> int:
    args = parser().parse_args()
    workspace_root = Path(args.workspace_root).resolve()
    registry_path = Path(args.registry)
    if not registry_path.is_absolute():
        registry_path = workspace_root / registry_path
    reg = load_registry(registry_path)

    try:
        validate_schema(reg)
        if args.cmd == "schema":
            print("schema: ok")
            return 0
        if args.cmd == "verify-tags":
            verify_tags(reg, workspace_root)
            return 0
        if args.cmd == "check-publish":
            check_publish(
                reg,
                workspace_root,
                args.repo,
                args.branch,
                args.head,
                fetch_remote=(not args.no_fetch),
            )
            return 0
        raise ValueError(f"unknown command: {args.cmd}")
    except Exception as exc:  # pylint: disable=broad-except
        print(f"baseline-verify: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
