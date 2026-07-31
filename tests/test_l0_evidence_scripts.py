import importlib.util
import io
import json
import sys
import types
from pathlib import Path

import pytest


SKILL_SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / ".agents"
    / "skills"
    / "research-gameplay-systems"
    / "scripts"
)


def load_script(name: str):
    path = SKILL_SCRIPTS / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_bilibili_video_id_parsing_and_output(tmp_path):
    module = load_script("extract_bilibili_l0.py")
    assert module.parse_video_key("https://www.bilibili.com/video/BV19h4y1K7yM") == (
        "bvid",
        "BV19h4y1K7yM",
    )
    assert module.parse_video_key("av617673117") == ("aid", "617673117")

    output = tmp_path / "pack"
    output.mkdir()
    segments = [module.Segment("S-00001", 1.2, 3.4, "机制说明", "official_subtitle")]
    module.write_outputs(
        output,
        {
            "bvid": "BV19h4y1K7yM",
            "aid": 617673117,
            "title": "测试视频",
            "desc": "",
            "duration": 10,
            "owner": {"name": "公开作者", "mid": 123},
        },
        {"cid": 456, "page": 1, "part": "P1", "duration": 10},
        segments,
        {"available": True, "source": "official_subtitle"},
        None,
        None,
    )
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["evidence_level"] == "L0"
    assert manifest["segment_count"] == 1
    assert manifest["duration_sec"] == 10
    assert manifest["tail_coverage_ratio"] == 0.34
    assert "[00:00:01–00:00:03]" in (output / "transcript.md").read_text(encoding="utf-8")


def test_bilibili_windows_cuda_dll_setup_is_safe():
    module = load_script("extract_bilibili_l0.py")
    configured = module.configure_windows_cuda_dlls()
    assert isinstance(configured, list)


def test_bilibili_rejects_partial_multi_segment_media(monkeypatch):
    module = load_script("extract_bilibili_l0.py")
    monkeypatch.setattr(
        module,
        "request_json",
        lambda *args, **kwargs: {
            "data": {"durl": [{"url": "https://example/1"}, {"url": "https://example/2"}]}
        },
    )
    with pytest.raises(RuntimeError, match="拒绝只转写其中一段"):
        module.choose_play_url(1, "BV1test", 2)


def test_bilibili_media_download_retries_transient_network_error(tmp_path, monkeypatch):
    module = load_script("extract_bilibili_l0.py")
    calls = 0

    def fake_urlopen(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise module.urllib.error.URLError("temporary TLS timeout")
        response = io.BytesIO(b"full")
        response.headers = {"Content-Length": "4"}
        return response

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(module.time, "sleep", lambda *_: None)
    destination = tmp_path / "source.mp4"
    module.download_media("https://example/video", destination, max_bytes=10, attempts=2)
    assert calls == 2
    assert destination.read_bytes() == b"full"


def test_bilibili_repairs_common_chinese_mojibake():
    module = load_script("extract_bilibili_l0.py")
    assert module.repair_mojibake("ã€åŽŸç¥žã€‘") == "【原神】"
    assert module.repair_mojibake("´ó¼ÒºÃ") == "大家好"
    assert module.repair_mojibake("正常中文") == "正常中文"


def test_bilibili_auto_language_uses_whisper_detection(monkeypatch, tmp_path):
    module = load_script("extract_bilibili_l0.py")
    captured = {}

    class FakeInfo:
        language = "en"

    class FakeModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, path, **kwargs):
            captured.update(kwargs)
            return iter(()), FakeInfo()

    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        types.SimpleNamespace(WhisperModel=FakeModel),
    )
    segments, info = module.transcribe_with_device(
        tmp_path / "audio.wav", "small", "auto", "cpu", "int8", 1
    )

    assert segments == []
    assert info.language == "en"
    assert captured["language"] is None


def test_bilibili_large_v3_cpu_requires_opt_in(monkeypatch, tmp_path):
    module = load_script("extract_bilibili_l0.py")
    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        types.SimpleNamespace(WhisperModel=object),
    )
    monkeypatch.setattr(module, "resolve_device", lambda requested: ("cpu", "int8"))

    with pytest.raises(RuntimeError, match="large-v3.*CPU"):
        module.transcribe_audio(
            tmp_path / "audio.wav", "large-v3", "auto", "auto", 1
        )


