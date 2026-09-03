"""命令行入口。

    python -m digest info
    python -m digest run --date today
    python -m digest backfill --days 7
    python -m digest list
    python -m digest show --date 2026-08-21
    python -m digest schedule --dry-run
    python -m digest install-schedule
    python -m digest uninstall-schedule
    python -m digest test
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from typing import List, Optional

from . import __app__, __version__
from .builders import BuilderRegistry
from .config import load_settings
from .scheduler import install_windows_task, next_run, uninstall_windows_task, NoonScheduler
from .sources import SourceRegistry
from . import pipeline as pipeline_mod
from . import backfill as backfill_mod


def _build_pipeline(fetcher_mode: Optional[str] = None):
    mode = fetcher_mode or os.environ.get("DIGEST_FETCHER", "fixture")
    return pipeline_mod.build_pipeline(fetcher_mode=mode)


def _parse_date(value: str) -> date:
    if value.lower() in ("today", "now"):
        return date.today()
    return date.fromisoformat(value)


def _cmd_info(args) -> int:
    settings = load_settings()
    sr = SourceRegistry(settings)
    br = BuilderRegistry(settings)
    src_sum = sr.summary()
    bld_sum = br.summary()
    print(f"{__app__}  v{__version__}")
    print(f"・信源：{src_sum['count']} 个 → " + "、".join(f"{k} {v}" for k, v in src_sum["by_category"].items()))
    print(f"・Builder：{bld_sum['count']} 位 → " + "、".join(f"{k} {v}" for k, v in bld_sum["by_category"].items()))
    print(f"・调度：每日 {settings.schedule.get('run_at', '12:00')} 自动更新")
    print(f"・采集模式：{os.environ.get('DIGEST_FETCHER', 'fixture')}（fixture=离线可复现 / web=联网）")
    return 0


def _cmd_run(args) -> int:
    day = _parse_date(args.date)
    p = _build_pipeline(args.fetcher)
    res = p.run_day(day, write=False)
    # 不落盘时也打印报告摘要，便于查看
    print(f"[run] {day.isoformat()} 合格 {len(res.report.items)} 条")
    print(pipeline_mod.status_summary([res]))
    if res.paths:
        print("output:", res.paths)
    return 0


def _cmd_backfill(args) -> int:
    days = args.days
    end = _parse_date(args.end) if args.end else date.today()
    p = _build_pipeline(args.fetcher)
    bf = backfill_mod.Backfiller(p)
    results = bf.run(days=days)
    weekly = bf.write_weekly(results)
    index = p.write_index(results)
    print(f"[backfill] 生成过去 {days} 天日报：")
    print(pipeline_mod.status_summary(results))
    print(f"[backfill] index → {index}")
    if weekly:
        print(f"[backfill] week.md → {weekly['md']}")
        print(f"[backfill] week.csv → {weekly['csv']}")
    return 0


def _cmd_list(args) -> int:
    root = _output_root()
    if not os.path.isdir(root):
        print("[list] 尚无输出，请先运行 backfill 或 run")
        return 0
    dirs = sorted((d for d in os.listdir(root) if _is_date(d)), reverse=True)
    for d in dirs:
        print(d)
    print(f"[list] 共 {len(dirs)} 天")
    return 0


def _cmd_show(args) -> int:
    day = _parse_date(args.date)
    md = os.path.join(_output_root(), day.isoformat(), "report.md")
    if not os.path.exists(md):
        print(f"[show] 未找到 {day.isoformat()} 的日报，请先运行 digest backfill")
        return 1
    print(open(md, "r", encoding="utf-8").read())
    return 0


def _cmd_schedule(args) -> int:
    settings = load_settings()
    hour, minute = _hour_minute(settings)
    if args.dry_run:
        print(f"[schedule] dry-run：下一次运行 {next_run(hour=hour, minute=minute):%Y-%m-%d %H:%M:%S}")
        return 0
    p = _build_pipeline(args.fetcher)
    marker = os.path.join(_output_root(), ".last_run_day")
    scheduler = NoonScheduler(job=lambda: _backfill_then_report(p),
                              hour=hour, minute=minute, marker_file=marker)
    print("[schedule] 常驻调度启动，每天中午 12:00 自动更新。Ctrl+C 退出。")
    scheduler.loop(dry_run=False)
    return 0


def _cmd_install_schedule(args) -> int:
    settings = load_settings()
    hour, minute = _hour_minute(settings)
    task = settings.schedule.get("task_name", "AI_News_Digest_Daily_Noon")
    ok, msg = install_windows_task(task, hour=hour, minute=minute)
    print(f"[install-schedule] {msg}")
    return 0 if ok else 1


def _cmd_uninstall_schedule(args) -> int:
    settings = load_settings()
    task = settings.schedule.get("task_name", "AI_News_Digest_Daily_Noon")
    ok, msg = uninstall_windows_task(task)
    print(f"[uninstall-schedule] {msg}")
    return 0 if ok else 1


def _cmd_test(args) -> int:
    print("[test] 跑通校验：用 fixture 离线模式跑一天，验证链路闭环……")
    p = _build_pipeline(args.fetcher)
    day = _parse_date(args.date)
    res = p.run_day(day, write=True)
    q = res.quality.summary()
    print(f"[test] ✓ {day.isoformat()} 采集 {q['total_input']} → 合格 {q['qualified']}"
          f"（通过率 {q['survival_rate']:.0%}）")
    print(f"[test] ✓ 生成报告 → {res.paths}")
    print("[test] ✓ 全链路（采集→审核→合成→输出）跑通")
    return 0


# --------------------------------------------------------------------------
def _output_root() -> str:
    settings = load_settings()
    root = settings.output.get("root", "output")
    return os.path.join(os.path.dirname(__file__), "..", root) if not os.path.isabs(root) else root


def _hour_minute(settings) -> tuple[int, int]:
    return int(settings.schedule.get("hour", 12)), int(settings.schedule.get("minute", 0))


def _is_date(name: str) -> bool:
    try:
        date.fromisoformat(name)
        return True
    except ValueError:
        return False


def _backfill_then_report(p):
    # 当天中午触发：保证生成当天报告并写入 index
    from .backfill import run_backfill
    run_backfill(p, days=1)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="digest", description=__app__)
    parser.add_argument("--version", action="version", version=f"{__app__} {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add(name: str, help_: str, opts=None):
        sp = sub.add_parser(name, help=help_)
        for args, kwargs in (opts or []):
            sp.add_argument(*args, **kwargs)
        return sp

    add("info", "展示信源/人物/调度配置")
    add("run", "生成某日日报", [(["--date"], {"default": "today"}), (["--fetcher"], {"default": None})])
    add("backfill", "回填近 N 天日报",
        [(["--days"], {"type": int, "default": 7}),
         (["--end"], {"default": None}),
         (["--fetcher"], {"default": None})])
    add("list", "列出已生成日报")
    add("show", "查看某日日报", [(["--date"], {"required": True})])
    add("schedule", "常驻中午 12:00 自动更新",
        [(["--dry-run"], {"action": "store_true"}),
         (["--fetcher"], {"default": None})])
    add("install-schedule", "注册 Windows 计划任务（每日 12:00）")
    add("uninstall-schedule", "删除 Windows 计划任务")
    add("test", "跑通校验", [(["--date"], {"default": "today"}), (["--fetcher"], {"default": None})])

    args = parser.parse_args(argv)

    handlers = {
        "info": _cmd_info,
        "run": _cmd_run,
        "backfill": _cmd_backfill,
        "list": _cmd_list,
        "show": _cmd_show,
        "schedule": _cmd_schedule,
        "install-schedule": _cmd_install_schedule,
        "uninstall-schedule": _cmd_uninstall_schedule,
        "test": _cmd_test,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
