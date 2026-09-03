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


def _day(rep) -> dict:
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
    }


def _items(rep) -> list:
    out = []
    for cat, cards in rep.categories.items():
        for c in cards:
            out.append({**c, "date": rep.report_date, "category": cat})
    return out


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
