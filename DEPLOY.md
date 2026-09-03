# 部署工作流：「真实 AI 新闻 · 每天自动更新 · 人人可访问」

## 一、整体架构（真实新闻版）

```
        GitHub 仓库（AI_智讯日报_Agent）
        config/  digest/  build_viewer.py  ingest_today.py
        .github/workflows/daily-deploy.yml   netlify.toml
                    │
   (1) 每天 12:00(北京) GitHub Actions 定时触发
                    ▼
   (2) ingest_today.py  抓取「真实」Google News RSS(中英文多查询)
        → 按发布日期写入 data/archive/<date>.json
                    ▼
   (3) 把 data/ 归档提交回仓库(累积近 30 天真实新闻)
                    ▼
   (4) build_viewer.py --mode web  读归档 → 每天过 5 道质量门
        → 生成 viewer/index.html(内嵌近 30 天)
                    ▼
   (5) 自动发布到公网
        → GitHub Pages 网址(默认) 或 你的 Netlify 网址(可选)
```

**为什么这样设计**：真实新闻源(RSS)只能取最近几天，无法回溯 30 天。
所以靠「逐日归档」累积：每天 CI 抓今天、入库、提交；连续运行约 1 个月后，
近 30 天均为真实新闻。首次上线可能只有最近几天的真实数据，之后逐日补满。

## 二、一条路径搞定（推荐）：GitHub Pages + Actions

1. **推 GitHub**（在 `AI_智讯日报_Agent` 目录）
   ```powershell
   git init; git add .; git commit -m init
   git remote add origin https://github.com/<你>/ai-news-digest.git
   git push -u origin main
   ```
2. 仓库 `Settings → Pages → Source` 选 **GitHub Actions**。
3. 推送 `main` 或手动 Run 一次 → 自动跑完整环（抓取→归档→构建→发布）。
   - 发布网址：`https://<你>.github.io/<仓库>/`
   - 之后**每天北京时间 12:00** 自动重建并发布，无需人工。

> `daily-deploy.yml` 已内置：抓取真实新闻 → 提交归档 → 构建(web) → 发布。

## 三、可选：保留你现有的 Netlify 网址

若想继续用 `velvety-pastelito-ef3404.netlify.app`：
1. 同上去 GitHub 推仓库。
2. Netlify 该站点 → `Link site to Git` → 选该仓库（`netlify.toml` 设了
   `DIGEST_FETCHER=web` 且发布目录 `viewer`，构建命令 `python build_viewer.py --days 30`）。
3. 在 Netlify 建一个 **Build Hook** → 把 URL 存为仓库 Secret `NETLIFY_BUILD_HOOK_URL`。
   - `daily-deploy.yml` 里已有一步：抓取+提交归档后，若该 Secret 存在就调 Netlify Hook 触发重建，
     发布回你原来的网址。
   - 或直接在 Netlify 开 **Scheduled build**(每天 12:00, Asia/Shanghai)。

## 四、真实新闻源与模型

- **新闻源**：Google News RSS（免费、无需 key、海外 CI 稳定可达；中英文多查询覆盖
  OpenAI/Anthropic/NVIDIA/融资/算力/Agent 等主题）。可改 `digest/feeds.py` 的 `QUERIES_*`。
- **总结**：默认确定性聚合（离线可用）。要真实大模型总结(含 DeepSeek)，把站点接
  `server.py` 的后端并配置 `DIGEST_LLM_BASE_URL / DIGEST_LLM_MODEL / DIGEST_LLM_API_KEY`。

## 五、验证与本地预览
```powershell
python -m pytest                     # 20 用例全通过(含 RSS 解析/归档/web 组装)
python build_viewer.py --days 30     # fixture 演示(离线 30 天)
DIGEST_FETCHER=web python ingest_today.py  # 真实抓取入库(需联网,CI 会跑)
```
本地预览：`python server.py --port 8787` → `http://127.0.0.1:8787/`

> 注意：真实抓取需联网，本地沙箱无法验证联网；首跑由 CI 完成。已用离线 RSS 样本
> 对解析、人物归属、归档往返、web 组装做了单测。
