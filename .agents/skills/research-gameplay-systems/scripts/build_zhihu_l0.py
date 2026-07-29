#!/usr/bin/env python3
"""Normalize MediaCrawler Zhihu answer/article JSONL into local L0 evidence packs."""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="把知乎回答/文章全文整理为带段落定位和哈希的 L0 证据包。"
    )
    parser.add_argument("--input", action="append", required=True, help="MediaCrawler 知乎 contents JSONL；可重复。")
    parser.add_argument("--output", required=True, help="输出目录；必须不存在。")
    parser.add_argument("--min-chars", type=int, default=800, help="正文最低字符数，默认 800。")
    parser.add_argument("--segment-chars", type=int, default=1200, help="证据段最大字符数，默认 1200。")
    return parser.parse_args()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def normalized_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t\f\v]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def chunk_text(text: str, max_chars: int) -> Iterable[tuple[int, int, str]]:
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            search_floor = start + max_chars // 2
            split_at = max(text.rfind(mark, search_floor, end) for mark in "\n。！？!?；;")
            if split_at >= search_floor:
                end = split_at + 1
        raw_chunk = text[start:end]
        leading = len(raw_chunk) - len(raw_chunk.lstrip())
        trailing = len(raw_chunk) - len(raw_chunk.rstrip())
        chunk_start = start + leading
        chunk_end = end - trailing
        if chunk_start < chunk_end:
            yield chunk_start, chunk_end, text[chunk_start:chunk_end]
        start = end


def expand_input_paths(values: list[str]) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        candidate = Path(value).expanduser()
        if candidate.is_dir():
            matches = list(candidate.rglob("*.jsonl"))
        elif glob.has_magic(value):
            matches = [Path(item) for item in glob.glob(value, recursive=True)]
        else:
            matches = [candidate]
        for match in matches:
            resolved = match.resolve()
            if resolved not in paths:
                paths.append(resolved)
    return sorted(paths)


def iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    with path.open(encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.strip():
                yield line_number, json.loads(line)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    output = Path(args.output).expanduser().resolve()
    if output.exists():
        raise SystemExit(f"拒绝覆盖已有目录：{output}")
    inputs = expand_input_paths(args.input)
    if not inputs:
        raise SystemExit("输入路径或通配符没有匹配任何 JSONL。")
    for path in inputs:
        if not path.is_file():
            raise SystemExit(f"找不到输入：{path}")

    output.parent.mkdir(parents=True, exist_ok=True)

    documents: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for input_path in inputs:
        for line_number, item in iter_jsonl(input_path):
            content_type = str(item.get("content_type") or "")
            content_id = str(item.get("content_id") or "")
            key = (content_type, content_id)
            if not content_id or key in seen:
                continue
            seen.add(key)
            text = normalized_text(str(item.get("content_text") or ""))
            if content_type not in {"answer", "article"} or len(text) < args.min_chars:
                skipped.append(
                    {
                        "content_type": content_type,
                        "content_id": content_id,
                        "text_chars": len(text),
                        "reason": "not_answer_or_article" if content_type not in {"answer", "article"} else "summary_or_short_body",
                        "raw_locator": f"{input_path}#L{line_number}",
                    }
                )
                continue

            document_id = f"ZH-{content_type}-{content_id}"
            source_url = str(item.get("content_url") or "")
            content_hash = sha256_bytes(text.encode("utf-8"))
            document = {
                "document_id": document_id,
                "platform": "zhihu",
                "content_id": content_id,
                "content_type": content_type,
                "title": item.get("title", ""),
                "source_url": source_url,
                "published_at": item.get("created_time", 0),
                "updated_at": item.get("updated_time", 0),
                "voteup_count": item.get("voteup_count", 0),
                "comment_count": item.get("comment_count", 0),
                "creator_attribution": item.get("user_nickname", ""),
                "creator_identity_status": "masked_by_crawler; verify manually from public source",
                "text_chars": len(text),
                "content_sha256": content_hash,
                "raw_locator": f"{input_path}#L{line_number}",
                "body": text,
            }
            documents.append(document)
            for index, (start, end, chunk) in enumerate(
                chunk_text(text, args.segment_chars), start=1
            ):
                segments.append(
                    {
                        "segment_id": f"{document_id}-P{index:04d}",
                        "document_id": document_id,
                        "platform": "zhihu",
                        "content_id": content_id,
                        "source_url": source_url,
                        "char_start": start,
                        "char_end": end,
                        "text": chunk,
                        "content_sha256": content_hash,
                    }
                )

    if not documents:
        raise SystemExit("没有符合要求的知乎全文；搜索摘要不能作为 L0。")
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}.partial-", dir=output.parent
    ) as staging_name:
        staging = Path(staging_name)
        with (staging / "documents.jsonl").open("w", encoding="utf-8") as handle:
            for item in documents:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        with (staging / "segments.jsonl").open("w", encoding="utf-8") as handle:
            for item in segments:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        with (staging / "review_queue.csv").open(
            "w", encoding="utf-8-sig", newline=""
        ) as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "deep_source_id", "document_id", "title", "source_url", "text_chars",
                    "published_at", "updated_at", "raw_locator", "content_sha256",
                    "question_match_0_3", "argument_completeness_0_3",
                    "primary_evidence_0_3", "author_basis_0_3", "version_clarity_0_3",
                    "self_check_0_3", "total_0_18", "source_role",
                    "independence_group", "decision", "notes",
                ]
            )
            for index, item in enumerate(documents, start=1):
                writer.writerow(
                    [
                        f"DS-ZH-{index:03d}", item["document_id"], item["title"],
                        item["source_url"], item["text_chars"], item["published_at"],
                        item["updated_at"], item["raw_locator"], item["content_sha256"],
                        "", "", "", "", "", "", "", "", "", "review", "",
                    ]
                )

        write_json(
            staging / "manifest.json",
            {
                "schema_version": 1,
                "evidence_level": "L0",
                "platform": "zhihu",
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "inputs": [
                    {"path": str(path), "sha256": sha256_file(path)} for path in inputs
                ],
                "document_count": len(documents),
                "segment_count": len(segments),
                "review_queue": "review_queue.csv",
                "skipped": skipped,
                "locator": "segments.jsonl#segment_id",
                "copyright_policy": "Keep full documents local; commit only short evidence slices and locators.",
            },
        )
        staging.replace(output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
