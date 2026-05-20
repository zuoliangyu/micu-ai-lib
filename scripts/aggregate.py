#!/usr/bin/env python3
"""Aggregate member repo metadata into Astro content (src/content/projects).

Each registry entry becomes one markdown file with YAML frontmatter (project
metadata) + README body. Astro reads the collection and renders pages.

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

import yaml
from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTENT = ROOT / "src" / "content" / "projects"
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


FRONTMATTER_KEYS = (
    "name", "summary", "authors", "category", "tags", "status",
    "updated", "cover", "demo", "links",
    "host", "repo", "slug", "web_url", "last_commit",
)


def _yaml_scalar(value) -> str:
    """Inline scalar safe for YAML frontmatter — quote when needed."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    # quote strings that could be misread by YAML (incl. date-like ISO prefixes)
    looks_like_date = len(s) >= 10 and s[:4].isdigit() and s[4] == "-" and s[7] == "-"
    needs_quote = (
        not s
        or s != s.strip()
        or any(c in s for c in (":", "#", "&", "*", "!", "|", ">", "%", "@", "`", "\"", "'"))
        or s.lower() in ("true", "false", "null", "yes", "no", "on", "off")
        or s[0] in ("-", "?", "[", "{", ",")
        or looks_like_date
    )
    if needs_quote:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def _yaml_block(meta: dict) -> str:
    out: list[str] = []
    for key in FRONTMATTER_KEYS:
        if key not in meta:
            continue
        value = meta[key]
        if value is None or value == "" or value == [] or value == {}:
            continue
        if isinstance(value, list):
            out.append(f"{key}:")
            for item in value:
                out.append(f"  - {_yaml_scalar(item)}")
        elif isinstance(value, dict):
            out.append(f"{key}:")
            for k, v in value.items():
                out.append(f"  {k}: {_yaml_scalar(v)}")
        else:
            out.append(f"{key}: {_yaml_scalar(value)}")
    return "\n".join(out)


def write_project_page(meta: dict) -> None:
    body = meta.get("readme_body", "") or ""
    # strip a leading H1 if the README starts with the project name — the
    # detail page already shows it as a styled heading.
    stripped = body.lstrip()
    if stripped.startswith("# "):
        first_nl = stripped.find("\n")
        if first_nl != -1:
            body = stripped[first_nl + 1 :].lstrip("\n")

    text = "---\n" + _yaml_block(meta) + "\n---\n\n" + body
    (CONTENT / f"{meta['slug']}.md").write_text(text, encoding="utf-8")


def sort_key(p: dict) -> str:
    return p.get("last_commit") or p.get("updated") or ""


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
    CONTENT.mkdir(parents=True, exist_ok=True)
    # wipe stale entries so deletions in registry propagate
    for old in CONTENT.glob("*.md"):
        old.unlink()

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

    print(f"\n[done] {len(projects)} projects written to {CONTENT.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
