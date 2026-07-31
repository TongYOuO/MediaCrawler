#!/usr/bin/env python3
"""Grade Zhihu scan results by relevance and select a deep-reading pool.

Interaction counts alone are a poor sampling frame. On contested topics the high-vote slots fill
with short controversy replies while mechanism teardowns, source-code analyses and build guides sit
in the single digits. This script therefore selects on the union of an upvote threshold and a body
length threshold, and reports the vote-by-length cross tab so the operator can see which rule is
actually carrying the sample before committing to it.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="对知乎扫描结果做相关性分级与深读池筛选，并输出量级报告。"
    )
    parser.add_argument("--input", action="append", required=True, help="MediaCrawler 知乎 contents JSONL、目录或通配符；可重复。")
    parser.add_argument("--output", required=True, help="输出目录；已存在时拒绝运行。")
    parser.add_argument("--match", required=True, help="判定主题命中的正则，例如 '杀戮尖塔\\s*[2２二]|尖塔\\s*[2２]'。")
    parser.add_argument("--exclude", default="", help="排除同名噪音的正则，例如 '杀戮空间|Killing Floor'。")
    parser.add_argument("--min-votes", type=int, default=100, help="高赞门槛，默认 100。")
    parser.add_argument("--min-chars", type=int, default=2000, help="长文门槛，默认 2000。")
    parser.add_argument("--body-mentions", type=int, default=5, help="标题未命中时，正文命中多少次算 B 级，默认 5。")
    parser.add_argument("--report-only", action="store_true", help="只打印量级报告，不写输出目录。")
    return parser.parse_args()


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    # NOTE: iterate the handle. str.splitlines() also breaks on U+2028/U+0085, which appear inside
    # Zhihu bodies and would split a JSON record in half.
    with path.open(encoding="utf-8-sig") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def expand_inputs(values: list[str]) -> list[Path]:
    import glob as globlib

    paths: list[Path] = []
    for value in values:
        candidate = Path(value).expanduser()
        if candidate.is_dir():
            matches = sorted(candidate.rglob("*.jsonl"))
        elif globlib.has_magic(value):
            matches = [Path(p) for p in globlib.glob(value, recursive=True)]
        else:
            matches = [candidate]
        for match in matches:
            resolved = match.resolve()
            if resolved not in paths:
                paths.append(resolved)
    return paths


def dedupe(paths: list[Path]) -> list[dict[str, Any]]:
    """One record per content_id, keeping the longest body seen across keywords."""
    rows: dict[str, dict[str, Any]] = {}
    for path in paths:
        for item in read_jsonl(path):
            content_id = str(item.get("content_id") or "")
            if not content_id:
                continue
            previous = rows.get(content_id)
            keywords = previous["_keywords"] if previous else set()
            if previous is None or len(item.get("content_text") or "") > len(previous.get("content_text") or ""):
                item["_keywords"] = keywords
                rows[content_id] = item
            rows[content_id]["_keywords"].add(item.get("source_keyword", ""))
    return list(rows.values())


def grade_items(items: list[dict[str, Any]], args: argparse.Namespace) -> None:
    match_re = re.compile(args.match, re.IGNORECASE)
    exclude_re = re.compile(args.exclude, re.IGNORECASE) if args.exclude else None
    for item in items:
        title = item.get("title") or ""
        body = item.get("content_text") or ""
        item["_votes"] = int(item.get("voteup_count") or 0)
        item["_chars"] = len(body)
        if exclude_re and exclude_re.search(title):
            item["_grade"] = "X"
        elif match_re.search(title):
            item["_grade"] = "A"
        elif len(match_re.findall(body)) >= args.body_mentions:
            item["_grade"] = "B"
        elif match_re.search(body):
            item["_grade"] = "C"
        else:
            item["_grade"] = "X"


def cross_tab(pool: list[dict[str, Any]], min_chars: int) -> list[str]:
    vote_bands = [(0, 50), (50, 100), (100, 300), (300, 10**9)]
    char_bands = [(0, 800), (800, min_chars), (min_chars, 10**9)]
    lines = [f"{'':>12} {'<800字':>8} {f'800-{min_chars}':>10} {f'>={min_chars}':>9} {'合计':>6}"]
    for low, high in vote_bands:
        row = [i for i in pool if low <= i["_votes"] < high]
        cells = [len([i for i in row if c0 <= i["_chars"] < c1]) for c0, c1 in char_bands]
        label = f"赞{low}-{'∞' if high > 10**8 else high}"
        lines.append(f"{label:>12} {cells[0]:>8} {cells[1]:>10} {cells[2]:>9} {len(row):>6}")
    return lines


def published(value: Any) -> str:
    try:
        stamp = int(value)
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(stamp, timezone.utc).astimezone().strftime("%Y-%m-%d") if stamp > 0 else ""


def main() -> int:
    args = parse_args()
    output = Path(args.output).expanduser().resolve()
    if output.exists() and not args.report_only:
        raise SystemExit(f"拒绝覆盖已有目录：{output}")

    paths = expand_inputs(args.input)
    if not paths:
        raise SystemExit("输入路径没有匹配任何 JSONL。")

    items = dedupe(paths)
    grade_items(items, args)
    relevant = [i for i in items if i["_grade"] in ("A", "B")]

    selected: list[dict[str, Any]] = []
    for item in relevant:
        by_vote = item["_votes"] >= args.min_votes
        by_len = item["_grade"] == "A" and item["_chars"] >= args.min_chars
        if not (by_vote or by_len):
            continue
        item["_tier"] = "both" if by_vote and by_len else ("high_vote" if by_vote else "long_form")
        selected.append(item)
    selected.sort(key=lambda x: (x["_tier"] == "high_vote", -x["_chars"], -x["_votes"]))

    report: list[str] = [
        f"唯一内容 {len(items)} 条，来自 {len(paths)} 个 JSONL",
        f"相关性分级 {dict(Counter(i['_grade'] for i in items))}  (A=标题命中 B=正文命中>={args.body_mentions}次 C=顺带一提 X=无关)",
        "",
        f"A+B 池 (n={len(relevant)}) 赞数 × 字数：",
        *cross_tab(relevant, args.min_chars),
        "",
        f"入选 {len(selected)} 条 = 赞>={args.min_votes} 或 正文>={args.min_chars}字",
        f"  {dict(Counter(i['_tier'] for i in selected))}",
    ]
    only_by_length = [i for i in selected if i["_tier"] == "long_form"]
    if only_by_length:
        report.append(
            f"  其中 {len(only_by_length)} 条仅靠长度入选——单用赞数阈值会漏掉这些深度材料。"
        )
    print("\n".join(report))

    if args.report_only:
        return 0

    output.mkdir(parents=True, exist_ok=True)
    with (output / "contents.jsonl").open("w", encoding="utf-8") as handle:
        for item in selected:
            record = {k: v for k, v in item.items() if not k.startswith("_")}
            record["relevance_grade"] = item["_grade"]
            record["selection_tier"] = item["_tier"]
            record["matched_keywords"] = sorted(k for k in item["_keywords"] if k)
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    with (output / "index.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["序号", "入选依据", "点赞", "评论", "正文字数", "相关性", "类型", "发布日", "标题", "URL", "content_id", "命中关键词"])
        for number, item in enumerate(selected, start=1):
            writer.writerow([
                number, item["_tier"], item["_votes"], item.get("comment_count", 0), item["_chars"],
                item["_grade"], item.get("content_type", ""), published(item.get("created_time")),
                item.get("title", ""), item.get("content_url", ""), item.get("content_id", ""),
                " | ".join(sorted(k for k in item["_keywords"] if k)),
            ])

    (output / "longform_urls.txt").write_text(
        "".join(f"{i.get('content_url','')}\n" for i in selected if i["_chars"] >= args.min_chars and i.get("content_url")),
        encoding="utf-8",
    )
    (output / "selection-report.md").write_text(
        "# 知乎候选筛选报告\n\n生成时间："
        + datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        + "\n\n```text\n"
        + "\n".join(report)
        + "\n```\n",
        encoding="utf-8",
    )
    print(f"\n{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
