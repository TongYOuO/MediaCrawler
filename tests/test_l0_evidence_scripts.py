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
