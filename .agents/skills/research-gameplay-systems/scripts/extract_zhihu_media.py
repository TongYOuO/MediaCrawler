#!/usr/bin/env python3
"""Recover Zhihu inline images/GIFs/formulas that MediaCrawler's text extraction discards.

MediaCrawler stores `content_text` produced by `tools.crawler_util.extract_text_from_html`,
which strips every tag with a regex. Image URLs are therefore destroyed before anything is
written to disk, so an L0 text pack silently loses figures, damage tables, map diagrams and
animated demonstrations. This script re-fetches the source page with the saved Zhihu login
profile, keeps the raw content HTML, and anchors every visual asset back to the plain text so
it can be cited alongside `segments.jsonl`.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

DEFAULT_PROFILE = Path("browser_data") / "zhihu_user_data_dir"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

TAG_RE = re.compile(r"<(img|figcaption|figure)\b[^>]*>", re.IGNORECASE)
ATTR_RE = re.compile(r"""([\w:-]+)\s*=\s*("([^"]*)"|'([^']*)'|([^\s"'>]+))""")
SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL)
# Zhihu emits every figure twice: once inside <noscript> for crawlers, once lazy-loaded.
# Scanning both would double every asset, so the noscript copy is dropped. It holds no text,
# so removing it leaves plain-text offsets unchanged.
NOSCRIPT_RE = re.compile(r"<noscript\b[^>]*>.*?</noscript>", re.IGNORECASE | re.DOTALL)
ANY_TAG_RE = re.compile(r"<[^>]+>")
FIGCAPTION_RE = re.compile(r"<figcaption\b[^>]*>(.*?)</figcaption>", re.IGNORECASE | re.DOTALL)
# 1x1 spacers and inline placeholders carry no research value.
PLACEHOLDER_RE = re.compile(r"^data:|/equation\?|v2-[0-9a-f]+_(?:xs|is)\.", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从知乎原文恢复正文配图/动图/公式，并锚定到 L0 段落。"
    )
    parser.add_argument("--input", action="append", required=True, help="含 content_url 的 JSONL；可重复。")
    parser.add_argument("--output", required=True, help="输出目录；必须不存在。")
    parser.add_argument("--l0-dir", help="可选：L0 包目录，用于把资源映射到 segment_id。")
    parser.add_argument("--user-data-dir", default=str(DEFAULT_PROFILE), help="Playwright 持久化 Profile。")
    parser.add_argument("--sleep", type=float, default=2.0, help="每页间隔秒数，默认 2。")
    parser.add_argument("--timeout", type=float, default=30.0, help="单页导航超时秒数，默认 30。")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 条，0 表示全部。")
    parser.add_argument("--no-download", action="store_true", help="只登记资源 URL，不下载字节。")
    parser.add_argument("--headless", action="store_true", help="无头运行；登录态失效时不便人工处理。")
    return parser.parse_args()


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    # NOTE: iterate the handle. str.splitlines() also breaks on U+2028/U+0085, which appear
    # inside Zhihu bodies and would split a JSON record in half.
    with path.open(encoding="utf-8-sig") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def expand_inputs(values: list[str]) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        candidate = Path(value).expanduser()
        matches = sorted(candidate.rglob("*.jsonl")) if candidate.is_dir() else [candidate]
        for match in matches:
            resolved = match.resolve()
            if resolved not in paths:
                paths.append(resolved)
    return paths


def plain_text(html: str) -> str:
    """Reproduce tools.crawler_util.extract_text_from_html so offsets line up with content_text."""
    return ANY_TAG_RE.sub("", SCRIPT_STYLE_RE.sub("", html)).strip()


