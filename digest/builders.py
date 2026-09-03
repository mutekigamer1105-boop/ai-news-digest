"""Builder 注册表访问：人物线输入，审核门4 的「人物加权」依据。"""
from __future__ import annotations

import re
from typing import List

from .config import Settings
from .models import Builder


class BuilderRegistry:
    def __init__(self, settings: Settings):
        self._builders = settings.builders

    @property
    def all(self) -> List[Builder]:
        return self._builders

    def by_id(self, builder_id: str) -> Builder | None:
        for b in self._builders:
            if b.id == builder_id:
                return b
        return None

    def find_by_handle(self, handle: str) -> Builder | None:
        h = handle.lower().lstrip("@")
        for b in self._builders:
            for v in b.handles.values():
                if v.lower().lstrip("@") == h:
                    return b
        return None

    def signal_hit(self, text: str) -> Builder | None:
        """若文本命中某 Builder 的 name/signal/handle，则视为该人物动态（门4 加权用）。"""
        t = text.lower()
        for b in self._builders:
            if b.name.lower() in t:
                return b
            for sig in b.signals:
                if sig.lower() in t:
                    return b
        return None

    def summary(self) -> dict:
        counts: dict = {}
        for b in self._builders:
            counts[b.category] = counts.get(b.category, 0) + 1
        return {"count": len(self._builders), "by_category": counts}
