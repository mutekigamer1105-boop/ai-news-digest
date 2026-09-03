# AI 智讯日报 · 情报自动化引擎

> 一个可配置、可离线测、可定时运行的 **AI 行业日报流水线引擎**。
> 核心链路与产品计划书一致：**一句话触发 → 全网采集 → 5 道质量审核门 → 结构化合成 → 双形态输出 → 每日 12:00 自动更新**。

---

## 0. 与原项目的关系「同链路、不同产品」

| 维度 | 原项目（Agent Skill） | 本产品（情报自动化引擎） |
| --- | --- | --- |
| 产品形态 | 一段提示词/配置包，嵌在 Claude Code / Cursor 里由宿主 Agent 执行 | 独立的 Python 引擎 + CLI + 调度器，可脱离宿主运行 |
| 采集 | 依赖宿主 Agent 的联网检索能力 | 显式 **Fetcher 适配器**（离线 fixture / 真实 Web），可替换 |
| 审核门 | 由模型启发式执行 | **确定性代码**实现的 5 道审核门，规则可审计、可单测 |
| 合成 | 由宿主模型撰写 | 模板合成器（零依赖可复现）+ 可插拔 LLM 合成器 |
| 产出 | 文本日报 | Markdown 人读报告 / JSON 结构化 / CSV 多维表格导入，周汇总 + 索引 |
| 更新 | 手动或宿主定时 | 内置 **12:00 调度环** + Windows 计划任务，支持 7 天回填 |

**9 道工程差异**，让「核心链路一致」但「交付物完全不同」：它是独立引擎，而非技能包。

---

## 1. 目录结构

```
AI_智讯日报_Agent/
├─ config/
│   ├─ sources.json      # 33 个中英文信源注册表（含可信度/权威度）
│   ├─ builders.json     # 25 位海外顶级 Builder 注册表
│   └─ pipeline.json     # 审核门阈值 / 打分权重 / 调度 / 输出配置
├─ digest/
│   ├─ models.py         # RawItem / QualifiedItem / DailyReport
│   ├─ config.py         # Settings 装配
│   ├─ sources.py        # SourceRegistry
│   ├─ builders.py       # BuilderRegistry
│   ├─ fetcher.py        # 采集层：Fixture(离线)/Web 适配器
│   ├─ quality.py        # 5 道质量审核门（确定性）
│   ├─ synthesizer.py    # 生成层：模板 / LLM 合成器
│   ├─ report.py         # 输出层：md / json / csv
│   ├─ pipeline.py       # 流水线编排 + 回填 + 索引
│   ├─ backfill.py       # 7 天回填与周汇总
│   ├─ scheduler.py      # 每日 12:00 调度 + Windows 计划任务
│   ├─ cli.py / __main__.py
├─ tests/                # pytest 套件（20 用例全通过）
├─ output/               # 已生成日报（md/json/csv + weekly + index）
├─ run_daily.bat         # 计划任务启动器（已生成）
└─ pytest.ini
```

## 2. 核心链路（与产品计划书一致）

```
[触发] 一句话/定时
   │
   ▼
[采集层] 信源调度 + 人物线   →  33 信源 × 25 Builder
   │
   ▼
[5 道质量审核门]
   ① 信源可信度 ② 去重/同类合并 ③ 时效性 ④ 重要性打分 ⑤ 交叉核验
   │（过滤 & 排序 & 保留 Top-N）
   ▼
[生成层] 结构化合成（模板/LLM）
   │
   ▼
[输出层] report.md（人读）/ report.json（结构化）/ report.csv（多维表格）
   │
   ▼
[调度] 每天 12:00 自动更新 + 7 天回填
```

## 3. 安装与运行

Python 3.10+（实机 Python 3.13.5），**零第三方运行时依赖**（标准库），`pytest` 仅用于开发测试。

> 直接使用 Anaconda 自带 Python：`C:\Users\76112\anaconda3\python.exe`

```powershell
cd AI_智讯日报_Agent

# 查看信源 / 人物 / 调度配置
python -m digest info

# 跑通校验（fixture 离线模式，一天）
python -m digest test --date 2026-09-04

# 生成某日日报
python -m digest run --date 2026-09-04

# 生成过去 7 天日报（回填）
python -m digest backfill --days 7

# 列出 / 查看已生成日报
python -m digest list
python -m digest show --date 2026-09-04
```

### 每日 12:00 自动更新

- **内置调度环（推荐，跨平台）**
  ```powershell
  python -m digest schedule            # 常驻，每天 12:00 自动触发，含当日去重标记
  python -m digest schedule --dry-run  # 只打印下一次运行时间，不执行
  ```
- **Windows 计划任务（可选，OS 级唤醒，更省资源）**
  ```powershell
  python -m digest install-schedule    # 注册每日 12:00 任务（生成 run_daily.bat 启动器）
  python -m digest uninstall-schedule  # 删除
  ```
  > ⚠️ 任务创建依赖 Windows「任务计划程序」服务与 `schtasks` 命令。在受限/沙箱环境下
  > `schtasks` 无法创建任务（本机验证：连控制项也报“找不到指定路径”），此时请用上面的
  > **内置调度环**，它不依赖 `schtasks`，仅靠一个常驻进程即可实现每日 12:00 自动更新。

### 切换真实联网 / LLM

默认使用 **fixture 离线合成器**，保证任何机器、任何日期都能复现、都能「跑通」。
部署接入真实数据时：

