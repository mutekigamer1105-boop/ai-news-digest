"""配置加载：信源注册表、Builder 注册表、流水线参数。

配置全部来自项目根目录的 config/ 目录，便于整包替换而无需改代码。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List

from .models import Builder, Source


def _path(name: str) -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "..", "config", name)


@dataclass
class Settings:
    sources: List[Source]
    builders: List[Builder]
    pipeline: Dict[str, Any]

    @property
    def gates(self) -> Dict[str, Any]:
        return self.pipeline.get("gates", {})

    @property
    def weights(self) -> Dict[str, Any]:
        return self.pipeline.get("weights", {})

    @property
    def report(self) -> Dict[str, Any]:
        return self.pipeline.get("report", {})

    @property
    def schedule(self) -> Dict[str, Any]:
        return self.pipeline.get("schedule", {})

    @property
    def output(self) -> Dict[str, Any]:
        return self.pipeline.get("output", {})


def load_settings() -> Settings:
    sources_cfg = _load_obj(_path("sources.json"))
    builders_cfg = _load_obj(_path("builders.json"))
    pipeline_cfg = _load_obj(_path("pipeline.json"))

    sources = [Source(**s) for s in sources_cfg.get("sources", []) if s.get("enabled", True)]
    builders = [Builder(**b) for b in builders_cfg.get("builders", [])]

    # 保证信源始终存在至少一个高可信背书，避免门1 全灭
    if not sources:
        sources = [Source(id="fallback", name="Fallback", type="media", lang="en",
                          category="erro", base_url="https://example.com", credibility=0.5)]

    return Settings(sources=sources, builders=builders, pipeline=pipeline_cfg)


def _load_obj(path: str) -> Dict[str, Any]:
    from .models import load_json
    return load_json(path)
