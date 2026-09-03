"""流水线编排：把「采集 → 审核门 → 合成 → 输出」四段串成一条可运行的链路。

核心链路（与产品计划书一致）：
    触发 → 采集(信源/人物) → 5 道质量审核门 → 结构化合成 → 双形态输出
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from .builders import BuilderRegistry
from .config import Settings, load_settings
from .fetcher import Fetcher, FixtureFetcher, WebFetcher
from .models import DailyReport
from .quality import QualityEngine, QualityResult
from .report import ReportWriter, write_index
from .sources import SourceRegistry
from .synthesizer import Synthesizer, create_synthesizer


@dataclass
class RunResult:
    day: date
    report: DailyReport
    quality: QualityResult
    paths: Dict[str, str] = None  # type: ignore[assignment]


class Pipeline:
    def __init__(self, settings: Settings, fetcher: Fetcher, quality: QualityEngine,
                 synthesizer: Synthesizer, writer: ReportWriter):
        self.settings = settings
        self.fetcher = fetcher
        self.quality = quality
        self.synthesizer = synthesizer
        self.writer = writer
        self.registry = fetcher.registry
        self.builders = fetcher.builders

    def run_day(self, day: date, write: bool = True) -> RunResult:
        # 1) 采集
        raw = self.fetcher.acquire(day)
        # 2) 5 道质量审核门
        qres = self.quality.run(raw, day)
        # 3) 结构化合成
        report = self.synthesizer.synthesize(qres.qualified, day)
        # 4) 输出
        paths = self.writer.write(report, day) if write else None
        return RunResult(day=day, report=report, quality=qres, paths=paths)

    def backfill(self, days: int, end: Optional[date] = None, write: bool = True) -> List[RunResult]:
        """回填：从 end（默认今天）往前生成 days 份日报。"""
        end = end or date.today()
        results: List[RunResult] = []
        for offset in range(days):
            d = end - timedelta(days=offset)
            results.append(self.run_day(d, write=write))
        return results

    def write_index(self, results: Optional[List[RunResult]] = None) -> str:
        paths = [res.paths for res in (results or []) if res.paths]
        # 统一用当前流水线真正落盘的输出根目录，避免测试/多实例互相污染
        return write_index(paths, self.writer.output_root)


def build_pipeline(settings: Optional[Settings] = None,
                   output_root: Optional[str] = None,
                   fetcher_mode: str = "fixture") -> Pipeline:
    """装配默认流水线：fixture 离线采集 + 模板合成，可复现；部署可切 web + llm。"""
    settings = settings or load_settings()
    registry = SourceRegistry(settings)
    builders = BuilderRegistry(settings)
    root = output_root or settings.output.get("root", "output")
    if os.path.isabs(root):
        abs_root = root
    else:
        abs_root = os.path.join(os.path.dirname(__file__), "..", root)
    abs_root = os.path.normpath(abs_root)

    if fetcher_mode == "web":
        fetcher = WebFetcher(settings, registry, builders)
    else:
        fetcher = FixtureFetcher(settings, registry, builders)

    quality = QualityEngine(settings, registry, builders)
    synthesizer = create_synthesizer(settings)
    writer = ReportWriter(abs_root)
    return Pipeline(settings, fetcher, quality, synthesizer, writer)


def status_summary(results: List[RunResult]) -> str:
    lines = ["日期          采集条数  合格条数  通过率  输出"]
    for r in results:
        day = r.day.isoformat()
        q = r.quality
        rate = q.summary().get("survival_rate", 0)
        written = "✓" if r.paths else "-"
        lines.append(f"{day}    {q.gate_stats.get('input', 0):<6}  {len(q.qualified):<6}  {rate:<6.0%}   {written}")
    return "\n".join(lines)
