"""输出层：把结构化日报落成「人读 + 机器读 + 可导入多维表格」三种形态。

- report.md   人读日报（亮点速览 / 分类资讯 / 人物动态 / 趋势注记）
- report.json 结构化数据（供程序处理）
- report.csv  多维表格导入（飞书 / Notion / Airtable 等，一行一条）
"""
from __future__ import annotations

import csv
import json
import os
from datetime import date
from typing import Any, Dict, List

from .models import DailyReport

_CSV_HEADERS = ["日期", "标题", "摘要", "信源", "原文链接", "标签", "关联人物", "重要度", "分类"]


class ReportWriter:
    def __init__(self, output_root: str):
        self.output_root = output_root

    def write(self, report: DailyReport, day: date) -> Dict[str, str]:
        out_dir = os.path.join(self.output_root, day.isoformat())
        os.makedirs(out_dir, exist_ok=True)
        paths = {
            "markdown": os.path.join(out_dir, "report.md"),
            "json": os.path.join(out_dir, "report.json"),
            "csv": os.path.join(out_dir, "report.csv"),
        }
        self._write_markdown(paths["markdown"], report)
        self._write_json(paths["json"], report)
        self._write_csv(paths["csv"], report)
        return paths

    # -- markdown -----------------------------------------------------------
    def _write_markdown(self, path: str, report: DailyReport) -> None:
        lines: List[str] = []
        lines.append(f"# {report.title}")
        lines.append("")
        lines.append(f"> 生成时间：{report.generated_at}　|　该日通过 5 道质量门 {len(report.items)} 条")
        lines.append("")

        lines.append("## 亮点速览")
        for h in report.highlights:
            lines.append(f"- {h}")
        lines.append("")

        lines.append("## 分类资讯")
        for cat, cards in report.categories.items():
            lines.append(f"### {cat}")
            for c in cards:
                b = f"｜{c['builder']}" if c.get("builder") else ""
                lines.append(f"- **{c['title']}**{b} 　[{c['source']}]({c['url']})")
                lines.append(f"  {c['summary']}")
            lines.append("")

        if report.builder_dynamics:
            lines.append("## 人物动态")
            for c in report.builder_dynamics:
                lines.append(f"- **{c['builder']}**：{c['title']} 　[{c['source']}]({c['url']})")
                lines.append(f"  {c['summary']}")
            lines.append("")

        lines.append("## 趋势注记")
        for n in report.trend_notes:
            lines.append(f"- {n}")
        lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("*本日报由 AI 智讯日报 · 情报自动化引擎生成，所有条目附原始链接，可回溯核验。*")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))

    # -- json ---------------------------------------------------------------
    def _write_json(self, path: str, report: DailyReport) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(report.to_dict(), fh, ensure_ascii=False, indent=2)

    # -- csv ----------------------------------------------------------------
    def _write_csv(self, path: str, report: DailyReport) -> None:
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(_CSV_HEADERS)
            for cat, cards in report.categories.items():
                for c in cards:
                    writer.writerow([
                        report.report_date,
                        c["title"],
                        c["summary"],
                        c["source"],
                        c["url"],
                        "|".join(c["tags"]),
                        c.get("builder", ""),
                        c.get("importance", ""),
                        cat,
                    ])


def write_index(report_paths: List[Dict[str, str]], output_root: str) -> str:
    """写一份按日期倒序的索引列表，方便用户快速调用。"""
    path = os.path.join(output_root, "index.md")
    lines = ["# AI 智讯日报 · 已生成日报索引", ""]
    lines.append("| 日期 | 报告 | 结构化 | 多维表格 | 生成时间 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for p in report_paths:
        day = os.path.basename(os.path.dirname(p["markdown"]))
        lines.append(f"| {day} | [md]({p['markdown']}) | [json]({p['json']}) | [csv]({p['csv']}) | - |")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path
