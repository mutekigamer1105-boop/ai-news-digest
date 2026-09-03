"""逐日归档：把真实抓到的新闻按「发布日期」持久化，供 build_viewer 组装近 30 天。

为什么需要归档：真实新闻源(RSS)只能取到最近几天,无法回溯 30 天。
所以每天 CI 把当天抓好、去重后,按发布日期落盘到 data/archive/<date>.json;
build_viewer(web 模式)读取这些归档,对每天过 5 道质量门,得到近 30 天真实日报。
连续运行,归档逐渐铺满近 30 天,实现「真实新闻 + 每日自动更新」。
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from .models import RawItem


def archive_dir() -> str:
    override = os.environ.get("DIGEST_ARCHIVE_DIR")
    if override:
        return override
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "data", "archive")


def _day_file(day: date) -> str:
    return os.path.join(archive_dir(), f"{day.isoformat()}.json")


def _load(day: date) -> List[dict]:
    path = _day_file(day)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh).get("items", [])


def save_items(items: List[RawItem], bucket_by_pubdate: bool = True) -> Dict[str, int]:
    """把一批真实条目按发布日期归档,并按 URL 去重。返回 {date: added}。"""
    os.makedirs(archive_dir(), exist_ok=True)
    buckets: Dict[str, List[RawItem]] = {}
    for it in items:
        d = it.published.date() if bucket_by_pubdate else date.today()
        buckets.setdefault(d.isoformat(), []).append(it)

    added: Dict[str, int] = {}
    for d, group in buckets.items():
        day = date.fromisoformat(d)
        existing = _load(day)
        seen = {x.get("url") or x.get("title") for x in existing}
        new_items: List[dict] = []
        for it in group:
            key = it.url or it.title
            if key in seen:
                continue
            seen.add(key)
            new_items.append(it.to_dict())
        # 按重要度/发布时间稳定排序
        new_items.sort(key=lambda x: x.get("published_at", ""), reverse=True)
        if new_items:
            with open(_day_file(day), "w", encoding="utf-8") as fh:
                json.dump({"items": existing + new_items}, fh, ensure_ascii=False, indent=1)
            added[d] = len(new_items)
    return added


def load_raw(day: date) -> List[RawItem]:
    dicts = _load(day)
    return [RawItem(**d) for d in dicts]


def recent_days(n: int, end: date | None = None) -> List[date]:
    end = end or date.today()
    out = []
    for i in range(n):
        d = end - timedelta(days=i)
        if os.path.exists(_day_file(d)):
            out.append(d)
    out.sort(reverse=True)
    return out


def archive_summary() -> Dict[str, int]:
    total = 0
    days = 0
    if os.path.isdir(archive_dir()):
        for fn in os.listdir(archive_dir()):
            if fn.endswith(".json"):
                days += 1
                with open(os.path.join(archive_dir(), fn), encoding="utf-8") as fh:
                    total += len(json.load(fh).get("items", []))
    return {"days": days, "items": total}
