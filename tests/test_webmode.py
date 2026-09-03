"""真实新闻(web)链路测试：RSS 解析、人物归属、归档往返、web 模式组装。

离线进行：用一份 Google News RSS 样本解析，不联网。
"""
import os
from datetime import date

import pytest

from digest import feeds, store
from digest.builders import BuilderRegistry
from digest.config import load_settings
from digest.sources import SourceRegistry
from digest.models import RawItem

# 一份简化但结构真实的 Google News RSS 样本
SAMPLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>Google News</title>
  <item>
    <title>OpenAI releases a new reasoning model</title>
    <link>https://example.com/openai-reasoning</link>
    <pubDate>Thu, 04 Sep 2026 08:30:00 GMT</pubDate>
    <description>OpenAI announces a new reasoning model with updated tool calling.</description>
    <source url="https://techcrunch.com">TechCrunch</source>
  </item>
  <item>
    <title>NVIDIA announces next-gen GPU for AI inference</title>
    <link>https://example.com/nvidia-gpu</link>
    <pubDate>Thu, 04 Sep 2026 07:00:00 GMT</pubDate>
    <description>Jensen Huang unveils a new GPU and compute roadmap.</description>
    <source url="https://www.reuters.com">Reuters</source>
  </item>
  <item>
    <title>Sam Altman teases a new model release</title>
    <link>https://example.com/altman</link>
    <pubDate>Thu, 03 Sep 2026 20:00:00 GMT</pubDate>
    <description>Sam Altman shares a hint on X about the next model.</description>
    <source url="https://www.theverge.com">The Verge</source>
  </item>
</channel>
</rss>
"""


def test_parse_rss_extracts_records():
    recs = feeds.parse_rss(SAMPLE_RSS)
    assert len(recs) == 3
    assert recs[0]["title"].startswith("OpenAI")
    assert recs[0]["source"] == "TechCrunch"
    assert recs[0]["link"].startswith("https://")
    assert recs[0]["published"]  # ISO 时间


def test_build_raw_items_attributes_source_and_builder():
    settings = load_settings()
    reg, bld = SourceRegistry(settings), BuilderRegistry(settings)
    recs = feeds.parse_rss(SAMPLE_RSS)
    items = feeds.build_raw_items(recs, reg, bld)
    assert len(items) == 3
    # TechCrunch 命中注册表 → 可信度、来源类型对齐
    tc = next(i for i in items if i.source_name == "TechCrunch")
    assert tc.source_credibility >= 0.6
    # Reuters 也是注册表内
    reuters = next(i for i in items if i.url.endswith("nvidia-gpu"))
    assert reuters.source_id == "reuters-tech"
    # 人物归属：Sam Altman 与 NVIDIA(Jensen Huang) 命中 builder
    altman = next(i for i in items if "/altman" in i.url)
    assert altman.builder_name == "Sam Altman"
    assert all(i.url and i.url.startswith("https://") for i in items)


def test_store_roundtrip_dedup(monkeypatch, scratch):
    monkeypatch.setenv("DIGEST_ARCHIVE_DIR", str(scratch))
    settings = load_settings()
    reg, bld = SourceRegistry(settings), BuilderRegistry(settings)
    recs = feeds.parse_rss(SAMPLE_RSS)
    items = feeds.build_raw_items(recs, reg, bld)
    # 第一次入库，全部新增
    added = store.save_items(items)
    assert sum(added.values()) == 3
    # 再次入库同一批 → 全部去重，不重复新增
    added2 = store.save_items(items)
    assert sum(added2.values()) == 0
    # 按发布日期归档，今天应至少有一篇(09-04)
    loaded = store.load_raw(date(2026, 9, 4))
    assert len(loaded) >= 1
    assert loaded[0].url.startswith("https://")


def test_build_bundle_web_uses_archive(monkeypatch, scratch):
    monkeypatch.setenv("DIGEST_ARCHIVE_DIR", str(scratch))
    settings = load_settings()
    reg, bld = SourceRegistry(settings), BuilderRegistry(settings)
    recs = feeds.parse_rss(SAMPLE_RSS)
    store.save_items(feeds.build_raw_items(recs, reg, bld))
    from build_viewer import build_bundle_web
    bundle = build_bundle_web(30)
    assert bundle["mode"] == "web"
    assert len(bundle["days"]) >= 1
    assert bundle["days"][0]["items"]
    assert bundle["meta"]["total_items"] >= 1
    # 归档统计正确
    assert bundle["meta"]["archive"]["days"] >= 1
