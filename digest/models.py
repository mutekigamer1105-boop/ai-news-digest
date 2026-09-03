"""数据模型：贯穿采集、审核、合成、输出四段式的核心对象。

全部使用 dataclass，字段只读、可序列化，保证流水线各阶段可独立测试。
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class Source:
    """信源注册表里的一条记录（采集层 / 审核门 1、4 使用）。"""

    id: str
    name: str
    type: str
    lang: str
    category: str
    base_url: str
    credibility: float
    enabled: bool = True

    @property
    def authority(self) -> float:
        """信源权威度：官方/高校最高，媒体次之，社区再次之。"""
        base = {"official": 1.0, "media": 0.8, "product": 0.65, "community": 0.55}.get(self.type, 0.6)
        return round(min(base, 1.0), 2)


@dataclass
class Builder:
    """追踪的 25 位海外顶级 Builder（人物层输入，审核门 4 加权）。"""

    id: str
    name: str
    role: str
    category: str
    handles: Dict[str, str] = field(default_factory=dict)
    signals: List[str] = field(default_factory=list)


@dataclass
class RawItem:
    """采集层抓到的原始条目：尚未过任何审核门。"""

    id: str
    source_id: str
    source_name: str
    source_type: str
    source_lang: str
    source_credibility: float
    title: str
    summary: str
    url: str
    published_at: str
    author_handle: Optional[str] = None
    builder_id: Optional[str] = None
    builder_name: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    engagement: float = 0.0
    raw_text: str = ""
    fetched_at: str = field(default_factory=_now_iso)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = "raw-" + hashlib.sha1(self.url.encode("utf-8")).hexdigest()[:12]

    @property
    def published(self) -> datetime:
        return _parse_dt(self.published_at)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class QualifiedItem:
    """已通过质量审核门的条目：在 RawItem 基础上附加审核字段。"""

    item: RawItem
    credibility_score: float = 0.0     # 门1
    dedup_key: str = ""                # 门2
    is_recent: bool = True             # 门3
    importance_score: float = 0.0      # 门4
    validated: bool = True             # 门5
    gate_results: Dict[str, bool] = field(default_factory=dict)
    passed: bool = True


@dataclass
class DailyReport:
    """一份结构化日报，可导出为 Markdown / JSON / 多维表格 CSV。"""

    report_date: str
    generated_at: str
    title: str
    highlights: List[str] = field(default_factory=list)
    categories: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    builder_dynamics: List[Dict[str, Any]] = field(default_factory=list)
    trend_notes: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    items: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------
def _parse_dt(value: str) -> datetime:
    if not value:
        return datetime.now()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return datetime.now()


def normalize_title(title: str) -> str:
    """标题归一化：小写、去重空格与标点，用于去重键。"""
    t = title.lower()
    t = re.sub(r"[^\w\u4e00-\u9fff ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def title_similarity(a: str, b: str) -> float:
    """基于 Jaccard 的标题相似度，用于跨信源去重（门2）。"""
    ta, tb = set(normalize_title(a).split()), set(normalize_title(b).split())
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
