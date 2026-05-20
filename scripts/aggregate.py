#!/usr/bin/env python3
"""Aggregate member repo metadata into docs/ for docsify rendering."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

import yaml
from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
PROJECTS = DOCS / "projects"
SCHEMA_FILE = ROOT / "scripts" / "schemas" / "project.schema.json"
RAW = "https://raw.githubusercontent.com/{repo}/HEAD/{path}"
API = "https://api.github.com/repos/{repo}/commits?per_page=1"

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")


def http_get(url: str, headers: dict | None = None) -> str | None:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"[warn] {url}: HTTP {e.code}", file=sys.stderr)
        return None
    except urllib.error.URLError as e:
        print(f"[warn] {url}: {e}", file=sys.stderr)
        return None


def fetch_raw(repo: str, path: str) -> str | None:
    return http_get(RAW.format(repo=repo, path=path))


def fetch_activity(repo: str) -> str | None:
    """Return ISO date of latest commit on default branch."""
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    raw = http_get(API.format(repo=repo), headers=headers)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data[0]["commit"]["committer"]["date"] if data else None
    except (json.JSONDecodeError, KeyError, IndexError):
        return None


def local_activity(path: pathlib.Path) -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(path), "log", "-1", "--format=%cI"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() or None
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def relative_time(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    seconds = (datetime.now(timezone.utc) - dt).total_seconds()
    if seconds < 0:
        return ""
    if seconds < 3600:
        return f"{max(1, int(seconds // 60))} 分钟前"
    if seconds < 86400:
        return f"{int(seconds // 3600)} 小时前"
    if seconds < 86400 * 30:
        return f"{int(seconds // 86400)} 天前"
    if seconds < 86400 * 365:
        return f"{int(seconds // (86400 * 30))} 个月前"
    return f"{int(seconds // (86400 * 365))} 年前"


def normalize(meta: dict) -> dict:
    """Coerce YAML-native types into JSON-friendly forms before schema validation."""
    if isinstance(meta.get("updated"), (dt.date, dt.datetime)):
        meta["updated"] = meta["updated"].isoformat()
    return meta


def load_schema() -> Draft202012Validator:
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def validate(meta: dict, source: str, validator: Draft202012Validator) -> bool:
    errors = sorted(validator.iter_errors(meta), key=lambda e: list(e.path))
    if not errors:
        return True
    for e in errors:
        loc = ".".join(str(p) for p in e.path) or "(root)"
        print(f"[bad-yaml] {source}: {loc} — {e.message}", file=sys.stderr)
    return False


def load_remote_project(repo: str, validator: Draft202012Validator) -> dict | None:
    raw = fetch_raw(repo, "project.yaml")
    if not raw:
        print(f"[skip] {repo}: no project.yaml", file=sys.stderr)
        return None
    meta = normalize(yaml.safe_load(raw) or {})
    if not validate(meta, repo, validator):
        return None
    meta["repo"] = repo
    meta["slug"] = repo.replace("/", "__")
    meta["readme_body"] = fetch_raw(repo, meta.get("readme", "README.md")) or ""
    meta["last_commit"] = fetch_activity(repo)
    cover = meta.get("cover")
    if cover and not cover.startswith(("http://", "https://")):
        meta["cover"] = f"https://raw.githubusercontent.com/{repo}/HEAD/{cover}"
    return meta


def load_local_project(path: str, validator: Draft202012Validator) -> dict | None:
    root = pathlib.Path(path).expanduser().resolve()
    yaml_file = root / "project.yaml"
    if not yaml_file.is_file():
        print(f"[skip] {path}: no project.yaml", file=sys.stderr)
        return None
    meta = normalize(yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {})
    if not validate(meta, str(root), validator):
        return None
    repo_id = f"local/{root.name}"
    meta["repo"] = repo_id
    meta["slug"] = repo_id.replace("/", "__").replace(" ", "_")
    readme_path = root / meta.get("readme", "README.md")
    meta["readme_body"] = (
        readme_path.read_text(encoding="utf-8") if readme_path.is_file() else ""
    )
    meta["last_commit"] = local_activity(root)
    return meta


def write_project_page(meta: dict) -> None:
    lines = [
        f"# {meta.get('name', meta['repo'])}\n",
        f"> {meta.get('summary', '')}\n",
        f"- **Repo:** [{meta['repo']}](https://github.com/{meta['repo']})",
        f"- **Authors:** {', '.join(meta.get('authors', []))}",
        f"- **Category:** {meta.get('category', '')}",
        f"- **Tags:** {', '.join(meta.get('tags', []))}",
        f"- **Status:** {meta.get('status', '')}",
        f"- **Updated:** {meta.get('updated', '')}",
    ]
    if meta.get("last_commit"):
        lines.append(f"- **Last commit:** {relative_time(meta['last_commit'])}")
    for k, v in (meta.get("links") or {}).items():
        lines.append(f"- **{k.capitalize()}:** {v}")
    if meta.get("demo"):
        lines.append(f"- **Demo:** {meta['demo']}")
    lines += ["\n---\n", meta["readme_body"]]
    (PROJECTS / f"{meta['slug']}.md").write_text("\n".join(lines), encoding="utf-8")


def sort_key(p: dict) -> str:
    """Sort projects by latest activity desc — newest first."""
    return p.get("last_commit") or p.get("updated") or ""


def render_cards(projects: list[dict]) -> str:
    out = ["# 卡片视图\n", '<div class="card-grid">']
    for p in projects:
        cover = f'<img src="{p["cover"]}" alt="">' if p.get("cover") else ""
        activity = relative_time(p.get("last_commit"))
        activity_html = f' · <span class="activity">{activity}</span>' if activity else ""
        out.append(
            f'<a class="card" href="#/projects/{p["slug"]}">{cover}'
            f'<h3>{p.get("name", p["repo"])}</h3>'
            f'<p>{p.get("summary", "")}</p>'
            f'<small>{", ".join(p.get("authors", []))} · {p.get("category", "")}{activity_html}</small>'
            f"</a>"
        )
    out.append("</div>")
    return "\n".join(out)


def render_list(projects: list[dict]) -> str:
    out: list[str] = ["# 列表视图\n"]
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for p in projects:
        by_cat[p.get("category", "Other")].append(p)
    for cat, items in sorted(by_cat.items()):
        out.append(f"## {cat}\n")
        for p in items:
            activity = relative_time(p.get("last_commit"))
            suffix = f" — _{activity}_" if activity else ""
            out.append(
                f"- [{p.get('name', p['repo'])}](#/projects/{p['slug']}) — "
                f"{p.get('summary', '')} _({', '.join(p.get('authors', []))})_{suffix}"
            )
        out.append("")
    return "\n".join(out)


def render_table(projects: list[dict]) -> str:
    out = [
        "# 表格视图\n",
        "| 名称 | 分类 | 作者 | 状态 | 活跃度 | 简介 |",
        "|---|---|---|---|---|---|",
    ]
    for p in projects:
        activity = relative_time(p.get("last_commit")) or p.get("updated", "")
        out.append(
            f"| [{p.get('name', p['repo'])}](#/projects/{p['slug']}) "
            f"| {p.get('category', '')} | {', '.join(p.get('authors', []))} "
            f"| {p.get('status', '')} | {activity} | {p.get('summary', '')} |"
        )
    return "\n".join(out)


def render_sidebar(projects: list[dict]) -> str:
    out = [
        "- [首页](/)",
        "- 视图",
        "  - [卡片](cards.md)",
        "  - [列表](list.md)",
        "  - [表格](table.md)",
        "- 项目",
    ]
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for p in projects:
        by_cat[p.get("category", "Other")].append(p)
    for cat, items in sorted(by_cat.items()):
        out.append(f"  - {cat}")
        for p in items:
            out.append(f"    - [{p.get('name', p['repo'])}](projects/{p['slug']}.md)")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate MICU AI Lib")
    parser.add_argument(
        "--local",
        action="append",
        default=[],
        metavar="PATH",
        help="本地目录（可重复），仅用于预览，不计入 registry",
    )
    args = parser.parse_args()

    validator = load_schema()
    registry = yaml.safe_load((ROOT / "registry.yaml").read_text(encoding="utf-8")) or {}
    PROJECTS.mkdir(parents=True, exist_ok=True)

    projects: list[dict] = []
    for repo in registry.get("repos", []) or []:
        meta = load_remote_project(repo, validator)
        if meta:
            write_project_page(meta)
            projects.append(meta)
            print(f"[ok] {repo}")

    for path in args.local:
        meta = load_local_project(path, validator)
        if meta:
            write_project_page(meta)
            projects.append(meta)
            print(f"[ok] (local) {path}")

    projects.sort(key=sort_key, reverse=True)

    (DOCS / "cards.md").write_text(render_cards(projects), encoding="utf-8")
    (DOCS / "list.md").write_text(render_list(projects), encoding="utf-8")
    (DOCS / "table.md").write_text(render_table(projects), encoding="utf-8")
    (DOCS / "_sidebar.md").write_text(render_sidebar(projects), encoding="utf-8")
    (DOCS / "_navbar.md").write_text(
        "- [卡片](cards.md)\n- [列表](list.md)\n- [表格](table.md)\n",
        encoding="utf-8",
    )
    print(f"\n[done] {len(projects)} projects aggregated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