def attributes(tag: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for match in ATTR_RE.finditer(tag):
        name = match.group(1).lower()
        out[name] = match.group(3) or match.group(4) or match.group(5) or ""
    return out


def best_source(attrs: dict[str, str]) -> str:
    """Zhihu puts the full-resolution asset in data-original; src is often a blurred thumbnail."""
    for key in ("data-original", "data-actualsrc", "data-default-watermark-src", "src"):
        value = (attrs.get(key) or "").strip()
        if value and not value.startswith("data:"):
            return value
    return ""


def asset_kind(attrs: dict[str, str], url: str) -> str:
    if attrs.get("eeimg") or attrs.get("data-formula") or attrs.get("data-tex"):
        return "formula"
    if "class" in attrs and "ztext-gif" in attrs["class"]:
        return "gif"
    if url.lower().split("?")[0].endswith(".gif"):
        return "gif"
    if "class" in attrs and "video-poster" in attrs["class"]:
        return "video_poster"
    return "image"


def is_animated_gif(blob: bytes) -> bool:
    if not blob.startswith(b"GIF8"):
        return False
    # More than one Graphic Control Extension block means more than one frame.
    return blob.count(b"\x21\xf9\x04") > 1


def extension_for(url: str, blob: bytes | None) -> str:
    if blob:
        if blob.startswith(b"GIF8"):
            return ".gif"
        if blob.startswith(b"\x89PNG"):
            return ".png"
        if blob.startswith(b"\xff\xd8"):
            return ".jpg"
        if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
            return ".webp"
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"} else ".bin"


def collect_assets(content_html: str) -> list[dict[str, Any]]:
    """Find every visual asset and record where it sits inside the plain text."""
    content_html = NOSCRIPT_RE.sub("", content_html)
    captions = {m.start(): re.sub(r"<[^>]+>", "", m.group(1)).strip() for m in FIGCAPTION_RE.finditer(content_html)}
    assets: list[dict[str, Any]] = []
    order = 0
    for match in TAG_RE.finditer(content_html):
        if match.group(1).lower() != "img":
            continue
        attrs = attributes(match.group(0))
        url = best_source(attrs)
        kind = asset_kind(attrs, url)
        formula = attrs.get("data-formula") or attrs.get("data-tex") or ""
        if kind != "formula" and (not url or PLACEHOLDER_RE.match(url)):
            continue
        order += 1
        # Offset of this tag inside the stripped text == length of stripped text before it.
        before = plain_text(content_html[: match.start()])
        nearest_caption = ""
        for pos, text in captions.items():
            if 0 <= pos - match.end() < 400:
                nearest_caption = text
                break
        assets.append(
            {
                "asset_order": order,
                "asset_kind": kind,
                "source_url": url,
                "formula_tex": formula,
                "alt": attrs.get("alt", ""),
                "caption": nearest_caption,
                "declared_width": attrs.get("data-rawwidth", ""),
                "declared_height": attrs.get("data-rawheight", ""),
                "text_offset": len(before),
                "preceding_text": before[-160:],
            }
        )
    return assets


def load_segments(l0_dir: Path | None) -> dict[str, list[dict[str, Any]]]:
    if not l0_dir:
        return {}
    path = l0_dir / "segments.jsonl"
    if not path.is_file():
        raise SystemExit(f"找不到 L0 段落文件：{path}")
    by_doc: dict[str, list[dict[str, Any]]] = {}
    for row in read_jsonl(path):
        by_doc.setdefault(row["document_id"], []).append(row)
    return by_doc


def locate_segment(segments: list[dict[str, Any]], asset: dict[str, Any]) -> str:
    """Anchor by text match first; the raw offset is only a fallback because build_zhihu_l0
    normalizes whitespace and shifts positions by a few characters."""
    tail = asset["preceding_text"][-40:].strip()
    if tail:
        for seg in segments:
            if tail in seg["text"]:
                return seg["segment_id"]
    offset = asset["text_offset"]
    for seg in segments:
        if seg["char_start"] <= offset < seg["char_end"]:
            return seg["segment_id"]
    return ""


async def fetch_pages(docs: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, str]:
    """Load each answer/article page with the saved login profile and return its content HTML."""
    from playwright.async_api import async_playwright

    html_by_doc: dict[str, str] = {}
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(Path(args.user_data_dir).resolve()),
            headless=args.headless,
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 900},
        )
        try:
            page = await context.new_page()
            for index, doc in enumerate(docs, start=1):
                url = doc["content_url"]
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=args.timeout * 1000)
                    raw = await page.evaluate(
                        "() => { const n = document.getElementById('js-initialData');"
                        " return n ? n.textContent : ''; }"
                    )
                except Exception as error:  # noqa: BLE001 - report and continue to the next page
                    print(f"  [{index}/{len(docs)}] 页面失败 {doc['document_id']}: {error}")
                    continue
                content_html = extract_content_html(raw, doc)
                if content_html:
                    html_by_doc[doc["document_id"]] = content_html
                    print(f"  [{index}/{len(docs)}] {doc['document_id']} 正文 HTML {len(content_html)} 字节")
                else:
                    print(f"  [{index}/{len(docs)}] {doc['document_id']} 未取到正文 HTML")
                await asyncio.sleep(args.sleep)
        finally:
            await context.close()
    return html_by_doc


def extract_content_html(raw_init_data: str, doc: dict[str, Any]) -> str:
    """Pull entities.answers|articles[id].content out of the page's js-initialData blob."""
    if not raw_init_data:
        return ""
    try:
        data = json.loads(raw_init_data)
    except json.JSONDecodeError:
        return ""
    entities = data.get("initialState", {}).get("entities", {})
    bucket = {"answer": "answers", "article": "articles"}.get(doc["content_type"], "")
    records = entities.get(bucket, {}) if bucket else {}
    if not records:
        return ""
    record = records.get(doc["content_id"]) or records[list(records.keys())[0]]
    return record.get("content", "") or ""


