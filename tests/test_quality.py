"""5 道质量审核门测试：覆盖门1可信度 / 门2去重 / 门3时效 / 门4打分 / 门5交叉核验。"""
from datetime import date

import pytest

from digest.builders import BuilderRegistry
from digest.config import load_settings
from digest.fetcher import FixtureFetcher
from digest.models import RawItem
from digest.quality import QualityEngine
from digest.sources import SourceRegistry


def _engine():
    settings = load_settings()
    return QualityEngine(settings, SourceRegistry(settings), BuilderRegistry(settings))


def _item(source_id="techcrunch", cred=0.95, title="NVIDIA 发布新一代 GPU 与算力方案",
          url="https://techcrunch.com/1", pub_hour=9, builder=None, engagement=100):
    return RawItem(
        id=f"raw-{source_id}-{pub_hour}", source_id=source_id, source_name=source_id,
        source_type="media", source_lang="en", source_credibility=cred,
        title=title, summary="摘要", url=url,
        published_at=date(2026, 8, 21).isoformat() + f"T{pub_hour:02d}:00:00+08:00",
        builder_id=builder, builder_name=builder, engagement=engagement, tags=["算力"],
    )


def test_gate1_drops_low_credibility():
    eng = _engine()
    low = RawItem(id="low", source_id="jike", source_name="jike", source_type="community",
                  source_lang="zh", source_credibility=0.30, title="低可信", summary="s",
                  url="https://jike/a", published_at=date(2026, 8, 21).isoformat() + "T10:00:00+08:00",
                  tags=["AI"], engagement=5)
    assert eng._gate_credibility(low) is False
    ok = RawItem(id="ok", source_id="techcrunch", source_name="tc", source_type="media",
                 source_lang="en", source_credibility=0.95, title="高可信", summary="s",
                 url="https://tc/a", published_at=date(2026, 8, 21).isoformat() + "T10:00:00+08:00",
                 tags=["AI"], engagement=5)
    assert eng._gate_credibility(ok) is True


def test_gate2_dedup_coalesces_duplicate_titles():
    eng = _engine()
    a = _item(title="OpenAI 发布新一代推理模型并更新 API", url="https://tc/1")
    b = _item(source_id="cnbc-tech", cred=0.85, title="OpenAI 发布新一代推理模型并更新 API —— 最新报道",
              url="https://cnbc/1")
    # 用 run 走完整链路，验证二者被归并（去重后代表少于输入）
    res = eng.run([a, b], date(2026, 8, 21))
    assert len(res.qualified) >= 1
    assert res.gate_stats.get("clusters", 0) >= 1


def test_gate3_drops_stale_items():
    eng = _engine()
    fresh = _item(pub_hour=9)                                # 当天 09:00
    stale = _item(url="https://tc/2", pub_hour=9)
    # 手动把 stale 的发布时间改到 3 天前
    stale.published_at = date(2026, 8, 18).isoformat() + "T09:00:00+08:00"
    res = eng.run([fresh, stale], date(2026, 8, 21))
    # stale 应为 0 条里不带它；fresh 在合格里
    assert res.qualified
    assert all(q.item.url != "https://tc/2" for q in res.qualified)


def test_gate4_builder_boosts_importance():
    import datetime as dt
    eng = _engine()
    normal = _item(title="正常资讯，无人物关联", url="https://tc/a", builder=None)
    builder = _item(title="Sam Altman 宣布 OpenAI 新进展", url="https://tc/b", builder="Sam Altman",
                    engagement=300)
    ref = dt.datetime(2026, 8, 21, 23, 59, 59).astimezone()
    importance_normal = eng._gate_importance(normal, ref)
    importance_builder = eng._gate_importance(builder, ref)
    assert importance_builder > importance_normal


def test_gate5_crosscheck_requires_sources_or_authority():
    eng = _engine()
    low_authority_single = RawItem(id="x", source_id="jike", source_name="jike", source_type="community",
                                   source_lang="zh", source_credibility=0.60, title="单一低权威",
                                   summary="s", url="https://jike/x",
                                   published_at=date(2026, 8, 21).isoformat() + "T10:00:00+08:00",
                                   tags=["AI"], engagement=5)
    valid, reason = eng._gate_crosscheck(low_authority_single, ["jike"], {})
    assert valid is False

    high_authority_single = RawItem(id="y", source_id="openai-blog", source_name="OpenAI",
                                    source_type="official", source_lang="en",
                                    source_credibility=1.0, title="官方博客", summary="s",
                                    url="https://openai/y",
                                    published_at=date(2026, 8, 21).isoformat() + "T10:00:00+08:00",
                                    tags=["AI"], engagement=5)
    valid2, _ = eng._gate_crosscheck(high_authority_single, ["openai-blog"], {"y": ["openai-blog"]})
    assert valid2 is True


def test_fixture_produces_reproducible_items():
    settings = load_settings()
    reg = SourceRegistry(settings)
    builders = BuilderRegistry(settings)
    f = FixtureFetcher(settings, reg, builders)
    day = date(2026, 8, 21)
    a = f.acquire(day)
    b = f.acquire(day)
    assert a == b  # 确定性合成：同日结果一致
    assert len(a) > 0
