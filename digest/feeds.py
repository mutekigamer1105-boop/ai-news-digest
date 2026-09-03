"""真实信源抓取：Google News RSS（中英文多查询，免费、无需 key、可达性高）。

核心是纯函数(可离线单测) + 一个联网抓取入口。部署时在 CI(海外)运行,本地沙箱
用它做离线解析测试。

- fetch_feed(url)        : urllib 拉取 RSS(仅联网调用)
- parse_rss(bytes)->list : 解析 RSS/Atom 为记录(可与网络解耦,离线测试)
- build_raw_items        : 记录 → RawItem(补信源可信度/人物归属)
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List
from urllib import request as urlreq

from .builders import BuilderRegistry
from .models import RawItem
from .sources import SourceRegistry

# Google News RSS 端点（q 需 URL 编码）
_GNEWS_EN = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
_GNEWS_ZH = "https://news.google.com/rss/search?q={q}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"

QUERIES_EN = [
    "artificial+intelligence", "AI+agent", "large+language+model",
    "OpenAI", "Anthropic+Claude", "NVIDIA+AI", "AI+startup+funding", "AI+model+release",
]
QUERIES_ZH = [
    "%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD",                # 人工智能
    "AI+%E5%A4%A7%E6%A8%A1%E5%9E%8B",                        # AI 大模型
    "AI+%E6%99%BA%E8%83%BD%E4%BD%93",                        # AI 智能体
    "OpenAI+%E4%B8%AD%E6%96%87",                              # OpenAI 中文
]

_UA = {"User-Agent": "Mozilla/5.0 (AI-News-Digest/1.0; +https://example.com)"}
_TIMEOUT = 25


def feed_url(query: str, lang: str = "en") -> str:
    tpl = _GNEWS_EN if lang == "en" else _GNEWS_ZH
    return tpl.format(q=query)


def fetch_feed(url: str, timeout: int = _TIMEOUT) -> bytes:
    """联网抓取一个 RSS 源。仅在有网络的环境调用(如 CI)。"""
    req = urlreq.Request(url, headers=_UA)
    with urlreq.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (固定 https 端点)
        return resp.read()


def parse_rss(data: bytes) -> List[Dict[str, Any]]:
    """解析 RSS/Atom,返回 [{title,link,published(iso),summary,source,lang}]。

    命名空间无关:按 localname 匹配,兼容 Google News / 常见 RSS 2.0 / Atom。
    """
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")
    root = ET.fromstring(data)
    records: List[Dict[str, Any]] = []
    for item in _findall(root, "item"):
        rec = {
            "title": _child_text(item, "title", ""),
            "link": _child_text(item, "link", ""),
            "published": "",
            "summary": _child_text(item, "description", ""),
            "source": _child_text(item, "source", ""),
        }
        pub = _child_text(item, "pubDate", "") or _child_text(item, "published", "") \
            or _child_text(item, "updated", "")
        if pub:
            rec["published"] = _parse_date(pub)
        if not rec["link"]:
            # Atom 的 link 是 <link href="..">
            for link in _findall(item, "link"):
                href = link.attrib.get("href", "")
                if href:
                    rec["link"] = href
                    break
        if rec["title"]:
            records.append(rec)
    return records


def build_raw_items(records: List[Dict[str, Any]], registry: SourceRegistry,
                    builders: BuilderRegistry, day: datetime | None = None) -> List[RawItem]:
    """把解析出的记录转成 RawItem:补信源可信度、归属人物、发布时间、标签。"""
    items: List[RawItem] = []
    for i, r in enumerate(records):
        publisher = r.get("source", "").strip()
        src = _match_source(publisher, registry)
        source_id = src.id if src else "news"
        source_name = src.name if src else (publisher or "Google News")
        cred = src.credibility if src else 0.62
        src_type = src.type if src else "media"
        src_lang = "zh" if _is_zh(r.get("title", "")) else ("en" if r.get("lang") else "en")
        builder = builders.signal_hit(r.get("title", "") + " " + r.get("summary", ""))
        published = r.get("published") or datetime.now(timezone.utc).isoformat()
        items.append(RawItem(
            id=f"web-{i}-{_hash(r.get('link', r.get('title', '')))}",
            source_id=source_id, source_name=source_name, source_type=src_type,
            source_lang=src_lang, source_credibility=cred,
            title=r.get("title", ""), summary=_clean_summary(r.get("summary", "")),
            url=r.get("link", ""), published_at=published,
            builder_id=builder.id if builder else None,
            builder_name=builder.name if builder else None,
            tags=_tags(r.get("title", "")), engagement=0.0,
            raw_text=r.get("summary", ""),
        ))
    return items


# --------------------------------------------------------------------------
def _findall(elem, localname: str):
    return [e for e in elem.iter() if e.tag.split("}")[-1] == localname]


def _child_text(elem, localname: str, default: str) -> str:
    for e in elem.iter():
        if e.tag.split("}")[-1] == localname:
            return (e.text or "").strip()
    return default


def _parse_date(value: str) -> str:
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().isoformat(timespec="seconds")
    except Exception:  # noqa: BLE001
        return datetime.now().astimezone().isoformat(timespec="seconds")


def _match_source(publisher: str, registry: SourceRegistry):
    pl = publisher.lower().strip()
    best = None
    best_score = 0
    for s in registry.all:
        nl = s.name.lower().strip()
        if not nl:
            continue
        if nl in pl or pl in nl:
            # 越长越准
            score = min(len(nl), len(pl))
            if score > best_score:
                best, best_score = s, score
    return best


def _is_zh(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _clean_summary(desc: str) -> str:
    s = re.sub(r"<[^>]+>", " ", desc)
    s = re.sub(r"\s+", " ", s).strip()
    # 去掉 Google News 常见的 "… 查看更多…" 尾巴
    s = re.sub(r"\s*….*$", "", s)
    return s[:200]


def _hash(text: str) -> str:
    import hashlib
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()[:10]


def _tags(title: str) -> List[str]:
    t = ["AI"]
    lower = title.lower()
    if any(k in lower for k in ("gpu", "算力", "nvidia", "chip", "芯片", "grok")):
        t.append("算力")
    if any(k in lower for k in ("开源", "weight", "model", "模型", "release", "open")):
        t.append("模型")
    if any(k in lower for k in ("agent", "智能体")):
        t.append("Agent")
    if any(k in lower for k in ("融资", "funding", "估值", "startup", "初创", "series")):
        t.append("融资")
    if any(k in lower for k in ("安全", "监管", "治理", "policy", "合规")):
        t.append("治理")
    return t
