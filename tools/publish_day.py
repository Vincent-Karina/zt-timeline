#!/usr/bin/env python3
"""Publish one day's limit-up timeline HTML into the static site."""
from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from zoom_inject import ensure_zoom

ROOT = Path(__file__).resolve().parents[1]
DAYS = ROOT / "days"
DATA = ROOT / "data" / "index.json"
INDEX = ROOT / "index.html"
WEEKDAYS = "一二三四五六日"


def load_index() -> list[dict]:
    if DATA.exists():
        return json.loads(DATA.read_text(encoding="utf-8"))
    return []


def save_index(items: list[dict]) -> None:
    DATA.parent.mkdir(parents=True, exist_ok=True)
    items = sorted(items, key=lambda x: x["date"], reverse=True)
    DATA.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_summary(summary: str) -> dict:
    zt = zb = weak = None
    m = re.search(r"(?:封板|涨停)\s*(\d+)", summary or "")
    if m:
        zt = m.group(1)
    m = re.search(r"炸板\s*(\d+)", summary or "")
    if m:
        zb = m.group(1)
    m = re.search(r"弱封单\s*(\d+)", summary or "")
    if m:
        weak = m.group(1)
    themes: list[str] = []
    m = re.search(r"(?:韭研列|芽研列)\s*[:：]\s*(.+)$", summary or "")
    if not m:
        m = re.search(r"(?:逻辑列复盘[（(][^：:]*[：:]|韭研[:：])(.+)$", summary or "")
    if m:
        raw = m.group(1).rstrip("）)")
        raw = re.sub(r"^\d{4}-\d{2}-\d{2}", "", raw).lstrip("：:，, ")
        themes = [t.strip() for t in re.split(r"[/、,，]", raw) if t.strip()]
        themes = [t for t in themes if t not in {"逻辑列复盘", "东财公开接口", "东财+同花顺公开接口"}]
    return {"zt": zt, "zb": zb, "weak": weak, "themes": themes}


def fmt_date(date_s: str) -> tuple[str, str, str]:
    d = datetime.strptime(date_s, "%Y-%m-%d")
    return f"{d.year}年{d.month}月{d.day}日", "周" + WEEKDAYS[d.weekday()], date_s


def card_html(item: dict, featured: bool = False) -> str:
    date_cn, wd, iso = fmt_date(item["date"])
    info = parse_summary(item.get("summary") or "")
    href = html_lib.escape(item["path"], quote=True)
    cls = "card featured" if featured else "card"
    kicker = '      <div class="kicker">最新交易日</div>\n' if featured else ""
    go = "打开复盘" if featured else "→"
    stats = ""
    if info["zt"] or info["zb"] or info["weak"]:
        def cell(kind: str, label: str, val: str | None) -> str:
            return (
                f'        <div class="stat {kind}"><b>{html_lib.escape(val or "—")}</b>'
                f"<span>{label}</span></div>\n"
            )
        stats = (
            '      <div class="stats">\n'
            + cell("zt", "封板", info["zt"])
            + cell("zb", "炸板", info["zb"])
            + cell("wk", "弱封单", info["weak"])
            + "      </div>\n"
        )
    themes = ""
    if info["themes"]:
        pills = "".join(
            f'        <span class="tag">{html_lib.escape(t)}</span>\n' for t in info["themes"]
        )
        themes = '      <div class="themes">\n' + pills + "      </div>\n"
    elif not stats:
        themes = f'      <div class="fallback">{html_lib.escape(item.get("summary") or "")}</div>\n'
    return (
        f'    <a class="{cls}" href="{href}">\n'
        f'      <div class="card-top">\n'
        f"        <div>\n"
        f"{kicker}"
        f'          <div class="date">{html_lib.escape(date_cn)} <span class="wd">{html_lib.escape(wd)}</span></div>\n'
        f'          <span class="iso">{html_lib.escape(iso)}</span>\n'
        f"        </div>\n"
        f'        <span class="go">{go}</span>\n'
        f"      </div>\n"
        f"{stats}{themes}"
        f"    </a>"
    )


def rewrite_index(items: list[dict]) -> None:
    page = INDEX.read_text(encoding="utf-8")
    parts: list[str] = []
    for i, item in enumerate(items):
        if i == 1:
            parts.append('    <div class="section">历史复盘</div>')
        parts.append(card_html(item, featured=(i == 0)))
    block = "\n".join(parts) + "\n"
    new_html, n = re.subn(
        r"<!-- DAYS_START -->.*?<!-- DAYS_END -->",
        "<!-- DAYS_START -->\n" + block + "<!-- DAYS_END -->",
        page,
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
    items = sorted(items, key=lambda x: x["date"], reverse=True)
    save_index(items)
    rewrite_index(items)
    print(f"published {dest}")
    print(f"index entries: {len(items)}")


if __name__ == "__main__":
    main()
