"""信源注册表访问：按可信度/语言/类别筛选，供采集层调度与审核门使用。"""
from __future__ import annotations

from typing import List

from .config import Settings
from .models import Source


class SourceRegistry:
    def __init__(self, settings: Settings):
        self._sources = settings.sources

    @property
    def all(self) -> List[Source]:
        return self._sources

    def by_id(self, source_id: str) -> Source | None:
        for s in self._sources:
            if s.id == source_id:
                return s
        return None

    def credibility(self, source_id: str) -> float:
        src = self.by_id(source_id)
        return src.credibility if src else 0.5

    def high_authority(self) -> List[Source]:
        return [s for s in self._sources if s.authority >= 0.8]

    def summary(self) -> dict:
        counts: dict = {}
        for s in self._sources:
            counts[s.category] = counts.get(s.category, 0) + 1
        return {"count": len(self._sources), "by_category": counts}

    def mid(self, source_id: str) -> Source | None:
        return self.by_id(source_id)
