#!/usr/bin/env python3
"""Create a non-destructive gameplay research case directory."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path


PLATFORMS = (
    "xhs",
    "douyin",
    "kuaishou",
    "bili",
    "weibo",
    "tieba",
    "zhihu",
    "heybox",
    "official",
    "gdc",
    "playtest",
)


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", value.strip())
    slug = re.sub(r"-+", "-", slug).strip("-_")
    if not slug:
        raise ValueError("无法从游戏名生成有效目录名，请显式提供 --slug。")
    return slug.lower()


def write_csv(path: Path, headers: list[str], rows: list[list[str]] | None = None) -> None:
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows or [])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="初始化两阶段游戏系统与核心玩法调研案例。")
    parser.add_argument("--game", required=True, help="游戏名称。")
    parser.add_argument("--version", default="待确认", help="版本、赛季或补丁号。")
    parser.add_argument("--platform", default="待确认", help="研究涉及的游戏平台。")
    parser.add_argument("--output", default="research-cases", help="案例根目录。")
    parser.add_argument("--slug", help="案例目录名；默认由游戏名生成。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    case_slug = safe_slug(args.slug or args.game)
    case_dir = Path(args.output).expanduser().resolve() / case_slug

    if case_dir.exists():
        print(f"拒绝覆盖已有目录：{case_dir}", file=sys.stderr)
        return 2

    skill_dir = Path(__file__).resolve().parent.parent
    template_path = skill_dir / "assets" / "gameplay-research-template.md"
    if not template_path.is_file():
        print(f"找不到模板：{template_path}", file=sys.stderr)
        return 3

    case_dir.mkdir(parents=True)
    for platform in PLATFORMS:
        (case_dir / "raw" / platform).mkdir(parents=True)
    (case_dir / "l0-private" / "bili").mkdir(parents=True)
    (case_dir / "l0-private" / "zhihu").mkdir()
    (case_dir / "evidence-slices").mkdir()
    (case_dir / "media-notes").mkdir()
    (case_dir / "analysis").mkdir()

    rendered = (
        template_path.read_text(encoding="utf-8")
        .replace("{{GAME_NAME}}", args.game)
        .replace("{{GAME_VERSION}}", args.version)
        .replace("{{GAME_PLATFORM}}", args.platform)
        .replace("{{RESEARCH_DATE}}", date.today().isoformat())
    )
    (case_dir / "research.md").write_text(rendered, encoding="utf-8")

    write_csv(
        case_dir / "source-register.csv",
        [
            "source_id", "source_type", "platform", "title", "url_or_path",
            "published_at", "collected_at", "game_version", "purpose", "limitations",
        ],
    )
    write_csv(
        case_dir / "deep-source-register.csv",
        [
            "deep_source_id", "platform", "source_role", "title", "public_url",
            "author_public_basis", "game_version", "published_or_edited_at", "l0_locator",
            "content_sha256", "quality_score_0_18", "independence_group", "decision", "notes",
        ],
    )
    write_csv(
        case_dir / "l0-manifest.csv",
        [
            "l0_id", "platform", "content_type", "content_id", "public_url", "local_path",
            "locator_rule", "content_sha256", "duration_or_chars", "coverage_check", "status",
        ],
    )
    write_csv(
        case_dir / "evidence-ledger.csv",
        [
            "evidence_id", "evidence_level", "claim_or_observation", "evidence_type",
            "platform", "game_version", "conditions", "l0_locator", "verification_method",
            "verification_result", "support_scope", "alternative_explanation",
            "author_credibility", "evidence_strength", "confidence",
        ],
    )
    write_csv(
        case_dir / "keyword-matrix.csv",
        ["query_id", "platform", "game_term", "system_term", "intent_term", "version_term", "sort_mode", "time_window", "target_count"],
        [["Q-001", "", args.game, "核心玩法", "攻略", args.version, "热门/最新/中长尾", "", ""]],
    )
    write_csv(
        case_dir / "collection-log.csv",
        [
            "run_id", "platform", "query_id", "command_or_method", "started_at",
            "finished_at", "result_count", "raw_path", "status", "notes",
        ],
    )
    (case_dir / "case.json").write_text(
        json.dumps(
            {
                "game": args.game,
                "version": args.version,
                "platform": args.platform,
                "created_at": date.today().isoformat(),
                "status": "draft",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(case_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
