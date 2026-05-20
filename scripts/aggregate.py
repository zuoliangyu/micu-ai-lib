#!/usr/bin/env python3
"""Aggregate member repo metadata into docs/ for docsify rendering.

Registry entries can be plain `owner/repo` (GitHub, default) or
`gitee:owner/repo` (Gitee). Local previews go through --local PATH.
"""
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

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITEE_TOKEN = os.environ.get("GITEE_TOKEN")

# ---------------- HTTP ---------------- #


def http_get(url: str, headers: dict | None = None, retries: int = 1) -> str | None:
    """GET with one automatic retry on transient errors (timeout, 5xx)."""
    req = urllib.request.Request(url, headers=headers or {})
    last_err: str | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None  # 404 isn't transient — don't retry, don't warn
            if 500 <= e.code < 600 and attempt < retries:
                last_err = f"HTTP {e.code}"
                continue
            print(f"[warn] {url}: HTTP {e.code}", file=sys.stderr)
            return None
        except urllib.error.URLError as e:
            last_err = str(e)
            if attempt < retries:
                continue
            print(f"[warn] {url}: {last_err}", file=sys.stderr)
            return None
    return None


# ---------------- Host adapters ---------------- #

_gitee_branch_cache: dict[str, str] = {}


def parse_entry(entry: str) -> tuple[str, str]:
    """Return (host, owner/repo). Bare `owner/repo` defaults to github."""
    if ":" in entry and not entry.startswith(("http://", "https://")):
        host, repo = entry.split(":", 1)
        if host in ("github", "gitee"):
            return host, repo
    return "github", entry


def gitee_default_branch(repo: str) -> str:
    if repo in _gitee_branch_cache:
        return _gitee_branch_cache[repo]
    raw = http_get(f"https://gitee.com/api/v5/repos/{repo}")
    branch = "master"
    if raw:
        try:
            branch = json.loads(raw).get("default_branch") or "master"
        except json.JSONDecodeError:
            pass
    _gitee_branch_cache[repo] = branch
    return branch


def fetch_raw(host: str, repo: str, path: str) -> str | None:
    if host == "github":
        return http_get(f"https://raw.githubusercontent.com/{repo}/HEAD/{path}")
    if host == "gitee":
        branch = gitee_default_branch(repo)
        return http_get(f"https://gitee.com/{repo}/raw/{branch}/{path}")
    return None


def fetch_activity(host: str, repo: str) -> str | None:
    """Return ISO date of latest commit on default branch."""
    if host == "github":
        headers = {"Accept": "application/vnd.github+json"}
        if GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
        raw = http_get(f"https://api.github.com/repos/{repo}/commits?per_page=1", headers=headers)
    elif host == "gitee":
        url = f"https://gitee.com/api/v5/repos/{repo}/commits?per_page=1"
        if GITEE_TOKEN:
            url += f"&access_token={GITEE_TOKEN}"
        raw = http_get(url)
    else:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data[0]["commit"]["committer"]["date"] if data else None
    except (json.JSONDecodeError, KeyError, IndexError):
        return None


def web_url(host: str, repo: str) -> str:
    if host == "github":
        return f"https://github.com/{repo}"
    if host == "gitee":
        return f"https://gitee.com/{repo}"
    return ""


def cover_url(host: str, repo: str, cover: str) -> str:
    if host == "github":
        return f"https://raw.githubusercontent.com/{repo}/HEAD/{cover}"
    if host == "gitee":
        branch = gitee_default_branch(repo)
        return f"https://gitee.com/{repo}/raw/{branch}/{cover}"
    return cover


def make_slug(host: str, repo: str) -> str:
    """github stays bare for backward compat; other hosts get prefix."""
    repo_slug = repo.replace("/", "__")
    return repo_slug if host == "github" else f"{host}__{repo_slug}"


def host_badge(host: str) -> str:
    return {"github": "GitHub", "gitee": "Gitee"}.get(host, host)


# ---------------- Local git fallback ---------------- #


def local_activity(path: pathlib.Path) -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(path), "log", "-1", "--format=%cI"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() or None
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


# ---------------- Misc ---------------- #