def download(url: str, referer: str) -> bytes | None:
    import httpx

    try:
        response = httpx.get(
            url if url.startswith("http") else f"https:{url}",
            headers={"User-Agent": USER_AGENT, "Referer": referer},
            timeout=30.0,
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.content
    except Exception as error:  # noqa: BLE001 - a missing figure must not abort the pack
        print(f"    下载失败 {url}: {error}")
        return None


def main() -> int:
    args = parse_args()
    output = Path(args.output).expanduser().resolve()
    if output.exists():
        raise SystemExit(f"拒绝覆盖已有目录：{output}")

    inputs = expand_inputs(args.input)
    if not inputs:
        raise SystemExit("输入路径没有匹配任何 JSONL。")

    docs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in inputs:
        for item in read_jsonl(path):
            content_type = str(item.get("content_type") or "")
            content_id = str(item.get("content_id") or "")
            url = str(item.get("content_url") or "")
            if content_type not in {"answer", "article"} or not content_id or not url:
                continue
            document_id = f"ZH-{content_type}-{content_id}"
            if document_id in seen:
                continue
            seen.add(document_id)
            docs.append(
                {
                    "document_id": document_id,
                    "content_id": content_id,
                    "content_type": content_type,
                    "content_url": url,
                    "title": item.get("title", ""),
                }
            )
    if args.limit:
        docs = docs[: args.limit]
    if not docs:
        raise SystemExit("没有可处理的知乎回答/文章记录。")

    print(f"待处理 {len(docs)} 篇，Profile={args.user_data_dir}")
    html_by_doc = asyncio.run(fetch_pages(docs, args))

    segments_by_doc = load_segments(Path(args.l0_dir).expanduser().resolve() if args.l0_dir else None)

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}.partial-", dir=output.parent) as staging_name:
        staging = Path(staging_name)
        html_dir = staging / "html-private"
        assets_dir = staging / "assets"
        html_dir.mkdir()
        assets_dir.mkdir()

        rows: list[dict[str, Any]] = []
        no_html: list[str] = []
        for doc in docs:
            content_html = html_by_doc.get(doc["document_id"], "")
            if not content_html:
                no_html.append(doc["document_id"])
                continue
            (html_dir / f"{doc['document_id']}.html").write_text(content_html, encoding="utf-8")
            doc_assets = collect_assets(content_html)
            if not doc_assets:
                continue
            target = assets_dir / doc["document_id"]
            by_digest: dict[str, str] = {}
            for asset in doc_assets:
                asset["document_id"] = doc["document_id"]
                asset["content_url"] = doc["content_url"]
                asset["title"] = doc["title"]
                asset["segment_id"] = locate_segment(segments_by_doc.get(doc["document_id"], []), asset)
                asset["asset_id"] = f"{doc['document_id']}-M{asset['asset_order']:03d}"
                asset["local_path"] = ""
                asset["sha256"] = ""
                asset["bytes"] = 0
                asset["animated"] = False
                asset["duplicate_of_sha256"] = False
                if asset["asset_kind"] == "formula" or args.no_download or not asset["source_url"]:
                    rows.append(asset)
                    continue
                blob = download(asset["source_url"], doc["content_url"])
                if blob is None:
                    rows.append(asset)
                    continue
                digest = hashlib.sha256(blob).hexdigest()
                asset["sha256"] = digest
                asset["bytes"] = len(blob)
                asset["animated"] = is_animated_gif(blob)
                # The same figure can legitimately repeat inside one answer; store the bytes once
                # and let both occurrences point at it, so each keeps its own text anchor.
                if digest in by_digest:
                    asset["local_path"] = by_digest[digest]
                    asset["duplicate_of_sha256"] = True
                else:
                    target.mkdir(parents=True, exist_ok=True)
                    name = f"{asset['asset_order']:03d}-{digest[:8]}{extension_for(asset['source_url'], blob)}"
                    (target / name).write_bytes(blob)
                    asset["local_path"] = f"assets/{doc['document_id']}/{name}"
                    by_digest[digest] = asset["local_path"]
                if asset["animated"]:
                    asset["asset_kind"] = "gif"
                rows.append(asset)
            print(f"  {doc['document_id']}: 资源 {len(doc_assets)} 个")

        with (staging / "media.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

        downloaded = [r for r in rows if r["local_path"]]
        stored = [r for r in downloaded if not r["duplicate_of_sha256"]]
        (staging / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "evidence_level": "L0-media",
                    "platform": "zhihu",
                    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "documents_requested": len(docs),
                    "documents_with_html": len(html_by_doc),
                    "documents_without_html": no_html,
                    "asset_count": len(rows),
                    "downloaded_count": len(downloaded),
                    "stored_file_count": len(stored),
                    "stored_bytes": sum(r["bytes"] for r in stored),
                    "animated_count": len([r for r in rows if r["animated"]]),
                    "formula_count": len([r for r in rows if r["asset_kind"] == "formula"]),
                    "segment_anchored": len([r for r in rows if r["segment_id"]]),
                    "locator": "media.jsonl#asset_id -> segment_id",
                    "copyright_policy": "Local evidence only; commit locators and manifests, not platform images.",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        staging.replace(output)

    stored_bytes = sum(r["bytes"] for r in rows if r["local_path"] and not r["duplicate_of_sha256"])
    print(f"\n资源 {len(rows)} 个，落盘文件 {len([r for r in rows if r['local_path'] and not r['duplicate_of_sha256']])} 个，"
          f"{stored_bytes / 1024 / 1024:.1f} MB")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
