#!/usr/bin/env python3
"""Append a repo entry to registry.yaml (idempotent, sorted).

Accepts: owner/repo, github:owner/repo, gitee:owner/repo, or a full
GitHub/Gitee URL (https or git@). Stores GitHub as bare `owner/repo`
and other hosts with a `host:` prefix.
"""
from __future__ import annotations

import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "registry.yaml"
REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")

URL_PREFIXES = [
    ("https://github.com/", "github"),
    ("http://github.com/",  "github"),
    ("git@github.com:",     "github"),
    ("https://gitee.com/",  "gitee"),
    ("http://gitee.com/",   "gitee"),
    ("git@gitee.com:",      "gitee"),
]


def normalize_entry(arg: str) -> str:
    """Normalize user input into the registry's canonical form."""
    s = arg.strip().rstrip("/")
    if s.endswith(".git"):
        s = s[:-4]

    if s.startswith(("github:", "gitee:")):
        return s

    for prefix, host in URL_PREFIXES:
        if s.startswith(prefix):
            repo = s[len(prefix):]
            return repo if host == "github" else f"{host}:{repo}"

    return s  # bare owner/repo, assume github


def repo_part(entry: str) -> str:
    return entry.split(":", 1)[1] if ":" in entry else entry


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: add_repo.py owner/repo|<github-or-gitee-url>", file=sys.stderr)
        return 2
    new_entry = normalize_entry(sys.argv[1])
    if not REPO_RE.match(repo_part(new_entry)):
        print(f"[error] not a valid owner/repo: {sys.argv[1]!r}", file=sys.stderr)
        return 2

    data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    existing = data.get("repos") or []
    already_there = new_entry in existing
    repos = sorted(set(existing + [new_entry]))
    data["repos"] = repos

    REGISTRY.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    msg = "already present" if already_there else "added"
    print(f"[ok] {new_entry}: {msg} ({len(repos)} entries total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
