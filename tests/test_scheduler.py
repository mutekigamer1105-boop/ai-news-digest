"""调度器测试：中午 12:00 的 next_run / is_due / 单次触发与去重。"""
import os
from datetime import datetime

from digest.scheduler import NoonScheduler, is_due, next_run


def test_next_run_is_future_noon():
    nxt = next_run(datetime(2026, 8, 21, 9, 0))
    assert nxt.hour == 12 and nxt.minute == 0
    # 9:00 → 明天12点还是今天12点？应选今天12点（今天12点尚未到）
    assert nxt == datetime(2026, 8, 21, 12, 0)

    nxt2 = next_run(datetime(2026, 8, 21, 13, 0))
    assert nxt2 == datetime(2026, 8, 22, 12, 0)  # 已过今天12点 → 明天


def test_is_due_window():
    assert is_due(datetime(2026, 8, 21, 12, 0)) is True
    assert is_due(datetime(2026, 8, 21, 12, 30)) is True
    assert is_due(datetime(2026, 8, 21, 11, 59)) is False
    assert is_due(datetime(2026, 8, 21, 13, 0)) is False


def test_run_until_noon_once_respects_marker(scratch):
    marker = os.path.join(str(scratch), ".last_run_day")
    calls = {"n": 0}

    def job():
        calls["n"] += 1

    sched = NoonScheduler(job, hour=12, minute=0, marker_file=marker)
    # 12:00 当日 -> 应执行一次
    ran, msg = sched.run_until_noon_once(datetime(2026, 8, 21, 12, 5))
    assert ran is True and calls["n"] == 1
    # 再调用 -> 当日已标记，不再执行
    ran2, msg2 = sched.run_until_noon_once(datetime(2026, 8, 21, 12, 40))
    assert ran2 is False and calls["n"] == 1
