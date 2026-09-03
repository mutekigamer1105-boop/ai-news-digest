"""英文 AI 新闻 → 简体中文 翻译钩子(DeepSeek / OpenAI 兼容接口)。

说明:
- 真实调用需要网络(在 GitHub Actions 上运行);本地沙箱无外网,用 mock 单测逻辑。
- 未配置 DIGEST_LLM_API_KEY 或调用失败时,回落到原文,保证整体流程不中断。
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List
from urllib import request as urlreq

from .models import RawItem

DEFAULT_BASE = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"


def is_zh(text: str | None) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def call_chat(messages: List[Dict[str, str]], api_key: str, base: str, model: str,
              timeout: int = 90) -> str:
    """调用 OpenAI 兼容的 /chat/completions,返回助手文本。"""
    body = json.dumps({"model": model, "messages": messages, "temperature": 0.2,
                       "response_format": {"type": "json_object"}}).encode("utf-8")
    req = urlreq.Request(base.rstrip("/") + "/chat/completions", data=body, method="POST",
                         headers={"Content-Type": "application/json",
                                  "Authorization": "Bearer " + api_key})
    with urlreq.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def _extract_json(text: str) -> Dict[str, Any]:
    """从模型输出中提取 JSON(容忍 ```json 围栏与多余文本)。"""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    return json.loads(text)


def translate_items(items: List[RawItem], api_key: str | None = None,
                    base: str | None = None, model: str | None = None) -> List[RawItem]:
    """把非中文的标题/摘要翻译为中文(批量一次请求)。无 key 或失败则返回原文。"""
    api_key = api_key if api_key is not None else os.environ.get("DIGEST_LLM_API_KEY", "")
    if not api_key:
        return items
    base = base or os.environ.get("DIGEST_LLM_BASE_URL", DEFAULT_BASE)
    model = model or os.environ.get("DIGEST_LLM_MODEL", DEFAULT_MODEL)

    positions = [i for i, it in enumerate(items) if not is_zh(it.title)]
    if not positions:
        return items

    tasks = [{"i": i, "title": items[i].title, "summary": items[i].summary} for i in positions]
    sys_msg = "你是专业科技翻译。把给定的英文 AI 新闻标题与摘要翻译成简体中文。标题要简洁有力，摘要通顺自然，保留专有名词。只输出 JSON。"
    user_msg = json.dumps({
        "tasks": tasks,
        "output_schema": {"translations": [{"i": 0, "zh_title": "", "zh_summary": ""}]},
    }, ensure_ascii=False)
    try:
        text = call_chat([{"role": "system", "content": sys_msg},
                          {"role": "user", "content": user_msg}], api_key, base, model)
        data = _extract_json(text)
        tr_map: Dict[int, tuple[str, str]] = {}
        for t in data.get("translations", []):
            try:
                tr_map[int(t.get("i"))] = (t.get("zh_title") or "", t.get("zh_summary") or "")
            except (TypeError, ValueError):
                continue
        for i in positions:
            zh = tr_map.get(i)
            if zh:
                items[i].title = zh[0] or items[i].title
                items[i].summary = zh[1] or items[i].summary
    except Exception:  # noqa: BLE001 —— 翻译失败不阻断流程
        pass
    return items
