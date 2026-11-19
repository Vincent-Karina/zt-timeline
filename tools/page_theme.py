#!/usr/bin/env python3
"""Shared product chrome for the day review page (and reskin of older days)."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

HOME_URL = "https://vincent-karina.github.io/zt-timeline/"
WEEKDAYS = "一二三四五六日"
DISCLAIMER = (
    "数据来自同花顺封板池与东方财富公开接口；题材列参考韭研公社全天涨停简图。"
    "本页为复盘工具，不构成投资建议。"
)

DAY_CSS = """
:root{
  --bg:#050505;
  --panel:#111114;
  --panel-2:#18181c;
  --text:#f4f4f4;
  --muted:#9a9a9a;
  --line:#2c2c30;
  --gold:#ffd54f;
  --zt:#69f0ae;
  --zb:#ff9100;
  --wk:#ffd54f;
  --hf:#69f0ae;
  --xline:#00e5ff;
}
*{box-sizing:border-box}
html,body{
  margin:0;height:100%;background:var(--bg);color:var(--text);
  font:13px/1.45 "Segoe UI","PingFang SC","Hiragino Sans GB","Noto Sans SC",system-ui,sans-serif;
  -webkit-font-smoothing:antialiased;
}
.page{height:100vh;display:grid;grid-template-rows:auto 1fr auto;position:relative}
.head{
  padding:10px 18px 12px;
  background:linear-gradient(180deg,#16140f 0%,#111114 100%);
  border-bottom:1px solid var(--line);
  box-shadow:inset 0 2px 0 var(--gold);
}
.topbar{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px}
.brand{
  color:var(--gold);text-decoration:none;font-weight:750;letter-spacing:.12em;
  font-size:12px;display:inline-flex;align-items:center;gap:8px;
}
.brand i{
  display:inline-block;width:8px;height:8px;background:var(--gold);border-radius:2px;
  box-shadow:0 0 8px rgba(255,213,79,.7);
}
.top-meta{color:#888;font-size:12px}
.title-row{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;flex-wrap:wrap}
h1{margin:0;font-size:22px;font-weight:750;letter-spacing:.03em;color:#fff}
h1 .wd{margin-left:8px;font-size:14px;font-weight:600;color:#aaa}
.h-stats{display:flex;gap:8px}
.h-stat{
  min-width:76px;text-align:center;
  background:#0a0a0a;border:1px solid #2a2a2a;border-radius:10px;
  padding:7px 12px 6px;
}
.h-stat b{display:block;font-size:22px;font-variant-numeric:tabular-nums;font-weight:800;line-height:1.1}
.h-stat span{display:block;font-size:10px;letter-spacing:.12em;color:#999;margin-top:3px}
.h-stat.zt b{color:var(--zt)}
.h-stat.zb b{color:var(--zb)}
.h-stat.wk b{color:var(--wk)}
.sub{display:none}
.leg{display:flex;flex-wrap:wrap;gap:6px 12px;margin-top:10px;align-items:center}
.lg{display:inline-flex;align-items:center;gap:5px;font-size:11px;color:#eee;font-weight:600}
.lg i{width:10px;height:10px;border-radius:2px;border:1px solid rgba(255,255,255,.45);flex-shrink:0}
.leg-label{color:#777;font-size:11px;letter-spacing:.1em;margin-left:4px}
.key{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;font-size:11px;color:#aaa}
.key .k{
  display:inline-flex;align-items:center;gap:5px;
  border:1px solid #2a2a2a;border-radius:999px;padding:2px 9px;background:#0a0a0a;
}
.key b{font-weight:700;color:#eee}
.foot{
  padding:7px 18px;font-size:11px;color:#777;line-height:1.45;
  border-top:1px solid var(--line);background:#0c0c0c;
}
.wrap{overflow:auto;padding:10px 12px;min-height:0;position:relative;background:var(--bg);cursor:grab}
.wrap.is-panning{cursor:grabbing;user-select:none;-webkit-user-select:none}
.wrap.is-panning *{cursor:grabbing!important}
#stage{position:relative;display:inline-block;min-width:100%}
table{border-collapse:separate;border-spacing:0;width:max-content;min-width:100%;background:#111114;position:relative;z-index:1}
th,td{border:1px solid #2c2c30;padding:5px 6px;vertical-align:top}
th{
  background:#18181c;color:#fff;position:sticky;top:0;z-index:3;
  font-size:12px;min-width:128px;max-width:168px;border-bottom:1px solid #444;
  letter-spacing:.02em;
}
th .arr{display:block;font-weight:500;color:var(--gold);font-size:10px;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;opacity:.9}
td.tm{
  position:sticky;left:0;background:#121814;color:var(--zt);font-weight:800;
  z-index:2;white-space:nowrap;min-width:52px;border-right:2px solid #1b5e20;
  font-variant-numeric:tabular-nums;
}
.c{display:flex;align-items:center;gap:4px;width:100%;margin:0 0 5px;padding:6px 7px;border-radius:6px;border:2px solid #000;background:var(--bg);color:var(--fg);cursor:pointer;font:inherit;font-weight:700}
.c b{flex:1;text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:inherit}
.c i{font-style:normal;font-size:10px;background:#000;color:#ffd54f;padding:0 3px;border-radius:2px}
.c .plate{font-style:normal;font-size:10px;font-weight:900;padding:1px 4px;border-radius:3px;border:1px solid #fff;letter-spacing:.02em;flex-shrink:0}
.c .plate-main{background:#1565c0;color:#fff}
.c .plate-cy{background:#ff6d00;color:#000}
.c .plate-kc{background:#aa00ff;color:#fff}
.c .plate-bj{background:#546e7a;color:#fff}
.plate-leg{display:inline-flex;align-items:center;gap:8px;flex-wrap:wrap;margin-left:2px}
.plate-leg .pl{display:inline-flex;align-items:center;gap:4px;font-size:11px;font-weight:700;color:#eee}
.plate-leg .pl span{font-size:10px;font-weight:900;padding:1px 5px;border-radius:3px;border:1px solid #fff}
.plate-leg .pl .plate-main{background:#1565c0;color:#fff}
.plate-leg .pl .plate-cy{background:#ff6d00;color:#000}
.plate-leg .pl .plate-kc{background:#aa00ff;color:#fff}
.plate-leg .pl .plate-bj{background:#546e7a;color:#fff}
.c.zt{border-style:solid;border-width:2px;border-color:#000;box-shadow:0 0 0 1px rgba(255,255,255,.35)}
.c.zb{border-style:dashed;border-width:3px;border-color:#ff9100;box-shadow:0 0 0 1px #ffea00,inset 0 0 0 1px rgba(255,145,0,.35);filter:saturate(.9);opacity:1;background-image:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(255,145,0,.06) 2px,rgba(255,145,0,.06) 4px)}
.c.wk{outline:3px solid #ffd54f;outline-offset:1px}
.c.mk{padding:2px 5px;margin:0 0 3px;font-size:10px;font-weight:800;width:auto;gap:2px;align-items:center}
.c.mk b{font-size:10px;flex:1;text-align:left}
.c.zb-mk{border-style:dashed;border-width:2px;border-color:#ff9100;background:#3d2800;color:#ffea00;box-shadow:0 0 0 1px #ffea00,inset 0 0 0 1px rgba(255,145,0,.35)}
.c.hf-mk{border-style:solid;border-width:2px;border-color:#00e676;background:#003d1f;color:#b9f6ca;box-shadow:0 0 0 1px #69f0ae}
.c em{font-style:normal;font-size:10px;background:#000;color:#fff;padding:0 3px;border-radius:2px}
.c em.r{background:#ffd54f;color:#000;font-weight:900}
.c:hover{filter:brightness(1.15);z-index:5}
#arrows{position:absolute;left:0;top:0;pointer-events:none;z-index:4;overflow:visible}
.mask{position:fixed;inset:0;background:rgba(0,0,0,.72);display:none;align-items:center;justify-content:center;z-index:40;padding:16px;backdrop-filter:blur(4px)}
.mask.on{display:flex}
.dlg{width:min(460px,100%);background:#161616;border:1px solid #3a3a3a;border-radius:14px;padding:16px 18px;box-shadow:0 16px 48px rgba(0,0,0,.55)}
.dlg h2{margin:0 0 4px;font-size:17px;color:#fff;font-weight:750}
.dlg .meta{color:var(--gold);font-size:12px;margin-bottom:10px}
.dlg .logic{background:#0a0a0a;border:1px solid #2a2a2a;border-radius:10px;padding:12px;line-height:1.6;white-space:pre-wrap;color:#eee}
.dlg button{margin-top:12px;width:100%;padding:9px;border:0;border-radius:999px;background:var(--gold);color:#111;font-weight:800;cursor:pointer;font-size:13px}
.dlg button:hover{filter:brightness(1.06)}
.edge-lab{font:10px/1.2 "Segoe UI","PingFang SC",system-ui,sans-serif;fill:#fff;paint-order:stroke;stroke:#000;stroke-width:3px;stroke-linejoin:round;pointer-events:none}
@media (max-width:720px){
  .head{padding:8px 12px 10px}
  h1{font-size:18px}
  .h-stat{min-width:64px;padding:6px 8px 5px}
  .h-stat b{font-size:18px}
}
""".strip()

FOOT_HTML = f'<div class="foot">{DISCLAIMER}</div>'


def cn_date(date: str) -> tuple[str, str]:
    d = datetime.strptime(date, "%Y-%m-%d")
    return f"{d.year}年{d.month}月{d.day}日", "周" + WEEKDAYS[d.weekday()]


def head_html(date: str, zt_n: int | str, zb_n: int | str, wk_n: int | str, leg: str, plate_leg: str) -> str:
    date_cn, wd = cn_date(date)
    return f"""<div class="topbar">
  <a class="brand" href="{HOME_URL}"><i></i>涨停时间轴</a>
  <div class="top-meta">按涨停逻辑分列</div>
</div>
<div class="title-row">
  <h1>{date_cn}<span class="wd">{wd}</span></h1>
  <div class="h-stats">
    <div class="h-stat zt"><b>{zt_n}</b><span>封板</span></div>
    <div class="h-stat zb"><b>{zb_n}</b><span>炸板</span></div>
    <div class="h-stat wk"><b>{wk_n}</b><span>弱封单</span></div>
  </div>
</div>
<div class="leg">{leg}<span class="leg-label">板别</span>{plate_leg}</div>
<div class="key">
  <span class="k"><b style="color:#fff">实心</b>涨停封板</span>
  <span class="k"><b style="color:#ff9100">虚线</b>炸板未回封</span>
  <span class="k"><b style="color:#ffd54f">黄框</b>弱封单&lt;3000万</span>
  <span class="k"><b style="color:#ffd54f">黄线</b>同列接力</span>
  <span class="k"><b style="color:#ff9100">橙虚线</b>炸板关联</span>
  <span class="k"><b style="color:#00e5ff">青线</b>跨列共享逻辑</span>
  <span class="k"><b style="color:#ff9100">炸</b>/<b style="color:#69f0ae">回</b>分时标记</span>
  <span class="k">点击卡片看逻辑 · 按住拖动 · 滚轮缩放</span>
</div>"""


def _close_div(html: str, start: int) -> int:
    """Return index just after the matching </div> for the <div...> at start."""
    open_tag_end = html.find(">", start)
    if open_tag_end < 0:
        raise ValueError("unclosed tag")
    i = open_tag_end + 1
    depth = 1
    while i < len(html) and depth:
        nxt_open = html.find("<div", i)
        nxt_close = html.find("</div>", i)
        if nxt_close < 0:
            raise ValueError("unclosed head")
        if nxt_open != -1 and nxt_open < nxt_close:
            depth += 1
            i = nxt_open + 4
        else:
            depth -= 1
            i = nxt_close + 6
    return i


def _parse_day_meta(html: str) -> tuple[str, str, str, str, str, str]:
    m = re.search(r"(20\d{2}-\d{2}-\d{2})", html)
    if not m:
        raise ValueError("no date in day html")
    date = m.group(1)
    zt = zb = wk = None
    m = re.search(r"封板\s*(\d+)\s*·\s*炸板\s*(\d+)\s*·\s*弱封单\s*(\d+)", html)
    if m:
        zt, zb, wk = m.group(1), m.group(2), m.group(3)
    else:
        mz = re.search(r'class="h-stat zt"><b>(\d+)</b>', html)
        mb = re.search(r'class="h-stat zb"><b>(\d+)</b>', html)
        mw = re.search(r'class="h-stat wk"><b>(\d+)</b>', html)
        if mz and mb and mw:
            zt, zb, wk = mz.group(1), mb.group(1), mw.group(1)
    if zt is None:
        raise ValueError(f"cannot parse stats for {date}")

    mleg = re.search(r'<div class="leg">(.*?)</div>', html, flags=re.S)
    leg_inner = mleg.group(1) if mleg else ""
    plate_leg = ""
    if "plate-leg" in leg_inner:
        parts = re.split(r"\s*·\s*板别\s*", leg_inner, maxsplit=1)
        if len(parts) == 2:
            leg, plate_leg = parts[0], parts[1]
        else:
            parts = re.split(r'<span class="leg-label">板别</span>', leg_inner, maxsplit=1)
            if len(parts) == 2:
                leg, plate_leg = parts[0], parts[1]
            else:
                m2 = re.search(r'(<span class="plate-leg".*</span>)', leg_inner, flags=re.S)
                if m2:
                    plate_leg = m2.group(1)
                    leg = leg_inner.replace(plate_leg, "")
                else:
                    leg = leg_inner
    else:
        leg = leg_inner
    return date, zt, zb, wk, leg, plate_leg


def reskin_day_html(html: str) -> str:
    from zoom_inject import _strip, ensure_zoom

    html = _strip(html)
    date, zt, zb, wk, leg, plate_leg = _parse_day_meta(html)
    html = re.sub(
        r"<style>.*?</style>",
        "<style>\n" + DAY_CSS + "\n</style>",
        html,
        count=1,
        flags=re.S,
    )
    html = re.sub(
        r"<title>.*?</title>",
        f"<title>{date} 涨停时间轴</title>",
        html,
        count=1,
    )
    start = html.find('<div class="head">')
    if start < 0:
        raise ValueError("no .head in day html")
    end = _close_div(html, start)
    new_head = '<div class="head">\n' + head_html(date, zt, zb, wk, leg, plate_leg) + "\n</div>"
    html = html[:start] + new_head + html[end:]

    if 'class="foot"' not in html:
        html = re.sub(
            r"(</div>\s*)</div>(\s*<div class=\"mask\")",
            r"\1" + FOOT_HTML + r"</div>\2",
            html,
            count=1,
        )
        if 'class="foot"' not in html:
            raise ValueError("failed to insert footer")

    # page used to be auto 1fr; new CSS already sets auto 1fr auto
    return ensure_zoom(html)


def reskin_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    path.write_text(reskin_day_html(text), encoding="utf-8")