def test_zhihu_full_text_is_segmented_and_short_summary_rejected(tmp_path, monkeypatch):
    module = load_script("build_zhihu_l0.py")
    input_path = tmp_path / "contents.jsonl"
    long_text = "第一段说明系统目标。" * 100
    rows = [
        {
            "content_id": "100",
            "content_type": "answer",
            "content_text": long_text,
            "content_url": "https://www.zhihu.com/question/1/answer/100",
            "title": "深度回答",
        },
        {
            "content_id": "101",
            "content_type": "answer",
            "content_text": "只有搜索摘要",
            "content_url": "https://www.zhihu.com/question/1/answer/101",
            "title": "短摘要",
        },
    ]
    input_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    output = tmp_path / "pack"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_zhihu_l0.py",
            "--input",
            str(input_path),
            "--output",
            str(output),
            "--min-chars",
            "100",
            "--segment-chars",
            "80",
        ],
    )
    assert module.main() == 0
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["document_count"] == 1
    assert manifest["segment_count"] > 1
    assert manifest["skipped"][0]["content_id"] == "101"
    assert (output / "review_queue.csv").is_file()
    document = json.loads((output / "documents.jsonl").read_text(encoding="utf-8"))
    first_segment = json.loads(
        (output / "segments.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert first_segment["text"] == document["body"][
        first_segment["char_start"] : first_segment["char_end"]
    ]


def test_research_case_initializes_deep_evidence_structure(tmp_path, monkeypatch):
    module = load_script("init_research_case.py")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "init_research_case.py",
            "--game",
            "测试游戏",
            "--output",
            str(tmp_path),
        ],
    )
    assert module.main() == 0
    case_dir = tmp_path / "测试游戏"
    assert (case_dir / "l0-private" / "bili").is_dir()
    assert (case_dir / "l0-private" / "zhihu").is_dir()
    assert (case_dir / "deep-source-register.csv").is_file()
    assert (case_dir / "l0-manifest.csv").is_file()


def test_zhihu_media_skips_noscript_duplicate_of_every_figure():
    module = load_script("extract_zhihu_media.py")
    # Zhihu ships each figure twice: a <noscript> copy plus the lazy-loaded one.
    html = (
        "<p>机制说明如下。</p>"
        "<figure>"
        "<noscript><img src=\"https://pic1.zhimg.com/v2-a.jpg\" data-rawwidth=\"800\"></noscript>"
        "<img class=\"lazy\" src=\"https://pic1.zhimg.com/v2-a_b.jpg\""
        " data-original=\"https://pic1.zhimg.com/v2-a.jpg\" data-rawwidth=\"800\">"
        "<figcaption>伤害结算顺序</figcaption>"
        "</figure>"
    )
    assets = module.collect_assets(html)
    assert len(assets) == 1
    # data-original is the full-resolution asset; src is a blurred thumbnail.
    assert assets[0]["source_url"] == "https://pic1.zhimg.com/v2-a.jpg"
    assert assets[0]["caption"] == "伤害结算顺序"
    assert assets[0]["asset_kind"] == "image"


def test_zhihu_media_anchors_asset_to_preceding_plain_text():
    module = load_script("extract_zhihu_media.py")
    html = "<p>前面的机制描述。</p><img data-original=\"https://pic1.zhimg.com/v2-b.png\"><p>后续说明。</p>"
    asset = module.collect_assets(html)[0]
    assert asset["text_offset"] == len("前面的机制描述。")
    assert asset["preceding_text"].endswith("前面的机制描述。")

    segments = [
        {"segment_id": "ZH-answer-1-P0001", "text": "前面的机制描述。", "char_start": 0, "char_end": 8},
        {"segment_id": "ZH-answer-1-P0002", "text": "后续说明。", "char_start": 8, "char_end": 13},
    ]
    assert module.locate_segment(segments, asset) == "ZH-answer-1-P0001"


def test_zhihu_media_records_formula_tex_instead_of_downloading_it():
    module = load_script("extract_zhihu_media.py")
    html = r'<p>期望值</p><img eeimg="1" data-formula="E = \sum p_i v_i" src="//zhihu.com/equation?tex=E">'
    assets = module.collect_assets(html)
    assert len(assets) == 1
    assert assets[0]["asset_kind"] == "formula"
    assert assets[0]["formula_tex"] == r"E = \sum p_i v_i"


def test_zhihu_media_detects_animated_gif_and_file_extension():
    module = load_script("extract_zhihu_media.py")
    still = b"GIF89a" + b"\x00" * 32 + b"\x21\xf9\x04" + b"\x00" * 8
    animated = still + b"\x21\xf9\x04" + b"\x00" * 8
    assert module.is_animated_gif(animated) is True
    assert module.is_animated_gif(still) is False
    assert module.is_animated_gif(b"\x89PNG\r\n\x1a\n") is False
    assert module.extension_for("https://pic1.zhimg.com/x", animated) == ".gif"
    assert module.extension_for("https://pic1.zhimg.com/x", b"\x89PNG\r\n\x1a\n") == ".png"


