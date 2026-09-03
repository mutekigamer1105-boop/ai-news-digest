"""每日中午 12:00 自动更新机制。

两种落地方式（可二选一，推荐都配）：
1) 内置调度环  `digest schedule`  —— 常驻进程，每天 12:00 触发一次，简单、跨平台。
2) 系统计划任务 `digest install-schedule` —— 注册 Windows 计划任务，进程每日被唤醒，
   更省资源、断电自动恢复、无需常驻。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from typing import Any, Optional


def next_run(now: Optional[datetime] = None, hour: int = 12, minute: int = 0) -> datetime:
    """下一次 12:00 的时间点（本地时区）。"""
    now = now or datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def is_due(now: Optional[datetime] = None, hour: int = 12, minute: int = 0) -> bool:
    now = now or datetime.now()
    if now.hour != hour or now.minute < minute:
        return False
    # 限定在本小时内、尚未超过太多（避免长时间空跑误触发多次）
    return True


class NoonScheduler:
    """内置调度环：每天中午 12:00 触发一次 job。"""

    def __init__(self, job, hour: int = 12, minute: int = 0,
                 poll_seconds: int = 30, marker_file: Optional[str] = None):
        self.job = job
        self.hour = hour
        self.minute = minute
        self.poll_seconds = poll_seconds
        self.marker_file = marker_file

    def _already_ran(self, day: date) -> bool:
        if not self.marker_file:
            return False
        if not os.path.exists(self.marker_file):
            return False
        with open(self.marker_file, "r", encoding="utf-8") as fh:
            return fh.read().strip() == day.isoformat()

    def _mark(self, day: date) -> None:
        if self.marker_file:
            with open(self.marker_file, "w", encoding="utf-8") as fh:
                fh.write(day.isoformat())

    def run_until_noon_once(self, now: Optional[datetime] = None) -> tuple[bool, str]:
        """只执行一次「今日未执行过则触发」，用于计划任务/单次校验。"""
        now = now or datetime.now()
        today = now.date()
        if not is_due(now, self.hour, self.minute):
            return False, f"not in run window (now {now:%H:%M}, window {self.hour:02d}:{self.minute:02d})"
        if self._already_ran(today):
            return False, f"today {today} already ran (marker)"
        self.job()
        self._mark(today)
        return True, f"ran job for {today}"

    def loop(self, dry_run: bool = False, max_iterations: Optional[int] = None) -> None:
        """常驻循环：阻塞直到每次 12:00。dry_run 只打印计划不真正执行。"""
        iterations = 0
        while True:
            nxt = next_run(hour=self.hour, minute=self.minute)
            if dry_run:
                print(f"[scheduler] next daily run at {nxt:%Y-%m-%d %H:%M:%S} (dry-run, not running)")
                return
            wait = (nxt - datetime.now()).total_seconds()
            print(f"[scheduler] sleeping {int(wait)}s until {nxt:%Y-%m-%d %H:%M:%S}")
            time.sleep(min(wait, self.poll_seconds))
            ran, msg = self.run_until_noon_once()
            if ran:
                print(f"[scheduler] {msg}")
            if max_iterations is not None:
                iterations += 1
                if iterations >= max_iterations:
                    return


# --------------------------------------------------------------------------
# Windows 计划任务集成
# --------------------------------------------------------------------------
def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def install_windows_task(task_name: str, hour: int = 12, minute: int = 0,
                         python_exe: Optional[str] = None) -> tuple[bool, str]:
    """注册每日 12:00 运行的 Windows 计划任务。

    用一个启动器 .bat 作为任务动作，规避 schtasks 对 && / 嵌套引号的解析问题。
    """
    python_exe = python_exe or sys.executable
    root = _project_root()
    launcher = os.path.join(root, "run_daily.bat")
    bat = f'@echo off\r\nchcp 65001 >nul\r\ncd /d "%~dp0"\r\n"{python_exe}" -m digest run --date today\r\n'
    with open(launcher, "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(bat)
    # 任务动作 = 启动 run_daily.bat（路径无空格，避免引号地狱）
    exe = ["schtasks", "/Create", "/F", "/TN", task_name,
           "/SC", "DAILY", "/ST", f"{hour:02d}:{minute:02d}",
           "/TR", launcher]
    try:
        subprocess.run(exe, check=True, capture_output=True, text=True, timeout=30)
        return True, f"task '{task_name}' registered daily at {hour:02d}:{minute:02d} (launcher: {launcher})"
    except Exception as exc:  # noqa: BLE001
        return False, f"schtasks failed: {exc}"


def uninstall_windows_task(task_name: str) -> tuple[bool, str]:
    try:
        subprocess.run(["schtasks", "/Delete", "/F", "/TN", task_name], check=True,
                       capture_output=True, text=True, timeout=30)
        return True, f"task '{task_name}' removed"
    except Exception as exc:  # noqa: BLE001
        return False, f"schtasks delete failed: {exc}"
