"""pytest 共享 fixture。

说明：本环境沙箱禁止对系统临时目录（%TEMP%）做目录扫描，而 pytest 内置
tmp_path 依赖该目录。这里用「工作区下的 .scratch」作为隔离临时目录，保证
测试在当前可写目录内即可可靠地创建、写入与清理。
"""
from __future__ import annotations

import os
import shutil
import uuid

import pytest


@pytest.fixture
def scratch():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".scratch"))
    os.makedirs(root, exist_ok=True)
    d = os.path.join(root, "case_" + uuid.uuid4().hex[:10])
    os.makedirs(d, exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)
