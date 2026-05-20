#!/usr/bin/env python3
"""Append a repo to registry.yaml (idempotent, sorted)."""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "registry.yaml"
REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: add_repo.py owner/repo", file=sys.stderr)
        return 2
    new_repo = sys.argv[1].strip()
    if not REPO_RE.match(new_repo):
        print(f"[error] not a valid owner/repo: {new_repo!r}", file=sys.stderr)
        return 2

    data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    repos = sorted(set((data.get("repos") or []) + [new_repo]))
    already_there = new_repo in (data.get("repos") or [])
    data["repos"] = repos

    REGISTRY.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    msg = "already present" if already_there else "added"
    print(f"[ok] {new_repo}: {msg} ({len(repos)} repos total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