```powershell
# 真实采集：设置环境变量后，流水线会切换到 WebFetcher
$env:DIGEST_FETCHER="web"

# 真实 LLM 合成：配置 OpenAI 兼容接口后自动启用 APISynthesizer（缺 key 回落模板）
$env:DIGEST_LLM_API_KEY="sk-..."
$env:DIGEST_LLM_BASE_URL="https://api.openai.com/v1"
$env:DIGEST_LLM_MODEL="gpt-4o-mini"
```

## 4. 5 道质量审核门（确定性实现）

| # | 门 | 规则 |
| --- | --- | --- |
| ① | 信源可信度 | 信源 `credibility ≥ 0.60`，否则淘汰 |
| ② | 去重/同类合并 | 标题 Jaccard 相似度 ≥ 0.45 归并为一簇，取最高可信代表 |
| ③ | 时效性 | 发布时间落在报告窗口内（`recency_hours=26`），过期淘汰 |
| ④ | 重要性打分 | 加权：可信度 0.35 / 权威度 0.20 / 时效 0.15 / 人物 0.15 / 热度 0.10 / 关键词 0.05，保留 Top-N |
| ⑤ | 事实/来源交叉核验 | 高权威（官方 1.0 / 媒体 0.8）自身可信；产品/社区类需 ≥2 个独立信源背书 |

## 5. 输出产物（`output/`）

- `output/<日期>/report.md` —— 人读日报（亮点速览 / 分类资讯 / 人物动态 / 趋势注记 / 原文链接）
- `output/<日期>/report.json` —— 结构化数据（程序友好）
- `output/<日期>/report.csv` —— 多维表格导入（飞书 / Notion / Airtable）
- `output/weekly/week.md` `output/weekly/week.csv` —— 近 N 天周汇总与跨天表格
- `output/index.md` —— 按日期倒序的日报索引

## 6. 测试

```powershell
python -m pytest        # 20 用例，全通过
```

覆盖：模型归一化/相似度、5 道审核门各自的判定、fixture 确定性、单日端到端跑通、
7 天回填落盘、调度器 12:00 时间窗与去重标记。

---

## 7. 在线查看器（可对外分享）

`viewer/index.html` 是**单文件、自包含**的在线查看器，已内嵌近 30 天日报数据
（30 天 / 316 条情报 / 33 信源 / 25 Builder）。无需任何依赖，双击即可打开；也
可直接扔到任意静态托管，**任何拿到链接的人都能查看**。功能：

- **每日日报视图**：点击左侧近 30 天任意日期，查看当日 高光 / 分类资讯 / 人物动态 / 趋势注记 / 原始链接。
- **日期范围总结视图**：自由圈选起止日期（含近 3/7/14/30 天快捷按钮），点击
  「生成 AI 总结」——对所选范围内的 AI 新闻做统一总结（覆盖天数/情报条数/主题分布
  柱状图/活跃人物/热词标签/重点条目），并给出模型生成的归纳叙事。

### 构建 / 重新生成

```powershell
python build_viewer.py --days 30   # 回填 30 天 + 注入数据 → viewer/index.html
python build_viewer.py --data-only # 只生成 viewer_data.json
```

### 自动部署：真实 AI 新闻 · 每天 12:00 更新 · 人人可访问（推荐）

> 详细步骤与架构图见 **`DEPLOY.md`**。**真实新闻版**：`.github/workflows/daily-deploy.yml`
> 每天北京时间 12:00 由 GitHub Actions 触发，依次：
> `ingest_today.py`(抓真实 Google News RSS，中英文) → 写 `data/archive`
> → 归档提交回仓库(累积近 30 天) → `build_viewer.py --mode web`(过 5 道质量门)
> → 发布到 GitHub Pages。默认网址 `https://<用户名>.github.io/<仓库名>/`。
>
> 可选 **保留你现有 Netlify 网址**：Link 到 Git（`netlify.toml` 已设 `DIGEST_FETCHER=web`）
> + 建 Build Hook 存 Secret `NETLIFY_BUILD_HOOK_URL`，即发布回 `velvety-pastelito-ef3404.netlify.app`。
>
> 说明：真实新闻源只能取最近几天，故靠逐日归档填补近 30 天；首次上线仅有最近数天真实数据，
> 之后逐日补满。**本地沙箱无外网，真实抓取在 CI(海外)完成**；已用离线 RSS 样本对解析/归档/web 组装做了单测。

#### 一次性手动部署（快速拿到链接）

- **Netlify Drop**：打开 `app.netlify.com/drop`，把 `viewer/index.html` 拖进去即得公开链接。
- **Vercel / Cloudflare Pages**：拖拽或 `git` 推送该文件夹，即生成 `https://xxx` 链接。
- **GitHub Pages / 任意 OSS**：把 `viewer/index.html` 上传为静态页即可。

> `viewer/index.html` 单文件即可跑通全部前端功能（范围总结用确定性聚合兜底）。

### 需要「真正的模型总结」时

用 `server.py`（纯标准库）托管，它会同时提供 `/` 与 `/api/summarize`：

```powershell
# 配置真实 LLM（OpenAI 兼容）
$env:DIGEST_LLM_API_KEY="sk-..."
$env:DIGEST_LLM_BASE_URL="https://api.openai.com/v1"
$env:DIGEST_LLM_MODEL="gpt-4o-mini"

python server.py --host 0.0.0.0 --port 8787
```

前端默认调用 `SUMMARIZE_ENDPOINT`（默认 `/api/summarize`）。部署后：
- 前端已内嵌数据，静态展示零后端；
- 点「生成 AI 总结」时若 `/api/summarize` 可达则走大模型归纳，否则回落到确定性聚合，
  **任何环境都能给出统一总结**。

---

*本引擎为「产品计划书」的可运行实现。所有配置位于 `config/`，可在不改代码前提下替换
信源、Builder、阈值与调度时间。*
