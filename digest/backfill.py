"""7 天回填与汇总：按同一链路连续生成过去 N 天日报，并输出便于用户调用的聚合形态。

- 逐日生成 report.md / report.json / report.csv
- 额外产出 week.md（七天一览）与 week.csv（跨天多维表格），方便整体调用与沉淀。
"""
from __future__ import annotations

import csv
import json
import os
from datetime import date, timedelta
from typing import Any, Dict, List

from .models import DailyReport
from .pipeline import Pipeline, RunResult

_WEEK_CSV_HEADERS = ["日期", "标题", "摘要", "信源", "原文链接", "标签", "关联人物", "重要度", "分类"]


class Backfiller:
    def __init__(self, pipeline: Pipeline):
        self.pipeline = pipeline
        # 使用流水线真正落盘的输出根目录（与 ReportWriter 一致）
        self.output_root = pipeline.writer.output_root

    def run(self, days: int = 7, end: Optional[date] = None) -> List[RunResult]:
        return self.pipeline.backfill(days=days, end=end or date.today(), write=True)

    def write_weekly(self, results: List[RunResult]) -> Dict[str, str]:
        """汇总 7 天：写 week.md 与 week.csv。"""
        if not results:
            return {}
        out_dir = os.path.join(self.output_root, "weekly")
        os.makedirs(out_dir, exist_ok=True)
        md_path = os.path.join(out_dir, "week.md")
        csv_path = os.path.join(out_dir, "week.csv")
        self._write_week_md(md_path, results)
        self._write_week_csv(csv_path, results)
        return {"md": md_path, "csv": csv_path}

    def _write_week_md(self, path: str, results: List[RunResult]) -> None:
        lines = [f"# AI 智讯日报 · 近 {len(results)} 天汇总", ""]
        for r in results:
            rep = r.report
            lines.append(f"## {rep.report_date}　（该日合格 {len(rep.items)} 条）")
            for h in rep.highlights[:3]:
                lines.append(f"- {h}")
            if rep.builder_dynamics:
                lines.append("- 人物动态：" + "；".join(
                    f"{c['builder']}→{c['title']}" for c in rep.builder_dynamics[:3]))
            lines.append("")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))

    def _write_week_csv(self, path: str, results: List[RunResult]) -> None:
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(_WEEK_CSV_HEADERS)
            for r in results:
                for cat, cards in r.report.categories.items():
                    for c in cards:
                        writer.writerow([
                            r.report.report_date, c["title"], c["summary"], c["source"],
                            c["url"], "|".join(c["tags"]), c.get("builder", ""),
                            c.get("importance", ""), cat,
                        ])


def run_backfill(pipeline: Pipeline, days: int = 7) -> dict:
    results = Backfiller(pipeline).run(days=days)
    weekly = Backfiller(pipeline).write_weekly(results)
    index = pipeline.write_index(results)
    return {
        "days": days,
        "generated": [r.report.report_date for r in results],
        "weekly": weekly,
        "index": index,
    }