def test_zhihu_media_extracts_content_html_from_init_data():
    module = load_script("extract_zhihu_media.py")
    payload = json.dumps(
        {"initialState": {"entities": {"answers": {"100": {"content": "<p>正文</p><img src=\"a.jpg\">"}}}}}
    )
    doc = {"content_type": "answer", "content_id": "100"}
    assert module.extract_content_html(payload, doc) == "<p>正文</p><img src=\"a.jpg\">"
    assert module.extract_content_html("", doc) == ""
    assert module.extract_content_html("not json", doc) == ""
    # An article id must not be read out of the answers bucket.
    assert module.extract_content_html(payload, {"content_type": "article", "content_id": "100"}) == ""


def _zhihu_rows():
    return [
        # short controversy reply: high votes, no depth
        {"content_id": "1", "content_type": "answer", "title": "如何看待《测试游戏2》的争议？",
         "content_text": "不买了。", "voteup_count": 900, "content_url": "u1", "source_keyword": "测试游戏2"},
        # mechanism teardown: almost no votes, real depth
        {"content_id": "2", "content_type": "article", "title": "《测试游戏2》系统策划拆解",
         "content_text": "机制说明。" * 400, "voteup_count": 1, "content_url": "u2", "source_keyword": "测试游戏2"},
        # different game with a colliding name
        {"content_id": "3", "content_type": "answer", "title": "杀戮空间2 综合教学",
         "content_text": "测试游戏2 " * 50, "voteup_count": 500, "content_url": "u3", "source_keyword": "测试游戏2"},
        # passing mention only
        {"content_id": "4", "content_type": "answer", "title": "有哪些好玩的游戏？",
         "content_text": "比如测试游戏2。" + "别的内容。" * 100, "voteup_count": 5, "content_url": "u4",
         "source_keyword": "测试游戏2"},
    ]


def test_zhihu_selection_keeps_low_vote_long_form_and_drops_name_collision(tmp_path, monkeypatch):
    module = load_script("select_zhihu_candidates.py")
    input_path = tmp_path / "scan.jsonl"
    input_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in _zhihu_rows()),
        encoding="utf-8",
    )
    output = tmp_path / "selected"
    monkeypatch.setattr(sys, "argv", [
        "select_zhihu_candidates.py", "--input", str(input_path), "--output", str(output),
        "--match", r"测试游戏\s*2", "--exclude", "杀戮空间", "--min-votes", "100", "--min-chars", "2000",
    ])
    assert module.main() == 0

    selected = [json.loads(l) for l in (output / "contents.jsonl").read_text(encoding="utf-8").splitlines() if l]
    by_id = {row["content_id"]: row for row in selected}
    # the 1-upvote teardown must survive purely on length
    assert by_id["2"]["selection_tier"] == "long_form"
    # the short controversy reply still qualifies on votes
    assert by_id["1"]["selection_tier"] == "high_vote"
    # a different game sharing part of the name must not leak in
    assert "3" not in by_id
    # a passing mention is graded C and never selected
    assert "4" not in by_id
    assert (output / "selection-report.md").is_file()
    # only long-form entries feed the follow-up comment/media pass
    assert (output / "longform_urls.txt").read_text(encoding="utf-8").strip() == "u2"


def test_zhihu_selection_dedupes_across_keywords_keeping_longest_body(tmp_path, monkeypatch):
    module = load_script("select_zhihu_candidates.py")
    input_path = tmp_path / "scan.jsonl"
    rows = [
        {"content_id": "9", "content_type": "article", "title": "《测试游戏2》拆解",
         "content_text": "短版本。", "voteup_count": 500, "content_url": "u9", "source_keyword": "关键词甲"},
        {"content_id": "9", "content_type": "article", "title": "《测试游戏2》拆解",
         "content_text": "完整机制。" * 500, "voteup_count": 500, "content_url": "u9", "source_keyword": "关键词乙"},
    ]
    input_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    output = tmp_path / "selected"
    monkeypatch.setattr(sys, "argv", [
        "select_zhihu_candidates.py", "--input", str(input_path), "--output", str(output),
        "--match", r"测试游戏\s*2",
    ])
    assert module.main() == 0
    selected = [json.loads(l) for l in (output / "contents.jsonl").read_text(encoding="utf-8").splitlines() if l]
    assert len(selected) == 1
    assert selected[0]["content_text"].startswith("完整机制。")
    # sorted() orders by codepoint, so 乙 (U+4E59) precedes 甲 (U+7532)
    assert selected[0]["matched_keywords"] == ["关键词乙", "关键词甲"]
