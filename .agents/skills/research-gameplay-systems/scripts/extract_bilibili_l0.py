#!/usr/bin/env python3
"""Build a local, timestamped L0 evidence pack from one public Bilibili video.

The script prefers creator/platform subtitles. When none exist, ``--asr`` downloads
the lowest practical public stream and runs local faster-whisper. Full transcripts
stay local and should not be committed without permission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sysconfig
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


API_ROOT = "https://api.bilibili.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)
_DLL_DIRECTORY_HANDLES: list[Any] = []


@dataclass(frozen=True)
class Segment:
    segment_id: str
    start_sec: float
    end_sec: float
    text: str
    transcript_source: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="提取 B站完整字幕或本地 ASR，生成带时间戳的 L0 证据包。"
    )
    parser.add_argument("--video", required=True, help="BV 号、av/aid 或完整视频 URL。")
    parser.add_argument("--output", required=True, help="输出目录；必须不存在。")
    parser.add_argument("--page", type=int, default=1, help="分 P 序号，默认 1。")
    parser.add_argument("--asr", action="store_true", help="没有官方字幕时运行本地 ASR。")
    parser.add_argument(
        "--asr-model",
        default="small",
        help="faster-whisper 模型，默认 small；关键短片可在已验证 GPU 上升级。",
    )
    parser.add_argument(
        "--language",
        default="auto",
        help="ASR 语言代码（如 zh/en）；默认 auto 自动检测，避免强制错误语言产生幻听。",
    )
    parser.add_argument("--beam-size", type=int, default=5, help="ASR beam size，默认 5；快速初筛可用 1。")
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    parser.add_argument(
        "--allow-large-cpu",
        action="store_true",
        help="允许 large-v3 在 CPU 上运行；可能持续数小时，默认拒绝。",
    )
    parser.add_argument("--keep-media", action="store_true", help="保留下载的视频与 WAV。")
    parser.add_argument(
        "--max-media-mb",
        type=int,
        default=600,
        help="媒体下载硬上限，默认 600 MB。",
    )
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def repair_mojibake(value: Any) -> str:
    """Repair common UTF-8/GBK bytes decoded as Latin-1, without changing good text."""
    text = str(value or "")
    candidates = [text]
    raw = bytearray()
    for char in text:
        for byte_codec in ("latin-1", "cp1252"):
            try:
                encoded = char.encode(byte_codec)
            except UnicodeEncodeError:
                continue
            if len(encoded) == 1:
                raw.extend(encoded)
                break
        else:
            raw.clear()
            break
    if raw:
        for encoding in ("utf-8", "gb18030"):
            try:
                candidates.append(bytes(raw).decode(encoding))
            except UnicodeDecodeError:
                pass

    def score(candidate: str) -> tuple[int, int]:
        cjk = sum("\u3400" <= char <= "\u9fff" for char in candidate)
        mojibake = sum(char in "ãåæçèéêëìíîïðñòóôõö÷øùúûüýþÿ´¼½¾" for char in candidate)
        return cjk * 4 - mojibake * 2, -candidate.count("�")

    return max(candidates, key=score)


def request_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Referer": "https://www.bilibili.com/"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("code") not in (None, 0):
        raise RuntimeError(f"Bilibili API error {payload.get('code')}: {payload.get('message')}")
    return payload


def parse_video_key(value: str) -> tuple[str, str]:
    bv_match = re.search(r"BV[0-9A-Za-z]+", value, flags=re.IGNORECASE)
    if bv_match:
        return "bvid", "BV" + bv_match.group(0)[2:]
    av_match = re.search(r"(?:av)?(\d+)", value, flags=re.IGNORECASE)
    if av_match:
        return "aid", av_match.group(1)
    raise ValueError(f"无法从输入识别 BV/aid：{value}")


def fetch_view(video: str, page_number: int) -> tuple[dict[str, Any], dict[str, Any]]:
    key, value = parse_video_key(video)
    payload = request_json(f"{API_ROOT}/x/web-interface/view", {key: value})
    data = payload.get("data") or {}
    pages = data.get("pages") or []
    if not pages:
        pages = [{"cid": data.get("cid"), "page": 1, "part": data.get("title", "")}]
    if page_number < 1 or page_number > len(pages):
        raise ValueError(f"分 P 超出范围：{page_number}，视频共 {len(pages)} P")
    return data, pages[page_number - 1]


def choose_subtitle(subtitles: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not subtitles:
        return None
    language_priority = ("zh-Hans", "zh-CN", "ai-zh", "zh-Hant", "zh-TW", "zh")
    for language in language_priority:
        for subtitle in subtitles:
            if str(subtitle.get("lan", "")).lower() == language.lower():
                return subtitle
    return subtitles[0]


def official_subtitle_segments(
    aid: int, bvid: str, cid: int
) -> tuple[list[Segment], dict[str, Any]]:
    payload = request_json(
        f"{API_ROOT}/x/player/v2",
        {"aid": aid, "bvid": bvid, "cid": cid},
    )
    subtitle_info = (payload.get("data") or {}).get("subtitle") or {}
    selected = choose_subtitle(subtitle_info.get("subtitles") or [])
    if not selected:
        return [], {"available": False, "tracks": 0}
    subtitle_url = str(selected.get("subtitle_url") or "")
    if subtitle_url.startswith("//"):
        subtitle_url = "https:" + subtitle_url
    body_payload = request_json(subtitle_url)
    segments = []
    for index, item in enumerate(body_payload.get("body") or [], start=1):
        text = " ".join(repair_mojibake(item.get("content")).split())
        if not text:
            continue
        segments.append(
            Segment(
                segment_id=f"S-{index:05d}",
                start_sec=float(item.get("from") or 0),
                end_sec=float(item.get("to") or item.get("from") or 0),
                text=text,
                transcript_source="official_subtitle",
            )
        )
    return segments, {
        "available": bool(segments),
        "tracks": len(subtitle_info.get("subtitles") or []),
        "selected_language": selected.get("lan"),
        "selected_language_label": selected.get("lan_doc"),
    }


def choose_play_url(aid: int, bvid: str, cid: int) -> str:
    payload = request_json(
        f"{API_ROOT}/x/player/playurl",
        {"avid": aid, "bvid": bvid, "cid": cid, "qn": 16, "fnval": 0, "platform": "pc"},
    )
    durl = (payload.get("data") or {}).get("durl") or []
    if not durl:
        raise RuntimeError("公开 playurl 未返回可下载媒体；可能需要登录态或视频受限。")
    if len(durl) != 1:
        raise RuntimeError(
            f"公开 playurl 返回 {len(durl)} 个媒体分段；当前脚本拒绝只转写其中一段，"
            "请先完整合并分段后再生成 L0。"
        )
    return str(durl[0].get("url") or "")


def download_media(url: str, destination: Path, max_bytes: int, attempts: int = 3) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Referer": "https://www.bilibili.com/"},
    )
    for attempt in range(1, attempts + 1):
        try:
            downloaded = 0
            with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
                declared = int(response.headers.get("Content-Length") or 0)
                if declared and declared > max_bytes:
                    raise RuntimeError(f"媒体大小 {declared} 字节，超过上限 {max_bytes} 字节。")
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    downloaded += len(block)
                    if downloaded > max_bytes:
                        raise RuntimeError(f"媒体下载超过上限 {max_bytes} 字节，已停止。")
                    output.write(block)
            return
        except (TimeoutError, urllib.error.URLError):
            destination.unlink(missing_ok=True)
            if attempt >= attempts:
                raise
            time.sleep(2 ** (attempt - 1))


def extract_audio(media_path: Path, audio_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("找不到 ffmpeg；无法进行 ASR。")
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(media_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(audio_path),
        ],
        check=True,
    )


def probe_media_duration(media_path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("找不到 ffprobe；无法验证媒体是否完整。")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return float(result.stdout.strip())


def resolve_device(requested: str) -> tuple[str, str]:
    if requested == "cpu":
        return "cpu", "int8"
    if requested == "cuda":
        return "cuda", "float16"
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except ImportError:
        pass
    return "cpu", "int8"


def configure_windows_cuda_dlls() -> list[str]:
    """Expose pip-installed NVIDIA DLLs to CTranslate2 on Windows."""
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return []
    purelib = Path(sysconfig.get_paths()["purelib"])
    nvidia_root = purelib / "nvidia"
    if not nvidia_root.is_dir():
        return []
    configured = []
    for bin_dir in sorted(nvidia_root.glob("*/bin")):
        if not any(bin_dir.glob("*.dll")):
            continue
        _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(bin_dir)))
        configured.append(str(bin_dir))
    return configured


def transcribe_with_device(
    audio_path: Path,
    model_name: str,
    language: str,
    device: str,
    compute_type: str,
    beam_size: int,
) -> tuple[list[Segment], Any]:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    generated, info = model.transcribe(
        str(audio_path),
        language=None if language.lower() == "auto" else language,
        beam_size=beam_size,
        vad_filter=True,
        condition_on_previous_text=True,
    )
    segments = []
    for index, item in enumerate(generated, start=1):
        text = " ".join(repair_mojibake(item.text).split())
        if not text:
            continue
        segments.append(
            Segment(
                segment_id=f"S-{index:05d}",
                start_sec=round(float(item.start), 3),
                end_sec=round(float(item.end), 3),
                text=text,
                transcript_source=f"asr:{model_name}",
            )
        )
    return segments, info


def transcribe_audio(
    audio_path: Path,
    model_name: str,
    language: str,
    requested_device: str,
    beam_size: int,
    allow_large_cpu: bool = False,
) -> tuple[list[Segment], dict[str, Any]]:
    cuda_dll_dirs = configure_windows_cuda_dlls()
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("未安装 faster-whisper；请安装后重试，或只处理带官方字幕的视频。") from exc

    del WhisperModel

    device, compute_type = resolve_device(requested_device)
    if device == "cpu" and model_name.lower() == "large-v3" and not allow_large_cpu:
        raise RuntimeError(
            "large-v3 将在 CPU 上运行，默认拒绝可能持续数小时的任务；"
            "请改用 --asr-model small，或确认后显式传 --allow-large-cpu。"
        )
    fallback_reason = None
    try:
        segments, info = transcribe_with_device(
            audio_path, model_name, language, device, compute_type, beam_size
        )
    except RuntimeError as exc:
        if device != "cuda":
            raise
        if model_name.lower() == "large-v3" and not allow_large_cpu:
            raise RuntimeError(
                "CUDA 转写失败，而 large-v3 的 CPU 回退默认关闭；"
                "请修复 CUDA、改用 --asr-model small，或显式传 --allow-large-cpu。"
            ) from exc
        fallback_reason = f"CUDA unavailable at runtime; fell back to CPU: {exc}"
        device, compute_type = "cpu", "int8"
        segments, info = transcribe_with_device(
            audio_path, model_name, language, device, compute_type, beam_size
        )
    return segments, {
        "model": model_name,
        "device": device,
        "compute_type": compute_type,
        "beam_size": beam_size,
        "requested_language": language,
        "detected_language": getattr(info, "language", language),
        "language_probability": getattr(info, "language_probability", None),
        "windows_cuda_dll_dirs": cuda_dll_dirs,
        "device_fallback_reason": fallback_reason,
    }


def format_time(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_outputs(
    output: Path,
    view: dict[str, Any],
    page: dict[str, Any],
    segments: Iterable[Segment],
    transcript_meta: dict[str, Any],
    media_hash: str | None,
    media_duration_sec: float | None,
) -> None:
    segments = list(segments)
    bvid = str(view.get("bvid") or "")
    aid = int(view.get("aid") or 0)
    source_url = f"https://www.bilibili.com/video/{bvid}"
    owner = view.get("owner") or {}
    metadata = {
        "platform": "bilibili",
        "content_id": bvid,
        "aid": aid,
        "cid": page.get("cid"),
        "page": page.get("page", 1),
        "part": repair_mojibake(page.get("part", "")),
        "title": repair_mojibake(view.get("title", "")),
        "description": repair_mojibake(view.get("desc", "")),
        "duration_sec": page.get("duration") or view.get("duration"),
        "published_at": view.get("pubdate"),
        "source_url": source_url,
        "public_creator_name": repair_mojibake(owner.get("name", "")),
        "public_creator_profile_url": (
            f"https://space.bilibili.com/{owner.get('mid')}" if owner.get("mid") else ""
        ),
        "collected_at": utc_now(),
        "transcript": transcript_meta,
    }
    write_json(output / "metadata.json", metadata)

    with (output / "transcript.jsonl").open("w", encoding="utf-8") as handle:
        for segment in segments:
            item = asdict(segment)
            item.update({"platform": "bilibili", "content_id": bvid, "source_url": source_url})
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    lines = [f"# {metadata['title']}", "", f"来源：{source_url}", ""]
    for segment in segments:
        lines.append(f"[{format_time(segment.start_sec)}–{format_time(segment.end_sec)}] {segment.text}")
    (output / "transcript.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    transcript_hash = sha256_file(output / "transcript.jsonl")
    duration_sec = float(metadata.get("duration_sec") or 0)
    transcript_end_sec = max((segment.end_sec for segment in segments), default=0.0)
    write_json(
        output / "manifest.json",
        {
            "schema_version": 1,
            "evidence_level": "L0",
            "platform": "bilibili",
            "content_id": bvid,
            "source_url": source_url,
            "segment_count": len(segments),
            "duration_sec": duration_sec,
            "transcript_end_sec": transcript_end_sec,
            "tail_coverage_ratio": (
                round(min(transcript_end_sec / duration_sec, 1.0), 4) if duration_sec else None
            ),
            "transcript_sha256": transcript_hash,
            "source_media_sha256": media_hash,
            "source_media_duration_sec": media_duration_sec,
            "source_media_duration_ratio": (
                round(min(media_duration_sec / duration_sec, 1.0), 4)
                if media_duration_sec is not None and duration_sec
                else None
            ),
            "locator": "transcript.jsonl#segment_id",
            "copyright_policy": "Keep full transcript local; commit only short evidence slices and locators.",
        },
    )


def main() -> int:
    args = parse_args()
    output = Path(args.output).expanduser().resolve()
    if output.exists():
        raise SystemExit(f"拒绝覆盖已有目录：{output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}.partial-", dir=output.parent
    ) as staging_name:
        staging = Path(staging_name)
        view, page = fetch_view(args.video, args.page)
        aid = int(view.get("aid") or 0)
        bvid = str(view.get("bvid") or "")
        cid = int(page.get("cid") or 0)
        segments, transcript_meta = official_subtitle_segments(aid, bvid, cid)
        media_hash = None
        media_duration_sec = None

        if not segments:
            if not args.asr:
                raise SystemExit("该视频没有可用官方字幕；使用 --asr 生成本地转写。")
            with tempfile.TemporaryDirectory(prefix="bili-l0-") as temp_dir:
                temp_root = Path(temp_dir)
                media_path = temp_root / "source.mp4"
                audio_path = temp_root / "audio.wav"
                play_url = choose_play_url(aid, bvid, cid)
                download_media(play_url, media_path, args.max_media_mb * 1024 * 1024)
                media_duration_sec = probe_media_duration(media_path)
                expected_duration_sec = float(page.get("duration") or view.get("duration") or 0)
                if expected_duration_sec and media_duration_sec / expected_duration_sec < 0.9:
                    raise RuntimeError(
                        "下载媒体不完整："
                        f"{media_duration_sec:.1f}/{expected_duration_sec:.1f} 秒；拒绝生成部分 L0。"
                    )
                media_hash = sha256_file(media_path)
                extract_audio(media_path, audio_path)
                segments, asr_meta = transcribe_audio(
                    audio_path,
                    args.asr_model,
                    args.language,
                    args.device,
                    args.beam_size,
                    args.allow_large_cpu,
                )
                transcript_meta = {"available": bool(segments), "source": "asr", **asr_meta}
                if args.keep_media:
                    media_dir = staging / "media"
                    media_dir.mkdir()
                    shutil.copy2(media_path, media_dir / "source.mp4")
                    shutil.copy2(audio_path, media_dir / "audio.wav")

        if not segments:
            raise SystemExit("没有生成任何字幕片段。")
        write_outputs(
            staging,
            view,
            page,
            segments,
            transcript_meta,
            media_hash,
            media_duration_sec,
        )
        staging.replace(output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
