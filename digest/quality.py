"""5 道质量审核门：把「采集到的原始条目」过滤成「可信、去重、时效、重要、可溯源」的合格条目。

门1 信源可信度  —— 低可信信源直接淘汰
门2 去重/同类合并 —— 跨信源同源消息归一，保留最佳代表
门3 时效性       —— 只保留报告窗口内的最新信息
门4 重要性打分   —— 加权排序，保留 Top-N
门5 事实/来源交叉核验 —— 需多个独立信源背书或来自高权威信源

输出：合格条目 + 每条的审核门结果，供「生成层」合成结构化日报。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from .builders import BuilderRegistry
from .models import QualifiedItem, RawItem, title_similarity
from .sources import SourceRegistry


@dataclass
class GateOutcome:
    passed: bool
    reason: str


@dataclass
class QualityResult:
    qualified: List[QualifiedItem] = field(default_factory=list)
    gate_stats: Dict[str, int] = field(default_factory=dict)
    dropped: List[Dict[str, Any]] = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        total = sum(self.gate_stats.values()) if self.gate_stats else len(self.dropped)
        return {
            "qualified": len(self.qualified),
            "total_input": self.gate_stats.get("input", 0),
            "gate_stats": self.gate_stats,
            "survival_rate": round(len(self.qualified) / max(1, self.gate_stats.get("input", 1)), 3),
        }


class QualityEngine:
    def __init__(self, settings, registry: SourceRegistry, builders: BuilderRegistry):
        self.cfg = settings
        self.registry = registry
        self.builders = builders
        self.gates = settings.gates
        self.weights = settings.weights

    # -- 入口 ---------------------------------------------------------------
    def run(self, items: List[RawItem], report_day: date) -> QualityResult:
        result = QualityResult()
        result.gate_stats["input"] = len(items)

        # 门1 信源可信度
        g1 = [i for i in items if self._gate_credibility(i)]
        result.gate_stats["gate1_credibility_fail"] = len(items) - len(g1)

        # 门2 去重：先按可信度降序处理，保证高可信者成为代表
        ordered = sorted(g1, key=lambda i: i.source_credibility, reverse=True)
        clusters = self._cluster(ordered)
        result.gate_stats["clusters"] = len(clusters)
        result.gate_stats["gate2_dedup_dropped"] = len(ordered) - len(clusters)

        # 门5 需要在聚簇维度算独立信源数，先并行记
        cluster_sources: Dict[str, list] = defaultdict(list)
        for label, members in clusters.items():
            cluster_sources[label] = [m.source_id for m in members]

        # 门3 + 门4 + 门5 逐条判定
        reference = datetime(report_day.year, report_day.month, report_day.day, 23, 59, 59).astimezone()
        scored: List[QualifiedItem] = []
        for label, members in clusters.items():
            representative = members[0]
            # 门3
            recent, rec_reason = self._gate_recency(representative, reference)
            if not recent:
                result.gate_stats["gate3_recency_fail"] = result.gate_stats.get("gate3_recency_fail", 0) + len(members)
                result.dropped.append({"id": representative.id, "gate": 3, "reason": rec_reason})
                continue
            # 门4 打分
            importance = self._gate_importance(representative, reference)
            # 门5 交叉核验
            validated, val_reason = self._gate_crosscheck(representative, cluster_sources[label], cluster_sources)
            if not validated:
                result.gate_stats["gate5_crosscheck_fail"] = result.gate_stats.get("gate5_crosscheck_fail", 0) + 1
                result.dropped.append({"id": representative.id, "gate": 5, "reason": val_reason})
                continue
            q = QualifiedItem(
                item=representative,
                credibility_score=representative.source_credibility,
                dedup_key=label,
                is_recent=recent,
                importance_score=round(importance, 4),
                validated=validated,
                gate_results={
                    "gate1_credibility": True,
                    "gate2_dedup": members[0].id == representative.id,
                    "gate3_recency": True,
                    "gate4_importance": True,
                    "gate5_crosscheck": True,
                },
                passed=True,
            )
            scored.append(q)

        # 门4 的“保留 Top-N”：按重要性排序后保留前 N
        top_n = int(self.gates.get("importance_top_n", 12))
        scored.sort(key=lambda q: q.importance_score, reverse=True)
        ranked = scored[:top_n]

        result.qualified = ranked
        result.gate_stats["qualified"] = len(ranked)
        result.gate_stats["kept_top_n"] = len(ranked)
        return result

    # -- 各门实现 -----------------------------------------------------------
    def _gate_credibility(self, item: RawItem) -> bool:
        return item.source_credibility >= float(self.gates.get("credibility_min", 0.60))

    def _cluster(self, ordered: List[RawItem]) -> Dict[str, List[RawItem]]:
        clusters: Dict[str, List[RawItem]] = {}
        rep_by_key: Dict[str, RawItem] = {}
        threshold = 0.45
        for item in ordered:
            matched = None
            for key, rep in rep_by_key.items():
                if title_similarity(item.title, rep.title) >= threshold:
                    matched = key
                    break
            if matched is None:
                key = item.id
                rep_by_key[key] = item
                clusters[key] = [item]
            else:
                clusters[matched].append(item)
        return clusters

    def _gate_recency(self, item: RawItem, reference: datetime) -> tuple[bool, str]:
        hours = float(self.gates.get("recency_hours", 26))
        published = item.published
        delta = (reference - published).total_seconds() / 3600.0
        # 允许轻微的未来时间戳误差
        if -2.0 <= delta <= hours:
            return True, f"within {hours}h window"
        return False, f"stale {delta:.1f}h from report window"

    def _gate_importance(self, item: RawItem, reference: datetime) -> float:
        w = self.weights
        credibility = item.source_credibility
        authority = self.registry.by_id(item.source_id).authority if self.registry.by_id(item.source_id) else 0.6
        # 时效因子
        hours = float(self.gates.get("recency_hours", 26))
        delta = max(0.0, (reference - item.published).total_seconds() / 3600.0)
        recency = 1.0 if delta <= 0 else max(0.0, 1.0 - delta / hours)
        builder = 1.0 if item.builder_id else 0.0
        engagement = min(item.engagement / 1000.0, 1.0)
        keyword = 1.0 if (item.tags or "agent" in item.title.lower()) else 0.0
        score = (
            float(w.get("credibility", 0.35)) * credibility
            + float(w.get("authority", 0.20)) * authority
            + float(w.get("recency", 0.15)) * recency
            + float(w.get("builder", 0.15)) * builder
            + float(w.get("engagement", 0.10)) * engagement
            + float(w.get("keyword", 0.05)) * keyword
        )
        return round(score, 4)

    def _gate_crosscheck(self, item: RawItem, member_sources: List[str],
                         all_clusters: Dict[str, list]) -> tuple[bool, str]:
        distinct = set(member_sources)
        min_ref = int(self.gates.get("cross_ref_min", 2))
        src = self.registry.by_id(item.source_id)
        # 高权威（官方 1.0 / 媒体 0.8）自身可信；产品/社区类需跨信源背书
        high_authority = src is not None and src.authority >= 0.80
        if len(distinct) >= min_ref or high_authority:
            return True, f"{len(distinct)} independent source(s) / high-authority"
        return False, "single non-authoritative source, insufficient cross-check"
