"""每日真实抓取入库：抓取今天(及 Google News 返回的近几天)的真实 AI 新闻,
按发布日期归档到 data/archive,供 build_viewer(web 模式)组装近 30 天。

在部署环境(有网络)每天由 CI 运行一次。本地沙箱无网络,请用它做归档/自测逻辑。

用法:
  DIGEST_FETCHER=web python ingest_today.py [--lookback 3]
"""
from __future__ import annotations

import argparse
import os
import time
from datetime import date, timedelta

from digest import store
from digest.pipeline import build_pipeline


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback", type=int, default=3,
                    help="对本机已生成但未入库的近期天数也补齐(归档存的是发布日,通常用不到)")
    args = ap.parse_args()

    p = build_pipeline(fetcher_mode=os.environ.get("DIGEST_FETCHER", "web"))
    raw = p.fetcher.acquire(date.today())
    if not raw:
        print("[ingest] 未能抓取到真实新闻(网络受限?),当天不入库")
        return 1

    added = store.save_items(raw)
    total_added = sum(added.values())
    print(f"[ingest] 抓取真实新闻 {len(raw)} 条 -> 新增归档 {total_added} 条,分布: {added}")
    print(f"[ingest] 当前归档: {store.archive_summary()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
