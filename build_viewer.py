"""构建可部署的静态查看器 index.html。

两种数据模式(由 DIGEST_FETCHER 或 --mode 决定):
- fixture(默认) : 引擎离线确定性生成近 N 天数据,用于演示/测试/本地预览。
- web           : 读「逐日归档 data/archive」(真实新闻),对每天过 5 道质量门后组装近 N 天。
                 需要先运行 ingest_today.py 累积归档(部署时由 CI 每天执行)。

用法:
  python build_viewer.py --days 30            # fixture 演示
  DIGEST_FETCHER=web python build_viewer.py --days 30   # 真实新闻(读归档)
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime

from digest import store
from digest.builders import BuilderRegistry
from digest.config import load_settings
from digest.pipeline import build_pipeline
from digest.quality import QualityEngine
from digest.sources import SourceRegistry
from digest.synthesizer import TemplateSynthesizer

HERE = os.path.dirname(os.path.abspath(__file__))
VIEWER = os.path.join(HERE, "viewer")
TEMPLATE = os.path.join(VIEWER, "template.html")
INDEX = os.path.join(VIEWER, "index.html")
DATA_JSON = os.path.join(VIEWER, "viewer_data.json")


# --------------------------------------------------------------------------
# fixture 模式：离线确定性合成近 N 天
# --------------------------------------------------------------------------
def build_bundle_fixture(days_n: int, end: date | None = None) -> dict:
    p = build_pipeline(fetcher_mode="fixture")
    end = end or date.today()
    results = p.backfill(days=days_n, end=end, write=True)
    days_data, total = [], 0
    for r in results:
        rep = r.report
        items = _items(rep)
        total += len(items)
        days_data.append(_day(rep))
    days_data.sort(key=lambda d: d["date"])
    return {
        "app": "AI 智讯日报 · 情报自动化引擎",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": "fixture",
        "days": days_data,
        "meta": {
            "days": len(days_data), "total_items": total,
            "sources_count": len(p.registry.all), "builders_count": len(p.builders.all),
            "source_categories": p.registry.summary()["by_category"],
        },
    }


# --------------------------------------------------------------------------
# web 模式：从真实归档组装近 N 天(每天过 5 道质量门)
# --------------------------------------------------------------------------
def build_bundle_web(days_n: int) -> dict:
    settings = load_settings()
    reg = SourceRegistry(settings)
    bld = BuilderRegistry(settings)
    eng = QualityEngine(settings, reg, bld)
    sym = TemplateSynthesizer(settings)

    daylist = store.recent_days(days_n)
    days_data, total = [], 0
    for d in daylist:
        raw = store.load_raw(d)
        qres = eng.run(raw, d)
        if not qres.qualified:
            continue
        rep = sym.synthesize(qres.qualified, d)
        total += len(_items(rep))
        days_data.append(_day(rep))
    days_data.sort(key=lambda d: d["date"])
    arc = store.archive_summary()
    return {
        "app": "AI 智讯日报 · 情报自动化引擎",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": "web",
        "days": days_data,
        "meta": {
            "days": len(days_data), "total_items": total,
            "sources_count": len(reg.all), "builders_count": len(bld.all),
            "source_categories": reg.summary()["by_category"],
            "archive": arc,
        },
    }


# 杂志栏目规则(按标签优先级给每条新闻分栏目)
_SECTION_RULES = [
    ("大厂动向", {"模型", "算力", "大模型", "OpenAI", "Gemini"}),
    ("初创与生态", {"融资", "创业"}),
    ("技术与观点", {"Agent", "开源", "模型", "技术"}),
    ("资本与治理", {"治理", "安全"}),
]
_WEEKDAYS_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _cn_date(date_str: str) -> str:
    d = date.fromisoformat(date_str)
    return f"{d.year}年{d.month}月{d.day}日 {_WEEKDAYS_CN[d.weekday()]}"


def _day(rep) -> dict:
    m = _magazine(rep)
    return {
        "date": rep.report_date,
        "title": rep.title,
        "generated_at": rep.generated_at,
        "highlights": rep.highlights,
        "categories": rep.categories,
        "builder_dynamics": rep.builder_dynamics,
        "trend_notes": rep.trend_notes,
        "items": _items(rep),
        "qualified": len(_items(rep)),
        "date_cn": m["date_cn"],
        "headline": m["headline"],
        "one_line_read": m["one_line_read"],
        "trends": m["trends"],
        "core_signals": m["core_signals"],
        "total_signals": m["total_signals"],
        "sections": m["sections"],
    }


def _items(rep) -> list:
    out = []
    for cat, cards in rep.categories.items():
        for c in cards:
            out.append({**c, "date": rep.report_date, "category": cat})
    return out


def _magazine(rep) -> dict:
    items = _items(rep)
    if not items:
        return {
            "date_cn": _cn_date(rep.report_date),
            "headline": "今日暂无核心情报",
            "one_line_read": "该日尚未累积到通过质量审核的新闻，系统持续归档中将逐步补全。",
            "trends": [], "core_signals": [], "total_signals": 0, "sections": [],
        }
    ranked = sorted(items, key=lambda i: i.get("importance") or 0, reverse=True)
    headline = ranked[0]["title"]
    tagfreq = {}
    for i in items:
        for t in i.get("tags", []):
            if t == "AI":          # 全局通用标签，不作为“趋势”
                continue
            tagfreq[t] = tagfreq.get(t, 0) + 1
    trends = [{"label": k, "count": v} for k, v in sorted(tagfreq.items(), key=lambda kv: -kv[1])[:3]]
    top_tags = "、".join(t["label"] for t in trends) or "行业动态"
    one_line_read = (f"本期聚焦「{top_tags}」，共 {len(items)} 条通过 5 道质量审核门的情报。"
                     f"头条为「{headline}」。" if items else "本期暂无核心情报。")
    return {
        "date_cn": _cn_date(rep.report_date),
        "headline": headline,
        "one_line_read": one_line_read,
        "trends": trends,
        "core_signals": ranked[:5],
        "total_signals": len(items),
        "sections": _sections(items),
    }


def _sections(items) -> list:
    buckets = {}
    for i in items:
        name = "行业动态"
        for sec, keys in _SECTION_RULES:
            if set(i.get("tags", [])) & keys:
                name = sec
                break
        buckets.setdefault(name, []).append(i)
    return [{"name": name, "items": bucket} for name, bucket in buckets.items()]


# --------------------------------------------------------------------------
def render_html(bundle: dict) -> str:
    with open(TEMPLATE, "r", encoding="utf-8") as fh:
        tpl = fh.read()
    payload = json.dumps(bundle, ensure_ascii=False)
    if "/*__DATA__*/" not in tpl:
        raise RuntimeError("template.html 缺少 /*__DATA__*/ 占位符")
    return tpl.replace("/*__DATA__*/", payload)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--end", default=None)
    ap.add_argument("--mode", default=None, help="fixture | web(默认读 DIGEST_FETCHER)")
    ap.add_argument("--data-only", action="store_true")
    args = ap.parse_args()

    mode = args.mode or os.environ.get("DIGEST_FETCHER", "fixture")
    end = date.fromisoformat(args.end) if args.end else None

    use_web = mode in ("web", "WebFetcher")
    bundle = build_bundle_web(args.days) if use_web else build_bundle_fixture(args.days, end)

    os.makedirs(VIEWER, exist_ok=True)
    with open(DATA_JSON, "w", encoding="utf-8") as fh:
        json.dump(bundle, fh, ensure_ascii=False, indent=2)
    print(f"[build] mode={mode} viewer_data.json -> {DATA_JSON} "
          f"({len(bundle['days'])} days, {bundle['meta']['total_items']} items)")

    if args.data_only:
        return 0

    html = render_html(bundle)
    with open(INDEX, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"[build] index.html -> {INDEX} ({os.path.getsize(INDEX) // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
