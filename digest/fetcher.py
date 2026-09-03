"""采集层：把「信源/人物」变成一批原始条目（RawItem）。

提供两种适配器，核心链路一致，仅输入来源不同：
- FixtureFetcher：读取 fixtures/raw_<date>.json；若无则用「确定性合成器」按日期种子生成，
  用于离线演示、回归测试与 7 天回填，保证结果可复现。
- WebFetcher：真实联网适配器（需可访问各信源端点 / RSS / 搜索 API），部署时启用。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from .builders import BuilderRegistry
from .config import Settings
from .models import Builder, RawItem, Source, normalize_title, title_similarity
from .sources import SourceRegistry

from . import feeds  # noqa: E402  (真实 Google News RSS 抓取)

# 合成器用的话题池：中英文混排，覆盖模型/产品/算力/融资/政策/开源等
_TOPICS = [
    ("OpenAI 发布新一代推理模型并更新 API", "OpenAI 正式推出新一代推理模型，重写 API 与工具调用体验。"),
    ("Anthropic 推出企业级 AI 智能体平台", "面向企业客户发布可编排的 AI 智能体与安全治理能力。"),
    ("Google 更新 Gemini 系列并开放多模态接口", "Gemini 系列模型升级，开放语音与视觉多模态能力。"),
    ("NVIDIA 发布新一代 GPU 与算力方案", "面向大规模推理发布新 GPU，并公布集群算力路线图。"),
    ("Meta 开源新一代大模型权重", "Meta 发布可商用权重模型，进一步推进开源生态。"),
    ("初创公司完成新一轮 AI 融资", "一家 AI 创业公司宣布完成新一轮融资，估值受关注。"),
    ("微软 Copilot 迎来重要功能更新", "Copilot 与 Office/Azure 深度集成，企业版能力增强。"),
    ("AI Agent 框架新增自动规划能力", "流行的 Agent 框架引入更可靠的规划与记忆机制。"),
    ("国产大模型集中发布并降价", "国内多家厂商发布新一代模型，推理成本显著下降。"),
    ("AI 安全与治理监管讨论升温", "多国就 AI 安全评估与合规框架展开新一轮讨论。"),
    ("开源社区发布高效微调工具", "社区版微调工具降低训练门槛，配合小模型方案走热。"),
    ("AI 编程助手进入日常研发", "代码助手在工程团队的复用率提升，逐渐成为标配。"),
    ("多模态视频生成模型取得进展", "视频生成质量与可控性进一步提升，面向创作落地。"),
    ("AI 芯片供应链出现新变化", "先进制程与封装产能成为 AI 算力供给的关键变量。"),
    ("搜索与信息获取被 AI 重塑", "新一代 AI 搜索与问答产品在真实使用中增长明显。"),
]

_SOURCE_POOL = [
    "techcrunch", "the-verge", "venturebeat", "mit-tr", "wired", "ars-technica",
    "the-information", "cnbc-tech", "reuters-tech", "openai-blog", "anthropic",
    "deepmind", "meta-ai", "google-research", "mistral", "cohere", "xai",
    "jiqizhixin", "qbitai", "36kr", "infoq-zh", "huxiu", "tmtpost", "geekpark",
    "xinzhiyuan", "producthunt", "hn", "showhn", "jike", "zhihu-ai", "v2ex", "juejin",
]


class Fetcher(ABC):
    """采集接口：给定日期，输出一批原始条目。"""

    def __init__(self, settings: Settings, registry: SourceRegistry,
                 builders: BuilderRegistry, fixtures_dir: Optional[str] = None,
                 seed: int = 20260821):
        self.settings = settings
        self.registry = registry
        self.builders = builders
        self.fixtures_dir = fixtures_dir or os.path.join(os.path.dirname(__file__), "fixtures")
        self.seed = seed

    @abstractmethod
    def acquire(self, day: date) -> List[RawItem]:
        ...


class FixtureFetcher(Fetcher):
    """离线采集：优先读 fixture，否则用确定性合成器生成（保证任何日期都能跑通）。"""

    def acquire(self, day: date) -> List[RawItem]:
        path = os.path.join(self.fixtures_dir, f"raw_{day.isoformat()}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            items = [RawItem(**it) for it in data["items"]]
        else:
            items = self._synthetic(day)
        return items

    # -- 确定性合成器 -------------------------------------------------------
    def _synthetic(self, day: date) -> List[RawItem]:
        rnd = random.Random(int(day.strftime("%Y%m%d")) ^ self.seed)
        pool = [s for s in self.registry.all if s.enabled]
        if not pool:
            pool = self.registry.all
        items: List[RawItem] = []
        n = rnd.randint(16, 24)
        topic_count = len(_TOPICS)
        for i in range(n):
            topic = _TOPICS[i % topic_count]
            src = rnd.choice(pool)
            published_dt = datetime(day.year, day.month, day.day, rnd.randint(6, 23), rnd.randint(0, 59))
            # 制造「时效性」样本：约 12% 是昨天的（用于门3 淘汰）
            if rnd.random() < 0.12:
                published_dt -= timedelta(days=1, hours=rnd.randint(1, 6))
            url = f"{src.base_url.rstrip('/')}/{day.strftime('%Y%m%d')}/{_slug(topic[0], i)}"
            summary = topic[1]
            builder = None
            # 约 30% 条目关联到某个 Builder（人物线）
            if rnd.random() < 0.30 and self.builders.all:
                builder = rnd.choice(self.builders.all)
            handle = None
            if builder and "x" in builder.handles:
                handle = builder.handles["x"]
            engagement = round(rnd.uniform(3, 980), 1)
            source_cred = src.credibility
            items.append(RawItem(
                id=f"raw-{day.strftime('%Y%m%d')}-{i}-{hashlib.sha1(url.encode()).hexdigest()[:6]}",
                source_id=src.id, source_name=src.name, source_type=src.type,
                source_lang=src.lang, source_credibility=source_cred,
                title=topic[0], summary=summary, url=url,
                published_at=published_dt.isoformat(timespec="seconds"),
                author_handle=handle,
                builder_id=builder.id if builder else None,
                builder_name=builder.name if builder else None,
                tags=_tags(topic[0]), engagement=engagement,
                raw_text=summary, fetched_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            ))
        # 制造「去重」样本：克隆某条到另一个低可信来源（标题相近，用于门2 合并）
        if len(items) >= 4:
            base = items[2]
            dup_src = next((s for s in pool if s.credibility < 0.66 and s.id != base.source_id), None)
            if dup_src:
                dup = RawItem(
                    id=f"raw-dup-{day.strftime('%Y%m%d')}-x",
                    source_id=dup_src.id, source_name=dup_src.name, source_type=dup_src.type,
                    source_lang=dup_src.lang, source_credibility=dup_src.credibility,
                    title=f"{base.title} —— 我们看到的最新报道",  # 语义相同、措辞略异
                    summary=base.summary, url=f"{dup_src.base_url.rstrip('/')}/{day.strftime('%Y%m%d')}/dup",
                    published_at=base.published_at, engagement=round(base.engagement * 0.4, 1),
                    tags=base.tags, raw_text=base.summary,
                )
                items.append(dup)
        return items


class WebFetcher(Fetcher):
    """真实联网适配器：Google News RSS(中英文多查询)。仅在有网络的环境使用(如 CI)。

    说明：
    - 真实新闻只能取「当天」；历史日期由逐日归档(data/archive)提供，
      所以对历史 day 返回 []（由 build_viewer 读归档补齐）。
    - 任一查询失败都跳过该查询，不影响整批；全部失败则当天无数据（不注入合成数据）。
    """

    def acquire(self, day: date) -> List[RawItem]:
        if day != date.today():
            return []  # 历史由归档提供，联网只取当天
        records: List[Any] = []
        for q in feeds.QUERIES_EN:
            try:
                records.extend(feeds.parse_rss(feeds.fetch_feed(feeds.feed_url(q, "en"))))
            except Exception:  # noqa: BLE001
                continue
        for q in feeds.QUERIES_ZH:
            try:
                records.extend(feeds.parse_rss(feeds.fetch_feed(feeds.feed_url(q, "zh"))))
            except Exception:  # noqa: BLE001
                continue
        if not records:
            return []
        items = feeds.build_raw_items(records, self.registry, self.builders, day)
        return self._dedup(items)

    def _dedup(self, items: List[RawItem]) -> List[RawItem]:
        seen_url, seen_title = set(), set()
        out: List[RawItem] = []
        for it in items:
            u = it.url or it.title
            if u in seen_url:
                continue
            key = normalize_title(it.title)
            for s in seen_title:
                if title_similarity(key, s) >= 0.55:
                    break
            else:
                seen_url.add(u)
                seen_title.add(key)
                out.append(it)
        return out


def _slug(text: str, i: int) -> str:
    h = hashlib.sha1(text.encode()).hexdigest()[:8]
    return f"item-{i}-{h}"


def _tags(title: str) -> List[str]:
    tags = ["AI"]
    lower = title.lower()
    if any(k in lower for k in ("gpu", "算力", "nvidia", "chip", "芯片", "grok")):
        tags.append("算力")
    if any(k in lower for k in ("开源", "weight", "model", "模型", "open")):
        tags.append("模型")
    if any(k in lower for k in ("agent", "智能体", "agent")):
        tags.append("Agent")
    if any(k in lower for k in ("融资", "funding", "估值", "startup", "初创")):
        tags.append("融资")
    if any(k in lower for k in ("安全", "监管", "治理", "policy", "合规")):
        tags.append("治理")
    return tags
