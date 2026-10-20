#!/usr/bin/env python3
"""Publish one day's limit-up timeline HTML into the static site."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from zoom_inject import ensure_zoom

ROOT = Path(__file__).resolve().parents[1]
DAYS = ROOT / "days"
DATA = ROOT / "data" / "index.json"
INDEX = ROOT / "index.html"


def load_index() -> list[dict]:
    if DATA.exists():
        return json.loads(DATA.read_text(encoding="utf-8"))
    return []


def save_index(items: list[dict]) -> None:
    DATA.parent.mkdir(parents=True, exist_ok=True)
    items = sorted(items, key=lambda x: x["date"], reverse=True)
    DATA.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def card_html(item: dict) -> str:
    return (
        f'    <a class="card" href="{item["path"]}">\n'
        f'      <div class="date">{item["date"]}</div>\n'
        f'      <div class="summary">{item["summary"]}</div>\n'
        f'      <div class="meta">打开当日复盘 →</div>\n'
        f"    </a>"
    )


def rewrite_index(items: list[dict]) -> None:
    html = INDEX.read_text(encoding="utf-8")
    block = "\n".join(card_html(i) for i in items) + "\n"
    new_html, n = re.subn(
        r"<!-- DAYS_START -->.*?<!-- DAYS_END -->",
        "<!-- DAYS_START -->\n" + block + "<!-- DAYS_END -->",
        html,
        count=1,
        flags=re.S,
    )
    if n != 1:
        raise SystemExit("index.html missing DAYS_START/DAYS_END markers")
    INDEX.write_text(new_html, encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--html", required=True, help="source HTML path")
    p.add_argument("--summary", required=True, help="one-line summary")
    p.add_argument("--title", default="", help="optional title")
    args = p.parse_args()

    src = Path(args.html)
    if not src.is_file():
        raise SystemExit(f"missing html: {src}")

    DAYS.mkdir(parents=True, exist_ok=True)
    dest = DAYS / f"{args.date}.html"
    dest.write_text(ensure_zoom(src.read_text(encoding="utf-8")), encoding="utf-8")

    items = [i for i in load_index() if i.get("date") != args.date]
    items.append(
        {
            "date": args.date,
            "title": args.title or f"{args.date} 涨停时间轴复盘",
            "summary": args.summary,
            "path": f"days/{args.date}.html",
        }
    )
    save_index(items)
    rewrite_index(items)
    print(f"published {dest}")
    print(f"index entries: {len(items)}")


if __name__ == "__main__":
    main()
