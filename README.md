# MICU AI 资源库

MICU 工作室 AI 项目聚合站点。成员仓库提交 `project.yaml`，主仓库定时拉取并由 Astro 渲染为静态站点。

在线访问：<https://micu-ai-lib.netlify.app>

## 目录

```
micu-ai-lib/
├── registry.yaml                    # 成员仓库白名单（owner/repo 列表）
├── templates/project.yaml           # 成员仓库要复制的元数据模板
├── scripts/
│   ├── aggregate.py                 # 聚合脚本：拉 project.yaml + README，写成 Astro content
│   ├── add_repo.py                  # 把一个 owner/repo 追加进 registry
│   └── schemas/project.schema.json  # project.yaml 的 JSON Schema
├── .github/workflows/aggregate.yml  # 定时 + 手动 + dispatch 触发
├── public/assets/                   # 静态资源（logo 等）
├── src/
│   ├── content.config.ts            # Astro content collection schema
│   ├── content/projects/            # 聚合产物（不进 git；CI 实时生成）
│   ├── layouts/Base.astro           # 主布局：brand 块 + sidebar + content
│   ├── components/                  # BrandBlock / Sidebar / Filters / ProjectCard / PageToc 等
│   ├── pages/                       # index / list / table / projects/[...slug]
│   ├── lib/format.ts                # 时间、分类等工具
│   └── styles/global.css            # 主题（亮 / 暗）+ 全局样式
├── astro.config.mjs
├── package.json
└── netlify.toml
```

## 添加新项目（推荐用法）

不用 clone、不用编辑器：

1. 打开 GitHub → `zuoliangyu/micu-ai-lib` → **Actions** → 左侧 `Aggregate MICU AI Lib`
2. 右上角 **Run workflow** → `add_repo` 框填 `owner/repo`（比如 `someone/awesome-rag`）→ 点 Run
3. workflow 自动把它加进 `registry.yaml` 并 commit、聚合、构建、部署。手机也能操作。

留空 `add_repo` 直接 Run 就是常规的「重新拉取所有项目」。

## 本地开发

需要 Python（聚合）+ Node 22（构建）。

```bash
# 1. 拉所有项目的 project.yaml + README → src/content/projects/*.md
python scripts/aggregate.py

# 顺带预览本地未 push 的项目（可重复 --local）
python scripts/aggregate.py --local "E:/path/to/repo-a" --local "E:/path/to/repo-b"

# 2. 起 Astro dev server（默认 http://localhost:4321）
npm install            # 首次
npm run dev

# 3. 构建静态站点（输出 dist/）
npm run build
```

Python 依赖：`pip install pyyaml jsonschema`

## 部署

托管在 Netlify，由 GitHub Action 推送构建产物：

- Action 每 6 小时跑一次：`aggregate.py` 拉数据 → `npm run build` 出 `dist/` → `nwtgck/actions-netlify` 推到 Netlify。
- 仓库 Secrets：`NETLIFY_AUTH_TOKEN`（Personal access token）+ `NETLIFY_SITE_ID`（站点 UUID）。
- Settings → Actions → General → Workflow permissions 选 **Read and write**（`add_repo` 触发时要 commit 回 registry）。
- 发布目录、headers 由根目录 `netlify.toml` 声明。

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