def relative_time(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        dt_ = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    seconds = (datetime.now(timezone.utc) - dt_).total_seconds()
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


def _to_list(v) -> list[str]:
    """Forgive `authors: cjh` (string) and `tags: 'a, b'` (comma string)."""
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        parts = [p.strip() for p in v.split(",")]
        return [p for p in parts if p]
    return [str(v)]


def normalize(meta: dict) -> dict:
    """Coerce YAML-native types and drop empty fields before schema validation.

    Tolerated mistakes:
      - `key:` with no value (becomes None) is treated as missing
      - `authors: cjh` (string) is coerced to `[cjh]`
      - `tags: "a, b"` is split to `[a, b]`
      - `updated:` as date/datetime is ISO-stringified
    """
    meta = {k: v for k, v in meta.items() if v is not None and v != ""}
    for key in ("authors", "tags"):
        if key in meta:
            meta[key] = _to_list(meta[key])
    if isinstance(meta.get("updated"), (dt.date, dt.datetime)):
        meta["updated"] = meta["updated"].isoformat()
    return meta


def safe_yaml_load(text: str, source: str) -> dict | None:
    """Parse YAML; on error report and return None so the build doesn't crash."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        print(f"[bad-yaml] {source}: parse error — {e}", file=sys.stderr)
        return None
    if data is None:
        return {}
    if not isinstance(data, dict):
        print(f"[bad-yaml] {source}: top level must be a mapping, got {type(data).__name__}", file=sys.stderr)
        return None
    return data


def load_schema() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_FILE.read_text(encoding="utf-8")))


def validate(meta: dict, source: str, validator: Draft202012Validator) -> bool:
    errors = sorted(validator.iter_errors(meta), key=lambda e: list(e.path))
    if not errors:
        return True
    for e in errors:
        loc = ".".join(str(p) for p in e.path) or "(root)"
        print(f"[bad-yaml] {source}: {loc} — {e.message}", file=sys.stderr)
    return False


# ---------------- Loaders ---------------- #


def load_remote_project(entry: str, validator: Draft202012Validator) -> dict | None:
    host, repo = parse_entry(entry)
    raw = fetch_raw(host, repo, "project.yaml")
    if not raw:
        print(f"[skip] {entry}: no project.yaml", file=sys.stderr)
        return None
    parsed = safe_yaml_load(raw, entry)
    if parsed is None:
        return None
    meta = normalize(parsed)
    if not validate(meta, entry, validator):
        return None
    meta["host"] = host
    meta["repo"] = repo
    meta["slug"] = make_slug(host, repo)
    meta["web_url"] = web_url(host, repo)
    meta["readme_body"] = fetch_raw(host, repo, meta.get("readme", "README.md")) or ""
    meta["last_commit"] = fetch_activity(host, repo)
    cover = meta.get("cover")
    if cover and not cover.startswith(("http://", "https://")):
        meta["cover"] = cover_url(host, repo, cover)
    return meta


def load_local_project(path: str, validator: Draft202012Validator) -> dict | None:
    root = pathlib.Path(path).expanduser().resolve()
    yaml_file = root / "project.yaml"
    if not yaml_file.is_file():
        print(f"[skip] {path}: no project.yaml", file=sys.stderr)
        return None
    parsed = safe_yaml_load(yaml_file.read_text(encoding="utf-8"), str(root))
    if parsed is None:
        return None
    meta = normalize(parsed)
    if not validate(meta, str(root), validator):
        return None
    repo_id = f"local/{root.name}"
    meta["host"] = "local"
    meta["repo"] = repo_id
    meta["slug"] = repo_id.replace("/", "__").replace(" ", "_")
    meta["web_url"] = ""
    readme_path = root / meta.get("readme", "README.md")
    meta["readme_body"] = (
        readme_path.read_text(encoding="utf-8") if readme_path.is_file() else ""
    )
    meta["last_commit"] = local_activity(root)
    return meta


# ---------------- Rendering ---------------- #


STATUS_LABEL = {
    "in-progress": "进行中",
    "done": "已完成",
    "archived": "已归档",
}


def activity_class(iso: str | None) -> str:
    """fresh < 7 天, warm < 30 天, 否则 cold."""
    if not iso:
        return "activity-cold"
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return "activity-cold"
    days = (datetime.now(timezone.utc) - d).days
    if days < 7:
        return "activity-fresh"
    if days < 30:
        return "activity-warm"
    return "activity-cold"


def _field(label: str, value_html: str) -> str:
    return (
        f'<div class="field"><span class="field-label">{label}</span>'
        f'<span class="field-value">{value_html}</span></div>'
    )


def write_project_page(meta: dict) -> None:
    host = meta.get("host", "github")
    status = meta.get("status", "")
    status_html = (
        f'<span class="badge badge-status-{status}">{STATUS_LABEL.get(status, status)}</span>'
        if status else "—"
    )
    repo_html = (
        f'<a href="{meta["web_url"]}" target="_blank" rel="noopener">{meta["repo"]}</a>'
        if meta.get("web_url") else meta["repo"]
    )
    tags_html = " ".join(f'<span class="tag">{t}</span>' for t in meta.get("tags", [])) or "—"
    authors_html = ", ".join(meta.get("authors", [])) or "—"
    activity = relative_time(meta.get("last_commit")) or "—"

    fields = [
        _field("Repo", repo_html),
        _field("Host", host_badge(host)),
        _field("Authors", authors_html),
        _field("Category", f'<span class="badge badge-category">{meta.get("category", "")}</span>'),
        _field("Status", status_html),
        _field("Last commit", activity),
    ]
    if meta.get("updated"):
        fields.append(_field("Updated", str(meta["updated"])))
    if meta.get("demo"):
        fields.append(_field("Demo", f'<a href="{meta["demo"]}" target="_blank" rel="noopener">{meta["demo"]}</a>'))
    for k, v in (meta.get("links") or {}).items():
        fields.append(_field(k.capitalize(), f'<a href="{v}" target="_blank" rel="noopener">{v}</a>'))
    if meta.get("tags"):
        fields.append(_field("Tags", tags_html))

    meta_block = '<div class="project-meta">' + "".join(fields) + "</div>"

    lines = [
        f"# {meta.get('name', meta['repo'])}",
        "",
        f"> {meta.get('summary', '')}",
        "",
        meta_block,
        "",
        "---",
        "",
        meta["readme_body"],
    ]
    (PROJECTS / f"{meta['slug']}.md").write_text("\n".join(lines), encoding="utf-8")


def sort_key(p: dict) -> str:
    return p.get("last_commit") or p.get("updated") or ""


def render_hero(projects: list[dict]) -> str:
    categories = {p.get("category", "") for p in projects if p.get("category")}
    latest = max((p.get("last_commit") or "" for p in projects), default="")
    latest_human = relative_time(latest) if latest else "—"
    return (
        '<section class="hero">'
        '<span class="eyebrow">MICU · AI · LIBRARY</span>'
        '<h1>工作室<em>项目矩阵</em></h1>'
        '<p>聚合工作室所有 AI 相关项目，每张卡是一个仓库的快照——简介 / 作者 / 最近更新一目了然。点开看详情。</p>'
        '<div class="hero-stats">'
        f'<div class="hero-stat"><span class="num">{len(projects)}</span><span class="label">项目</span></div>'
        f'<div class="hero-stat"><span class="num">{len(categories)}</span><span class="label">分类</span></div>'
        f'<div class="hero-stat"><span class="num">{latest_human}</span><span class="label">最近更新</span></div>'
        '</div>'
        '</section>'
    )


def render_cards(projects: list[dict]) -> str:
    out = [render_hero(projects), '<section class="card-grid">']
    for p in projects:
        host = p.get("host", "github")
        status = p.get("status", "")
        cover_html = (
            f'<div class="card-cover" style="background-image:url({p["cover"]})"></div>'
            if p.get("cover")
            else f'<div class="card-cover no-cover">{p.get("category", "·")}</div>'
        )
        eyebrow_parts = []
        if host != "github":
            eyebrow_parts.append(f'<span class="badge badge-host-{host}">{host_badge(host)}</span>')
        if p.get("category"):
            eyebrow_parts.append(f'<span class="badge badge-category">{p["category"]}</span>')
        if status:
            eyebrow_parts.append(
                f'<span class="badge badge-status-{status}">{STATUS_LABEL.get(status, status)}</span>'
            )
        eyebrow_html = (
            f'<div class="card-eyebrow">{"".join(eyebrow_parts)}</div>' if eyebrow_parts else ""
        )
        tags_html = ""
        if p.get("tags"):
            chips = "".join(f'<span class="tag">{t}</span>' for t in p["tags"][:4])
            tags_html = f'<div class="card-tags">{chips}</div>'
        activity = relative_time(p.get("last_commit"))
        activity_html = (
            f'<span class="card-activity {activity_class(p.get("last_commit"))}">'
            f'<span class="activity-dot"></span>{activity}</span>'
            if activity else ""
        )
        out.append(
            f'<a class="card" href="#/projects/{p["slug"]}">'
            f'{cover_html}'
            f'<div class="card-body">'
            f'{eyebrow_html}'
            f'<h3 class="card-title">{p.get("name", p["repo"])}</h3>'
            f'<p class="card-summary">{p.get("summary", "")}</p>'
            f'{tags_html}'
            f'<div class="card-foot">'
            f'<span class="card-authors">{", ".join(p.get("authors", []))}</span>'
            f'{activity_html}'
            f'</div>'
            f'</div>'
            f'</a>'
        )
    out.append("</section>")
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
        "| 名称 | 分类 | 来源 | 作者 | 状态 | 活跃度 | 简介 |",
        "|---|---|---|---|---|---|---|",
    ]
    for p in projects:
        activity = relative_time(p.get("last_commit")) or p.get("updated", "")
        out.append(
            f"| [{p.get('name', p['repo'])}](#/projects/{p['slug']}) "
            f"| {p.get('category', '')} | {host_badge(p.get('host', ''))} "
            f"| {', '.join(p.get('authors', []))} | {p.get('status', '')} "
            f"| {activity} | {p.get('summary', '')} |"
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


# ---------------- Main ---------------- #


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
    for entry in registry.get("repos", []) or []:
        meta = load_remote_project(entry, validator)
        if meta:
            write_project_page(meta)
            projects.append(meta)
            print(f"[ok] {entry}")

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
