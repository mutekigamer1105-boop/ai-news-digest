"""流水线端到端测试：跑通并校验输出产物。"""
import json
import os
from datetime import date

from digest.backfill import run_backfill
from digest.pipeline import build_pipeline, status_summary


def test_pipeline_run_day_writes_outputs(scratch):
    pipeline = build_pipeline(output_root=str(scratch), fetcher_mode="fixture")
    res = pipeline.run_day(date(2026, 8, 21), write=True)
    assert res.report.report_date == "2026-08-21"
    assert res.paths is not None
    assert os.path.exists(res.paths["markdown"])
    assert os.path.exists(res.paths["json"])
    assert os.path.exists(res.paths["csv"])
    # 报告含原始链接与亮点
    md = open(res.paths["markdown"], encoding="utf-8").read()
    assert "亮点速览" in md and "https://" in md
    data = json.load(open(res.paths["json"], encoding="utf-8"))
    assert data["items"] and data["report_date"] == "2026-08-21"


def test_pipeline_backfill_7_days(scratch):
    pipeline = build_pipeline(output_root=str(scratch), fetcher_mode="fixture")
    summary = run_backfill(pipeline, days=7)
    assert len(summary["generated"]) == 7
    for d in summary["generated"]:
        rd = os.path.join(str(scratch), d, "report.md")
        assert os.path.exists(rd), f"missing report for {d}"
    # index 与 weekly 必须落在本实例的输出根目录（不污染真实 output）
    assert summary["index"].startswith(str(scratch))
    assert summary["weekly"]["md"].startswith(str(scratch))
    assert os.path.exists(summary["index"])
    assert os.path.exists(summary["weekly"]["md"])
    assert os.path.exists(summary["weekly"]["csv"])
    # index 内容中的链接也应指向本实例目录
    idx = open(summary["index"], encoding="utf-8").read()
    assert str(scratch) in idx and ".scratch" in idx


def test_pipeline_status_line_prints():
    pipeline = build_pipeline(output_root="output", fetcher_mode="fixture")
    res = pipeline.backfill(days=2, end=date(2026, 8, 21), write=False)
    s = status_summary(res)
    assert "2026-08-21" in s and "2026-08-20" in s
