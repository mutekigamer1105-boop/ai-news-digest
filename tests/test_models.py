"""模型层基础测试。"""
from datetime import datetime

from digest.models import RawItem, normalize_title, title_similarity


def test_normalize_title_strips_punct_and_case():
    a = normalize_title("OpenAI 发布 新版模型！")
    assert a == normalize_title("openai 发布 新版模型")
    assert "！" not in a


def test_similar_title_high_similarity():
    a = "OpenAI 发布新一代推理模型"
    b = "OpenAI 发布新一代推理模型——我们看到的最新报道"
    assert title_similarity(a, b) > 0.5


def test_unrelated_title_low_similarity():
    assert title_similarity("NVIDIA 发布新 GPU", "AI 安全监管讨论升温") < 0.4


def test_rawitem_generates_id_from_url():
    it = RawItem(
        id="", source_id="x", source_name="X", source_type="media", source_lang="en",
        source_credibility=0.9, title="t", summary="s", url="https://a.example/1",
        published_at=datetime(2026, 8, 21, 9, 0).isoformat(),
    )
    assert it.id.startswith("raw-")
    assert len(it.id) > 8
