# MICU AI 资源库

MICU 工作室 AI 项目聚合站点。成员仓库提交 `project.yaml`，主仓库按计划拉取并渲染为在线 docsify 文档。

在线访问：<https://micu-ai-lib.netlify.app>

## 目录

```
micu-ai-lib/
├── registry.yaml                    # 成员仓库白名单（owner/repo 列表）
├── templates/project.yaml           # 成员仓库要复制的元数据模板
├── scripts/
│   ├── aggregate.py                 # 聚合脚本（GitHub Action 调用）
│   ├── add_repo.py                  # 把一个 owner/repo 追加进 registry
│   └── schemas/project.schema.json  # project.yaml 的 JSON Schema 校验规则
├── .github/workflows/aggregate.yml  # 定时 + 手动 + dispatch 触发
└── docs/
    └── index.html                   # docsify 入口（其他 md 由 aggregate.py 生成、不进 git）
```

## 添加新项目（推荐用法）

不用 clone、不用编辑器：

1. 打开 GitHub → `zuoliangyu/micu-ai-lib` → **Actions** → 左侧 `Aggregate MICU AI Lib`
2. 右上角 **Run workflow** → `add_repo` 框填 `owner/repo`（比如 `someone/awesome-rag`）→ 点 Run
3. workflow 自动把它加进 `registry.yaml` 并 commit、聚合、部署。手机也能操作。

留空 `add_repo` 直接 Run 就是常规的"重新拉取所有项目"。

## 本地预览

```bash
# 跑一次聚合（拉 registry 里所有远程项目）
python scripts/aggregate.py

# 顺带预览本地未 push 的项目（可重复 --local）
python scripts/aggregate.py --local "E:/path/to/repo-a" --local "E:/path/to/repo-b"

# 起 docsify 服务（任选其一）
npx docsify-cli serve docs
python -m http.server -d docs 3000
```

依赖：`pip install pyyaml jsonschema`

## 部署

托管在 Netlify，由 GitHub Action 推送构建产物：

- Action 每 6 小时跑一次 `scripts/aggregate.py`，把生成的 `docs/` 通过 `nwtgck/actions-netlify` 部署到 Netlify。
- 仓库 Secrets 需要 `NETLIFY_AUTH_TOKEN`（Netlify 用户的 Personal access token）和 `NETLIFY_SITE_ID`（站点 UUID）。
- Settings → Actions → General → Workflow permissions 选 **Read and write**（`add_repo` 触发时需要 commit 回 registry）。
- 发布目录、headers 等由根目录 `netlify.toml` 声明。

## 成员侧的 project.yaml

在自己的项目根目录放一份，按 `templates/project.yaml` 改。必填：

- `name` / `authors` / `category` / `summary`

可选：`tags` / `status` / `updated` / `cover` / `demo` / `readme` / `links`。

schema 校验由 `scripts/schemas/project.schema.json` 定义；不符合规则的会在 action 日志里报 `[bad-yaml]` 并跳过该项目（不会让整个构建失败）。

## 实时刷新（可选）

成员仓库 push 后想立刻刷新主站，在成员仓库加一个 workflow：

```yaml
on: { push: { branches: [main] } }
jobs:
  notify:
    runs-on: ubuntu-latest
    steps:
      - run: |
          curl -X POST \
            -H "Authorization: token ${{ secrets.MICU_AI_LIB_DISPATCH }}" \
            -H "Accept: application/vnd.github+json" \
            https://api.github.com/repos/zuoliangyu/micu-ai-lib/dispatches \
            -d '{"event_type":"member-updated"}'
```

`MICU_AI_LIB_DISPATCH` 是一个 fine-grained PAT，权限仅勾选目标仓库的 `contents: write`。
