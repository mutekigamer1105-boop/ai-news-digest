"""生成层：把「过审的合格条目」合成一份结构化日报（DailyReport）。

提供两种适配器，核心链路一致：
- TemplateSynthesizer：确定性、零依赖、离线可复现，用于演示 / 测试 / 无密钥环境。
- APISynthesizer：调用 OpenAI 兼容的 LLM（读 env），用「模型笔记」润色亮点与趋势注记；
  无密钥时自动回落到模板合成，保证链路不断。
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections import Counter
from datetime import date
from typing import Any, Dict, List, Optional

from .config import Settings
from .models import DailyReport, QualifiedItem

_CATEGORY_MAP = {
    "算力": "算力与硬件",
    "模型": "模型与开源",
    "开源": "模型与开源",
    "Agent": "Agent 与智能体",
    "智能体": "Agent 与智能体",
    "融资": "融资与创业",
    "治理": "安全与治理",
}


class Synthesizer(ABC):
    def __init__(self, settings: Settings):
        self.settings = settings
        self.cfg = settings.report

    @abstractmethod
    def synthesize(self, qualified: List[QualifiedItem], day: date,
                   builder_dynamics: Optional[List[Dict[str, Any]]] = None) -> DailyReport:
        ...


class TemplateSynthesizer(Synthesizer):
    """确定性合成：不调用模型，规则化产出亮点、分类、人物线与趋势注记。"""

    def synthesize(self, qualified: List[QualifiedItem], day: date,
                   builder_dynamics: Optional[List[Dict[str, Any]]] = None) -> DailyReport:
        highlights_n = int(self.cfg.get("highlights_n", 5))
        max_items = int(self.cfg.get("max_items", 45))
        prefix = self.cfg.get("title_prefix", "AI 智讯日报")
        top = qualified[:max_items]

        highlights = self._highlights(top, highlights_n)
        categories = self._categorize(top)
        dynamics = builder_dynamics or self._builder_dynamics(top)
        trends = self._trend_notes(top)
        items = self._items(top)

        report = DailyReport(
            report_date=day.isoformat(),
            generated_at=_now(),
            title=f"{prefix} · {day.strftime('%Y-%m-%d')}",
            highlights=highlights,
            categories=categories,
            builder_dynamics=dynamics,
            trend_notes=trends,
            items=items,
            meta={
                "qualified_items": len(top),
                "top_importance": top[0].importance_score if top else 0.0,
                "synthesizer": self.__class__.__name__,
            },
        )
        return report

    def _highlights(self, top: List[QualifiedItem], n: int) -> List[str]:
        return [f"[{it.item.source_name}] {it.item.title} —— {it.item.summary[:80]}" for it in top[:n]]

    def _categorize(self, top: List[QualifiedItem]) -> Dict[str, List[Dict[str, Any]]]:
        cats: Dict[str, List[Dict[str, Any]]] = {}
        for it in top:
            label = self._category_label(it.item.tags)
            cats.setdefault(label, []).append(self._card(it))
        # 按类别内条数排序，空的剔除
        return {k: v for k, v in sorted(cats.items(), key=lambda kv: (-len(kv[1]), kv[0]))}

    def _builder_dynamics(self, top: List[QualifiedItem]) -> List[Dict[str, Any]]:
        dyn = [self._card(it) for it in top if it.item.builder_name]
        return dyn

    def _trend_notes(self, top: List[QualifiedItem]) -> List[str]:
        counter: Counter = Counter()
        for it in top:
            for t in it.item.tags:
                counter[t] += 1
        notes = []
        top_tags = [t for t, _ in counter.most_common(3)]
        if top_tags:
            notes.append(f"今日热议方向集中在：{'、'.join(top_tags)}。")
        if top:
            notes.append(f"最高重要度条目 {top[0].importance_score:.2f}，来自 {top[0].item.source_name}。")
        notes.append(f"共 {len(top)} 条通过 5 道审核门的当日核心信息。")
        return notes

    def _card(self, it: QualifiedItem) -> Dict[str, Any]:
        return {
            "title": it.item.title,
            "summary": it.item.summary,
            "source": it.item.source_name,
            "source_id": it.item.source_id,
            "url": it.item.url,
            "tags": it.item.tags,
            "builder": it.item.builder_name or "",
            "importance": it.importance_score,
        }

    def _items(self, top: List[QualifiedItem]) -> List[Dict[str, Any]]:
        return [self._card(it) for it in top]

    def _category_label(self, tags: List[str]) -> str:
        for t in tags:
            if t in _CATEGORY_MAP:
                return _CATEGORY_MAP[t]
        return "行业动态"


class APISynthesizer(TemplateSynthesizer):
    """OpenAI 兼容 LLM 合成器：在模板基础上用模型润色亮点与趋势注记。

    需要环境变量：DIGEST_LLM_API_KEY / DIGEST_LLM_BASE_URL / DIGEST_LLM_MODEL。
    未配置时回落到模板合成，保证链路不中断。
    """

    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.api_key = os.environ.get("DIGEST_LLM_API_KEY", "")
        self.base_url = os.environ.get("DIGEST_LLM_BASE_URL", "https://api.openai.com/v1")
        self.model = os.environ.get("DIGEST_LLM_MODEL", "gpt-4o-mini")

    def synthesize(self, qualified, day, builder_dynamics=None) -> DailyReport:
        base = super().synthesize(qualified, day, builder_dynamics)
        if not self.api_key:
            base.meta["synthesizer"] = "TemplateSynthesizer (API key missing)"
            return base
        try:
            narrative = self._llm_notes(base)
            if narrative:
                base.trend_notes = [narrative] + base.trend_notes
        except Exception as exc:  # noqa: BLE001
            base.meta["llm_error"] = str(exc)
        base.meta["synthesizer"] = self.__class__.__name__
        return base

    def _llm_notes(self, report: DailyReport) -> str:
        # 真实实现会 POST /chat/completions；此处保留一个可注入的调用点。
        # 部署时替换为 requests/httpx 调用，并把结构化条目作为上下文。
        raise NotImplementedError("请在有网络与密钥时启用真实 LLM 调用")


def create_synthesizer(settings: Settings) -> Synthesizer:
    """工厂：有 LLM 密钥用 APISynthesizer，否则用模板合成（离线可跑）。"""
    if os.environ.get("DIGEST_LLM_API_KEY"):
        return APISynthesizer(settings)
    return TemplateSynthesizer(settings)


def _now() -> str:
    from datetime import datetime
    return datetime.now().astimezone().isoformat(timespec="seconds")
