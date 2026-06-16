#!/usr/bin/env python3
"""Append a repo entry to registry.yaml (idempotent, sorted).

Accepts: owner/repo, github:owner/repo, gitee:owner/repo, or a full
GitHub/Gitee URL (https or git@). Stores GitHub as bare `owner/repo`
and other hosts with a `host:` prefix.
"""
from __future__ import annotations

import argparse
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


def verify_entry(entry: str) -> str | None:
    """Fetch the repo's project.yaml and validate it against the schema.

    Reuses aggregate.py's fetch + parse + validation so the "door" applies
    exactly the same rules the aggregator will. Returns a human-readable
    error string when the entry is unusable, or None when it checks out.
    """
    import aggregate  # same dir; imported lazily so format-only runs stay cheap

    host, repo = aggregate.parse_entry(entry)
    raw = aggregate.fetch_raw(host, repo, "project.yaml")
    if not raw:
        return "拉不到 project.yaml（仓库不存在 / owner/repo 拼错 / 文件缺失 / 仓库非公开）"
    parsed = aggregate.safe_yaml_load(raw, entry)
    if parsed is None:
        return "project.yaml 不是合法的 YAML 映射"
    meta = aggregate.normalize(parsed)
    if not aggregate.validate(meta, entry, aggregate.load_schema()):
        return "project.yaml 不符合 schema（具体字段见上方 [bad-yaml] 行）"
    return None


class IndentedDumper(yaml.SafeDumper):
    """Force sequences nested in mappings to be indented under their key."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="把一个仓库追加进 registry.yaml（幂等、排序）",
    )
    parser.add_argument(
        "entry",
        metavar="owner/repo",
        help="owner/repo | github:owner/repo | gitee:owner/repo | GitHub/Gitee URL",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="跳过 project.yaml 抓取与校验（仅在确认无误、或上游临时不可达时使用）",
    )
    args = parser.parse_args()

    new_entry = normalize_entry(args.entry)
    if not REPO_RE.match(repo_part(new_entry)):
        print(f"[error] not a valid owner/repo: {args.entry!r}", file=sys.stderr)
        return 2

    if not args.no_verify:
        err = verify_entry(new_entry)
        if err:
            print(f"[reject] {new_entry}: {err}", file=sys.stderr)
            print(
                "[reject] 未写入 registry。修正后重试，"
                "或确认无误后用 --no-verify 跳过校验。",
                file=sys.stderr,
            )
            return 1
        print(f"[verify] {new_entry}: project.yaml OK")

    data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8")) or {}
    existing = data.get("repos") or []
    if new_entry in existing:
        print(f"[ok] {new_entry}: already present ({len(existing)} entries total)")
        return 0

    data["repos"] = sorted(set(existing + [new_entry]))
    REGISTRY.write_text(
        yaml.dump(data, Dumper=IndentedDumper, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"[ok] {new_entry}: added ({len(data['repos'])} entries total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
