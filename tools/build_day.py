#!/usr/bin/env python3
"""Build 涨停时间轴复盘 HTML — columns by 涨停逻辑 (reason_type), not industry.

Usage:
  python3 /workspace/zt-raw/build_day.py [--date 2026-10-21]

Reads:
  /workspace/zt-raw/ths/zt_pool_YYYYMMDD.json
  /workspace/zt-raw/ths/open_pool_YYYYMMDD.json
  /workspace/zt-raw/ths/block_top_YYYYMMDD.json  (optional, for zb reason)
  /workspace/zt-raw/zt_YYYYMMDD.json             (东财封单/精确时间)
  /workspace/zt-raw/zb_YYYYMMDD.json
Writes:
  /workspace/{date}-涨停时间轴复盘.html
  /workspace/{date}-zt-audit.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
WEAK_SEAL = 30_000_000
RAW = Path("/workspace/zt-raw")
OUT_DIR = Path("/workspace")

# (logic_name, bg, fg) — order = column order when present
LOGIC_PALETTE = [
    ("羊字辈", "#ffd600", "#001"),
    ("人形机器人", "#ff1744", "#fff"),
    ("工业机器人", "#ff5252", "#fff"),
    ("端侧AI", "#f50057", "#fff"),
    ("飞行汽车", "#00b0ff", "#001"),
    ("短剧传媒", "#f50057", "#fff"),
    ("词元算力", "#ff6d00", "#001"),
    ("数据要素", "#eceff1", "#111"),
    ("光模块材料", "#2979ff", "#fff"),
    ("卫星通信", "#651fff", "#fff"),
    ("益生菌", "#76ff03", "#001"),
    ("生猪养殖", "#ff9100", "#001"),
    ("医药", "#e040fb", "#fff"),
    ("消费零售", "#ffab00", "#001"),
    ("先进材料", "#00e5ff", "#001"),
    ("基建工程", "#8d6e63", "#fff"),
    ("数字能源", "#1de9b6", "#001"),
    ("安防AI", "#c6ff00", "#001"),
    ("独立逻辑", "#78909c", "#fff"),
]
LOGIC_COLOR = {n: (bg, fg) for n, bg, fg in LOGIC_PALETTE}

# Matchers: tag substring / synonym → logic. More specific first within each group.
# Assignment uses frequency + specificity + board height.
TAG_TO_LOGIC = [
    # specific first
    ("羊字辈", ["“羊”字辈", "羊字辈", "羊字"]),
    ("飞行汽车", ["飞行汽车"]),
    ("人形机器人", ["人形机器人", "具身机器人", "具身智能", "物理AI"]),
    ("工业机器人", ["工业机器人", "机器人传感", "机器人投资", "机器人应用", "MEMS传感"]),
    ("端侧AI", ["端侧AI", "通信模组", "无线模组"]),
    ("短剧传媒", [
        "微短剧", "AI漫剧", "AI短剧", "出版发行", "数字出版",
        "传媒内容", "高铁传媒", "裸眼3D", "AI创意", "影院运营", "广电网络",
    ]),
    ("词元算力", [
        "词元出海", "Token业务", "Token", "算力网络", "算力租赁",
        "太空算力", "AI算力服务器", "AI算力", "数据中心冷却", "数据中心",
    ]),
    ("数据要素", [
        "数据要素", "数据库", "数字财税", "AI财税", "数据分析",
        "云数服务", "数字政府", "政务智能体",
    ]),
    ("光模块材料", ["光模块胶", "电子胶"]),
    ("卫星通信", ["卫星通信", "SpaceX"]),
    ("益生菌", ["益生菌食品", "益生菌出海", "菌株研发", "益生菌"]),
    ("生猪养殖", ["生猪养殖", "供港活猪"]),
    ("医药", [
        "化学制药", "中药创新药", "抗癌药物", "生物医药", "质谱诊断",
        "体外诊断", "医药制造", "降脂复方药", "原料制剂一体化", "纳米炭铁",
    ]),
    ("消费零售", [
        "复合调味品", "厨房小家电", "豆浆机", "商贸零售", "商业地产",
        "羊毛羊绒", "男裤", "日用陶瓷", "酒器", "洗染服务", "对台贸易",
    ]),
    ("先进材料", [
        "MLCC粉体", "锂电电解液", "汽车电子玻璃", "差别化涤纶长丝",
        "仿皮草纤维", "钠电材料", "硅碳负极", "热熔胶",
    ]),
    ("基建工程", ["水泥熟料", "盾构机", "风电锻件", "重点工程", "专业照明"]),
    ("数字能源", ["变压器", "空冷器", "飞翼空冷器", "压缩机"]),
    ("安防AI", ["视频监控", "人工智能安防", "AI ISP", "信息安全", "网络安全大模型"]),
]

# Fallback keyword rules on name/hybk/reason text for zb or unmatched
FALLBACK_KW = [
    ("羊字辈", ["羊"]),
    ("医药", ["医药", "制药", "生物", "药业", "诊断"]),
    ("数据要素", ["数据", "软件", "税友", "银海", "财税", "IT服务"]),
    ("卫星通信", ["盛洋", "卫星", "航天"]),
    ("词元算力", ["算力", "词元", "Token", "数据中心"]),
    ("短剧传媒", ["传媒", "短剧", "出版", "影视", "广电"]),
    ("人形机器人", ["人形", "机器人"]),
    ("工业机器人", ["机器人", "机械"]),
    ("端侧AI", ["模组", "通信"]),
    ("飞行汽车", ["飞行", "低空", "eVTOL"]),
    ("消费零售", ["食品", "家电", "零售", "服装", "家居"]),
    ("先进材料", ["新材", "材料", "化学", "塑料", "光伏"]),
    ("基建工程", ["水泥", "工程", "基建", "重机"]),
    ("数字能源", ["电力", "空调", "能源"]),
]


def fmt_t_em(v) -> str:
    s = f"{int(v):06d}"
    return f"{s[0:2]}:{s[2:4]}:{s[4:6]}"


def fmt_t_ths(ts) -> str:
    if ts is None or ts == "":
        return "09:25:00"
    try:
        t = int(ts)
    except (TypeError, ValueError):
        return "09:25:00"
    # THS unix seconds (Asia/Shanghai wall clock via local tz)
    dt = datetime.fromtimestamp(t, TZ)
    return dt.strftime("%H:%M:%S")


def fmt_seal2(v) -> str:
    v = float(v or 0)
    if v >= 1e8:
        s = f"{v / 1e8:.2f}".rstrip("0").rstrip(".")
        return s + "亿"
    return f"{int(round(v / 10000))}万"


def bucket_time(t: str) -> str:
    hh, mm, ss = map(int, t.split(":"))
    if (hh, mm) == (9, 25):
        return "09:25"
    total = hh * 60 + mm
    b = (total // 5) * 5
    bh, bm = divmod(b, 60)
    return f"{bh:02d}:{bm:02d}"


def limit_type(fbt_hhmmss: str, lbt_hhmmss: str, zbc: int) -> str:
    def to_int(s: str) -> int:
        return int(s.replace(":", ""))

    fbt, lbt = to_int(fbt_hhmmss), to_int(lbt_hhmmss)
    if zbc == 0 and fbt == lbt and fbt <= 92500:
        return "一字板"
    if zbc == 0 and fbt <= 93000:
        return "一字板"
    if zbc and fbt <= 93000:
        return "T字板"
    return "换手板"


def board_from_high_days(high_days: str, lbc: int | None = None) -> tuple[str, str]:
    """Return (board_short, high_days_label)."""
    hd = (high_days or "").strip() or "首板"
    if hd == "首板":
        return "首板", "首板"
    m = re.search(r"(\d+)天(\d+)板", hd)
    if m:
        days, ct = int(m.group(1)), int(m.group(2))
        return f"{ct}连板", hd
    if lbc and lbc > 1:
        return f"{lbc}连板", f"{lbc}天{lbc}板"
    return hd, hd


def split_tags(reason_type: str | None) -> list[str]:
    if not reason_type:
        return []
    return [t.strip() for t in str(reason_type).split("+") if t.strip()]


def match_logics_from_tags(tags: list[str]) -> list[str]:
    """Return candidate logic names matched by tags (may be multiple)."""
    found = []
    for logic, keys in TAG_TO_LOGIC:
        for tag in tags:
            for k in keys:
                # key must equal tag or appear inside tag (not the reverse:
                # otherwise bare「机器人」falsely hits「人形机器人」)
                if tag == k or k in tag:
                    if logic not in found:
                        found.append(logic)
                    break
    # bare 「机器人」 without finer match → 工业机器人
    if "工业机器人" not in found and "人形机器人" not in found:
        for tag in tags:
            if tag == "机器人" or (
                "机器人" in tag and "人形" not in tag and "工业" not in tag
                and "具身" not in tag
            ):
                found.append("工业机器人")
                break
    return found


def fallback_logic(text: str) -> str:
    for logic, kws in FALLBACK_KW:
        for kw in kws:
            if kw in text:
                return logic
    return "独立逻辑"


def specificity_rank(logic: str) -> int:
    """Higher = more specific."""
    order = [
        "羊字辈", "飞行汽车", "人形机器人", "端侧AI", "光模块材料", "卫星通信",
        "益生菌", "生猪养殖", "词元算力", "短剧传媒", "数据要素", "工业机器人",
        "安防AI", "医药", "先进材料", "数字能源", "基建工程", "消费零售", "独立逻辑",
    ]
    try:
        return len(order) - order.index(logic)
    except ValueError:
        return 0


def board_height(high_days: str) -> int:
    m = re.search(r"(\d+)天(\d+)板", high_days or "")
    if m:
        return int(m.group(1)) * 10 + int(m.group(2))
    if (high_days or "") == "首板":
        return 1
    return 0


def load_block_reason_map(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    data = json.loads(path.read_text(encoding="utf-8"))
    blocks = data.get("data") or []
    for blk in blocks:
        for s in blk.get("stock_list") or []:
            c = s.get("code")
            if not c:
                continue
            if c not in out:
                out[c] = {
                    "reason_type": s.get("reason_type"),
                    "reason_info": s.get("reason_info") or "",
                    "high": s.get("high") or s.get("high_days"),
                    "block": blk.get("name") or "",
                }
            else:
                # keep first non-empty reason_type
                if not out[c].get("reason_type") and s.get("reason_type"):
                    out[c]["reason_type"] = s.get("reason_type")
                if not out[c].get("reason_info") and s.get("reason_info"):
                    out[c]["reason_info"] = s.get("reason_info")
    return out


def first_sentence_reason(reason_info: str) -> str:
    if not reason_info:
        return ""
    # Prefer 公司原因 first bullet
    m = re.search(r"公司原因：\s*\n?\s*1[、.]?\s*(.+?)(?:\n|$)", reason_info)
    if m:
        return m.group(1).strip()[:80]
    # else first non-empty line without 行业原因 header
    for line in reason_info.splitlines():
        line = line.strip()
        if not line or line.startswith("行业原因") or line.startswith("（免责"):
            continue
        if line.startswith("公司原因"):
            continue
        return line[:80]
    return ""


def assign_logic(
    tags: list[str],
    reason_type: str,
    name: str,
    hybk: str,
    high_days: str,
    logic_freq: Counter,
) -> str:
    cands = match_logics_from_tags(tags)
    if not cands:
        return fallback_logic(f"{reason_type} {name} {hybk}")

    def score(logic: str) -> tuple:
        # prefer higher today-frequency, then more specific, then higher board
        return (
            logic_freq.get(logic, 0),
            specificity_rank(logic),
            board_height(high_days),
        )

    # Hard overrides for clearly primary tags
    if any(t == "端侧AI" or t.startswith("端侧AI") for t in tags) and "端侧AI" in cands:
        return "端侧AI"
    if any("飞行汽车" in t for t in tags) and "飞行汽车" in cands:
        return "飞行汽车"
    if any(t in ("人形机器人", "具身机器人") or "人形机器人" in t for t in tags) and "人形机器人" in cands:
        # 具身智能 alone may still compete with 数据要素 below
        if any("人形机器人" in t or t == "具身机器人" for t in tags):
            return "人形机器人"
    if any("光模块胶" in t or t == "电子胶" for t in tags) and "光模块材料" in cands:
        return "光模块材料"
    if any("卫星通信" in t or t == "SpaceX" for t in tags) and "卫星通信" in cands:
        return "卫星通信"
    if any("益生菌" in t for t in tags) and "益生菌" in cands:
        return "益生菌"
    if any("生猪养殖" in t for t in tags) and "生猪养殖" in cands:
        return "生猪养殖"

    # 广电网络 → 短剧传媒 over 数据中心→词元算力
    if "短剧传媒" in cands and any(t in ("广电网络", "微短剧", "AI漫剧", "AI短剧", "出版发行") for t in tags):
        return "短剧传媒"

    # 羊字辈：今日高频情绪逻辑；仅让位给已硬覆盖的光模块/飞行/卫星等
    if "羊字辈" in cands and any("羊" in t and "字" in t for t in tags):
        return "羊字辈"

    # 数据要素 vs 具身：有明确数据要素/数据库标签且无具身/人形时，归数据要素
    if "数据要素" in cands and any(t in ("数据要素", "数据库", "数字财税") for t in tags):
        if not any("人形机器人" in t or t == "具身机器人" for t in tags):
            # 具身智能 soft → still prefer 数据要素 when 数据要素 tag present
            if "人形机器人" in cands and any(t == "具身智能" for t in tags):
                return "数据要素"
            if "数据要素" in [t for t in tags]:
                return "数据要素"

    best = max(cands, key=score)
    return best


def precount_logic_freq(zt_items: list[dict]) -> Counter:
    """Count how many zt stocks would match each logic (pre-assignment)."""
    freq: Counter = Counter()
    for x in zt_items:
        tags = split_tags(x.get("reason_type"))
        for logic in match_logics_from_tags(tags):
            freq[logic] += 1
        # also count 羊 in name as soft
        if "羊" in (x.get("name") or "") and "羊字辈" not in match_logics_from_tags(tags):
            # only if tags already have 羊
            pass
    return freq


def html_esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def meta_for(r, name_of):
    parts = []
    if r.get("to") and r["to"] in name_of:
        parts.append(f"→{name_of[r['to']]}")
    if r["status"] == "zb":
        parts.append(f"开{r['open_num']}")
        parts.append(r["first"][:5] if len(r["first"]) >= 5 else r["first"])
    else:
        parts.append(r["limit_type"])
        parts.append(r["high_days"])
        if r["open_num"]:
            parts.append(f"开{r['open_num']}")
        if r["open_num"] and r["first"] != r["last"]:
            parts.append(f"{r['first'][:5]}→{r['last'][:5]}")
        else:
            parts.append(r["first"][:5])
    return " · ".join(parts)


def badge(r):
    if r["status"] == "zb":
        return "炸"
    m = re.search(r"(\d+)连板", r["board"])
    if m:
        return f"{m.group(1)}板"
    m3 = re.search(r"(\d+)", r["board"])
    if "连板" in r["board"] and m3:
        return f"{m3.group(1)}板"
    return "1"


def build_records(date_compact: str, block_map: dict) -> list[dict]:
    ths_zt = json.loads((RAW / "ths" / f"zt_pool_{date_compact}.json").read_text(encoding="utf-8"))
    ths_op = json.loads((RAW / "ths" / f"open_pool_{date_compact}.json").read_text(encoding="utf-8"))
    em_zt = {x["c"]: x for x in json.loads((RAW / f"zt_{date_compact}.json").read_text(encoding="utf-8"))["data"]["pool"]}
    em_zb = {x["c"]: x for x in json.loads((RAW / f"zb_{date_compact}.json").read_text(encoding="utf-8"))["data"]["pool"]}

    zt_items = ths_zt["data"]["info"]
    op_items = ths_op["data"]["info"]
    logic_freq = precount_logic_freq(zt_items)

    records: list[dict] = []
    zt_codes = set()

    for x in zt_items:
        code = x["code"]
        zt_codes.add(code)
        name = x.get("name") or ""
        reason_type = x.get("reason_type") or ""
        tags = split_tags(reason_type)
        high_days = x.get("high_days") or "首板"
        em = em_zt.get(code) or {}
        # Prefer EM precise times & seal
        if em:
            first = fmt_t_em(em["fbt"])
            last = fmt_t_em(em["lbt"])
            seal = float(em.get("fund") or 0)
            open_num = int(em.get("zbc") or 0)
            hybk = em.get("hybk") or ""
            lbc = int(em.get("lbc") or 1)
            if em.get("zttj"):
                days = em["zttj"].get("days") or lbc
                ct = em["zttj"].get("ct") or lbc
                if days == ct == 1:
                    high_days = "首板"
                else:
                    high_days = f"{days}天{ct}板"
        else:
            first = fmt_t_ths(x.get("first_limit_up_time"))
            last = fmt_t_ths(x.get("last_limit_up_time") or x.get("first_limit_up_time"))
            seal = 0.0
            open_num = int(x.get("open_num") or 0)
            hybk = ""
            lbc = 1

        board, high_days = board_from_high_days(high_days, lbc if em else None)
        lt = limit_type(first, last, open_num)
        theme = assign_logic(tags, reason_type, name, hybk, high_days, logic_freq)
        logic = f"{reason_type}｜{high_days}｜{lt}"
        if open_num > 0:
            logic = logic + f"｜开板{open_num}次回封"

        records.append(
            {
                "code": code,
                "name": name,
                "status": "zt",
                "first": first,
                "last": last,
                "seal": seal,
                "reason": logic,
                "reason_type": reason_type,
                "tags": tags,
                "theme": theme,
                "board": board,
                "open_num": open_num,
                "high_days": high_days,
                "limit_type": lt,
                "hybk": hybk,
                "to": "",
            }
        )

    for x in op_items:
        code = x["code"]
        if code in zt_codes:
            continue
        name = x.get("name") or ""
        em = em_zb.get(code) or {}
        bm = block_map.get(code) or {}
        reason_type = x.get("reason_type") or bm.get("reason_type") or ""
        reason_info = bm.get("reason_info") or ""
        if em:
            first = fmt_t_em(em["fbt"])
            open_num = int(em.get("zbc") or x.get("open_num") or 1)
            hybk = em.get("hybk") or ""
        else:
            first = fmt_t_ths(x.get("first_limit_up_time"))
            open_num = int(x.get("open_num") or 1)
            hybk = ""
        tags = split_tags(reason_type)
        # Infer tags/logic for zb
        if not tags:
            tip = first_sentence_reason(reason_info)
            text = f"{name} {hybk} {tip} {bm.get('block') or ''}"
            theme = fallback_logic(text)
            # synthesize a short reason_type-like string
            if tip:
                reason_type = tip[:60]
            else:
                reason_type = hybk or theme
            tags = split_tags(reason_type) if "+" in reason_type else ([reason_type] if reason_type else [])
        else:
            theme = assign_logic(tags, reason_type, name, hybk, "炸板", logic_freq)

        logic = f"冲板未回封｜{reason_type}｜炸×{open_num}"
        records.append(
            {
                "code": code,
                "name": name,
                "status": "zb",
                "first": first,
                "last": first,
                "seal": 0.0,
                "reason": logic,
                "reason_type": reason_type,
                "tags": tags,
                "theme": theme,
                "board": "炸板",
                "open_num": open_num,
                "high_days": "炸板",
                "limit_type": "炸板",
                "hybk": hybk,
                "to": "",
            }
        )

    # Reconcile rare singleton columns: keep 独立逻辑 only when truly alone
    # (already using named small logics — OK)

    return records


def shared_tags(a: dict, b: dict) -> list[str]:
    ta = set(a.get("tags") or [])
    tb = set(b.get("tags") or [])
    # normalize sheep
    def norm(t: str) -> str:
        if "羊" in t and "字" in t:
            return "羊字辈"
        return t

    ta = {norm(t) for t in ta}
    tb = {norm(t) for t in tb}
    common = ta & tb
    # also theme-level secondary: if both themes different but share mapped secondary tags
    return sorted(common, key=lambda t: -len(t))


def chain_within_logic(recs: list[dict]) -> None:
    by_theme = defaultdict(list)
    for r in recs:
        by_theme[r["theme"]].append(r)
    for th, lst in by_theme.items():
        lst.sort(key=lambda x: (x["first"], 0 if x["status"] == "zt" else 1, x["code"]))
        zts = [x for x in lst if x["status"] == "zt"]
        for i, r in enumerate(zts):
            r["to"] = zts[i + 1]["code"] if i + 1 < len(zts) else ""
        for r in lst:
            if r["status"] == "zb":
                later = [z for z in zts if z["first"] >= r["first"]]
                # prefer shared tags
                if later:
                    scored = []
                    for z in later:
                        sh = shared_tags(r, z)
                        scored.append((1 if sh or z["theme"] == r["theme"] else 0, z["first"], z))
                    scored.sort(key=lambda x: (-x[0], x[1]))
                    r["to"] = scored[0][2]["code"] if scored else ""
                elif zts:
                    r["to"] = zts[-1]["code"]
                else:
                    r["to"] = ""


def build_edges(recs: list[dict]) -> list[list]:
    by = {r["code"]: r for r in recs}
    edges: list[list] = []
    seen: set = set()

    def add(a, b, reason, st):
        if a not in by or b not in by or a == b:
            return
        key = (a, b, st)
        if key in seen:
            return
        # also skip reverse duplicate for same type
        if (b, a, st) in seen and st == "x":
            return
        seen.add(key)
        edges.append([a, b, reason, st])

    # Yellow: same-column zt chain
    for r in recs:
        if r["status"] != "zt" or not r.get("to"):
            continue
        th = r["theme"]
        label = f"{th}接力"
        add(r["code"], r["to"], label, "zt")

    # Orange: zb → later same-logic or shared-tag zt (skip vague 独立逻辑→独立逻辑)
    for r in recs:
        if r["status"] != "zb" or not r.get("to"):
            continue
        tgt = by.get(r["to"])
        if not tgt:
            continue
        sh = shared_tags(r, tgt)
        same = tgt["theme"] == r["theme"]
        if r["theme"] == "独立逻辑" and tgt["theme"] == "独立逻辑" and not sh:
            continue
        if sh:
            lab = f"炸板→{'/'.join(sh[:2])}"
        elif same and r["theme"] != "独立逻辑":
            lab = f"炸板→{r['theme']}"
        elif same:
            continue
        else:
            lab = f"炸板→{tgt['theme']}"
        add(r["code"], r["to"], lab, "zb")

    # Cyan cross-column: shared secondary tags, limit ~12
    zt_recs = [r for r in recs if r["status"] == "zt"]
    # Index by normalized secondary tags (exclude the primary theme's main tag if only that)
    tag_index: dict[str, list] = defaultdict(list)
    SECONDARY_PRIORITY = [
        "羊字辈", "“羊”字辈", "数据要素", "人形机器人", "端侧AI",
        "出版发行", "AI漫剧", "AI短剧", "微短剧", "数据库", "算力网络",
        "Token业务", "词元出海", "飞行汽车", "卫星通信", "SpaceX",
        "光模块胶", "电子胶", "具身智能", "具身机器人", "机器人传感",
    ]
    # Exclude ultra-generic tags from cross edges
    CROSS_BLOCKLIST = {"AI应用", "业绩增长", "人工智能", "海外业务", "国企改革", "回购注销"}
    for r in zt_recs:
        for t in r.get("tags") or []:
            nt = "羊字辈" if ("羊" in t and "字" in t) else t
            tag_index[nt].append(r)

    cross = []
    used_pair = set()
    for tag in SECONDARY_PRIORITY:
        if tag in CROSS_BLOCKLIST:
            continue
        lst = tag_index.get(tag) or []
        # only stocks whose theme is NOT solely explained by this tag alone —
        # connect across different themes
        by_th = defaultdict(list)
        for r in lst:
            by_th[r["theme"]].append(r)
        if len(by_th) < 2:
            continue
        # connect earliest of theme A to earliest later of theme B
        flat = sorted(lst, key=lambda x: x["first"])
        for i in range(len(flat)):
            for j in range(i + 1, len(flat)):
                a, b = flat[i], flat[j]
                if a["theme"] == b["theme"]:
                    continue
                # skip if already yellow-chained directly
                if a.get("to") == b["code"]:
                    continue
                pair = (a["code"], b["code"])
                if pair in used_pair:
                    continue
                # tag should be secondary for at least one (not the column name itself for both)
                if tag in (a["theme"], b["theme"]) and a["theme"] == tag and b["theme"] == tag:
                    continue
                used_pair.add(pair)
                lab = f"共享·{tag}"
                cross.append((a["first"], a["code"], b["code"], lab))
                break  # one link per left node per tag
            if len(cross) >= 12:
                break
        if len(cross) >= 12:
            break

    # Prefer diverse pairs; cap 12; max 2 per shared tag
    cross.sort(key=lambda x: x[0])
    per_tag = Counter()
    kept = []
    for item in cross:
        lab = item[3]
        tag = lab.replace("共享·", "")
        if per_tag[tag] >= 2:
            continue
        per_tag[tag] += 1
        kept.append(item)
        if len(kept) >= 12:
            break
    for _, a, b, lab in kept:
        add(a, b, lab, "x")

    return edges


def render_html(date: str, recs: list[dict], edges: list[list]) -> tuple[str, int, int, int, Counter]:
    name_of = {r["code"]: r["name"] for r in recs}
    for r in recs:
        r["meta"] = meta_for(r, name_of)

    zt_n = sum(1 for r in recs if r["status"] == "zt")
    zb_n = sum(1 for r in recs if r["status"] == "zb")
    wk_n = sum(1 for r in recs if r["status"] == "zt" and r["seal"] < WEAK_SEAL)

    theme_counts = Counter(r["theme"] for r in recs)
    themes_present = [(t, bg, fg) for t, bg, fg in LOGIC_PALETTE if theme_counts[t] > 0]
    for th in theme_counts:
        if th not in LOGIC_COLOR:
            themes_present.append((th, "#78909c", "#fff"))

    header_arr = {}
    for th, _, _ in themes_present:
        lst = sorted(
            [r for r in recs if r["theme"] == th],
            key=lambda x: (x["first"], 0 if x["status"] == "zt" else 1),
        )
        zts = [r for r in lst if r["status"] == "zt"]
        show = zts[:3] if zts else lst[:3]
        names = [x["name"] for x in show]
        while len(names) < 3:
            names.append("—")
        header_arr[th] = " → ".join(names[:3])

    buckets = sorted({bucket_time(r["first"]) for r in recs})
    grid = defaultdict(lambda: defaultdict(list))
    for r in recs:
        b = bucket_time(r["first"])
        grid[b][r["theme"]].append(r)
    for b in grid:
        for th in grid[b]:
            grid[b][th].sort(key=lambda x: (x["first"], 0 if x["status"] == "zt" else 1, x["code"]))

    leg = "".join(
        f'<span class="lg"><i style="background:{bg}"></i>{th}{theme_counts[th]}</span>'
        for th, bg, fg in themes_present
    )

    th_cells = ["<th>时间</th>"]
    for th, bg, fg in themes_present:
        th_cells.append(
            f'<th style="border-top:4px solid {bg}">{th}<span class=\'arr\'>{header_arr[th]}</span></th>'
        )

    body_rows = []
    for b in buckets:
        cells = [f'<td class="tm">{b}</td>']
        for th, bg, fg in themes_present:
            parts = []
            for r in grid[b].get(th, []):
                wk = r["status"] == "zt" and r["seal"] < WEAK_SEAL
                cls = "c zb" if r["status"] == "zb" else "c zt"
                if wk:
                    cls += " wk"
                if r["status"] == "zb":
                    em = '<em class="r">炸</em>'
                elif wk:
                    em = f'<em class="r">{fmt_seal2(r["seal"])} 弱</em>'
                else:
                    em = f'<em class="">{fmt_seal2(r["seal"])}</em>'
                title = f'→ {name_of[r["to"]]}' if r.get("to") and r["to"] in name_of else ""
                to = r.get("to") or ""
                parts.append(
                    f'<button type="button" class="{cls}" id="s-{r["code"]}" '
                    f'data-to="{to}" data-logic="{html_esc(r["reason"])}" '
                    f'data-name="{html_esc(r["name"])}" data-code="{r["code"]}" '
                    f'data-meta="{html_esc(r["meta"])}" '
                    f'style="--bg:{bg};--fg:{fg}" title="{html_esc(title)}">'
                    f'<b>{html_esc(r["name"])}</b><i>{badge(r)}</i>{em}</button>'
                )
            cells.append(f'<td class="cell">{"".join(parts)}</td>')
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    edges_js = json.dumps(edges, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{date} 涨停时间轴（指向相关标的）</title>
<style>
:root{{--bg:#000;--panel:#0a0a0a;--text:#fff;--muted:#bbb;--line:#333}}
*{{box-sizing:border-box}}
html,body{{margin:0;height:100%;background:#000;color:#fff;font:12px/1.35 "Segoe UI",system-ui,sans-serif}}
.page{{height:100vh;display:grid;grid-template-rows:auto 1fr;position:relative}}
.head{{padding:8px 12px;background:#111;border-bottom:2px solid #fff}}
h1{{margin:0;font-size:16px;color:#fff}}
.sub{{color:#ccc;font-size:11px;margin:3px 0}}
.leg{{display:flex;flex-wrap:wrap;gap:6px 12px}}
.lg{{display:inline-flex;align-items:center;gap:5px;font-size:11px;color:#eee;font-weight:600}}
.lg i{{width:12px;height:12px;border-radius:2px;border:1px solid #fff}}
.key{{font-size:11px;color:#ddd;margin-top:4px}}
.wrap{{overflow:auto;padding:8px;min-height:0;position:relative;background:#000}}
#stage{{position:relative;display:inline-block;min-width:100%}}
table{{border-collapse:separate;border-spacing:0;width:max-content;min-width:100%;background:#111;position:relative;z-index:1}}
th,td{{border:1px solid #444;padding:4px;vertical-align:top}}
th{{background:#1a1a1a;color:#fff;position:sticky;top:0;z-index:3;font-size:11px;min-width:120px;max-width:160px;border-bottom:2px solid #fff}}
th .arr{{display:block;font-weight:500;color:#ff0;font-size:10px;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
td.tm{{position:sticky;left:0;background:#222;color:#0f0;font-weight:800;z-index:2;white-space:nowrap;min-width:48px;border-right:2px solid #0f0}}
.c{{display:flex;align-items:center;gap:4px;width:100%;margin:0 0 4px;padding:5px 6px;border-radius:4px;border:2px solid #000;background:var(--bg);color:var(--fg);cursor:pointer;font:inherit;font-weight:700;box-shadow:0 0 0 1px rgba(255,255,255,.35)}}
.c b{{flex:1;text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:inherit}}
.c i{{font-style:normal;font-size:10px;background:#000;color:#ff0;padding:0 3px;border-radius:2px}}
.c.zb{{border-style:dashed;border-width:2px;border-color:#000;filter:saturate(.85);opacity:.95}}
.c.wk{{outline:3px solid #ff0;outline-offset:1px}}
.c em{{font-style:normal;font-size:10px;background:#000;color:#fff;padding:0 3px;border-radius:2px}}
.c em.r{{background:#ff0;color:#000;font-weight:900}}
.c:hover{{filter:brightness(1.15);z-index:5}}
#arrows{{position:absolute;left:0;top:0;pointer-events:none;z-index:4;overflow:visible}}
.mask{{position:fixed;inset:0;background:rgba(0,0,0,.75);display:none;align-items:center;justify-content:center;z-index:40;padding:16px}}
.mask.on{{display:flex}}
.dlg{{width:min(440px,100%);background:#1a1a1a;border:2px solid #fff;border-radius:8px;padding:14px}}
.dlg h2{{margin:0 0 4px;font-size:15px;color:#fff}}
.dlg .meta{{color:#ff0;font-size:11px;margin-bottom:8px}}
.dlg .logic{{background:#000;border:1px solid #555;border-radius:6px;padding:10px;line-height:1.55;white-space:pre-wrap;color:#eee}}
.dlg button{{margin-top:10px;width:100%;padding:8px;border:0;border-radius:6px;background:#ff0;color:#000;font-weight:800;cursor:pointer}}

.edge-lab{{font:10px/1.2 "Segoe UI",system-ui,sans-serif;fill:#fff;paint-order:stroke;stroke:#000;stroke-width:3px;stroke-linejoin:round;pointer-events:none}}
</style></head><body>
<div class="page">
<div class="head">
<h1>{date} 涨停时间轴 · 按涨停逻辑分列</h1>
<div class="sub">封板{zt_n} · 炸板{zb_n} · 弱封单{wk_n} · 同列逻辑接力（黄实线）· 炸板关联（橙虚线）· 跨列共享逻辑（青实线）· 线上标注原因 · 数据：同花顺封板池 reason_type + 东财封单/时间</div>
<div class="leg">{leg}</div>
<div class="key">高对比色块 · 黄框=弱封单(&lt;3000万) · 悬停高亮相关线 · 点击看 reason_type｜高位｜板型 · 每条线中段有原因标签</div>
</div>
<div class="wrap" id="wrap">
<div id="stage">
<svg id="arrows" xmlns="http://www.w3.org/2000/svg">
<defs>
<marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
<path d="M0 0 L10 5 L0 10 z" fill="#ffea00"/>
</marker>
<marker id="ahz" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
<path d="M0 0 L10 5 L0 10 z" fill="#ff9100"/>
</marker>
<marker id="ahx" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
<path d="M0 0 L10 5 L0 10 z" fill="#00e5ff"/>
</marker>
</defs>
</svg>
<table id="grid"><thead><tr>{''.join(th_cells)}</tr></thead><tbody>
{''.join(body_rows)}
</tbody></table>
</div>
</div>
</div>
<div class="mask" id="mask"><div class="dlg">
<h2 id="p-name"></h2><div class="meta" id="p-meta"></div><div class="logic" id="p-logic"></div>
<button type="button" id="p-close">关闭</button>
</div></div>
<script>
const EDGES = {edges_js};
const svg = document.getElementById('arrows');
const stage = document.getElementById('stage');
const wrap = document.getElementById('wrap');

function offsetIn(el, root){{
  let x=0, y=0, n=el;
  while(n && n!==root){{
    x += n.offsetLeft;
    y += n.offsetTop;
    n = n.offsetParent;
  }}
  if(n!==root){{
    const sr=root.getBoundingClientRect(), r=el.getBoundingClientRect();
    return {{x:r.left-sr.left, y:r.top-sr.top}};
  }}
  return {{x,y}};
}}
function center(el){{
  if(!el) return null;
  const o = offsetIn(el, stage);
  return {{ x: o.x + el.offsetWidth/2, y1: o.y + 3, y2: o.y + el.offsetHeight - 3 }};
}}
function draw(highlight){{
  [...svg.querySelectorAll('.edge,.edge-lab')].forEach(p=>p.remove());
  const table = document.getElementById('grid');
  const W = table.offsetWidth;
  const H = table.offsetHeight;
  svg.setAttribute('width', W);
  svg.setAttribute('height', H);
  svg.style.width = W + 'px';
  svg.style.height = H + 'px';
  EDGES.forEach(([a,b,reason,st], idx)=>{{
    const ea=document.getElementById('s-'+a);
    const eb=document.getElementById('s-'+b);
    if(!ea||!eb) return;
    const A=center(ea), B=center(eb);
    if(!A||!B) return;
    const x1=A.x, y1=A.y2, x2=B.x, y2=B.y1;
    const midY = (y1+y2)/2;
    const bend = ((idx % 5) - 2) * 10;
    const mx = (x1+x2)/2 + bend;
    const my = midY + bend * 0.4;
    const d = 'M'+x1+','+y1+' C'+x1+','+my+' '+x2+','+my+' '+x2+','+y2;
    const p=document.createElementNS('http://www.w3.org/2000/svg','path');
    p.setAttribute('d', d);
    p.setAttribute('class','edge');
    p.setAttribute('data-a', a);
    p.setAttribute('data-b', b);
    const hi = !highlight || highlight===a || highlight===b;
    const zb = st==='zb';
    const xx = st==='x';
    const stroke = zb ? '#ff9100' : (xx ? '#00e5ff' : '#ffea00');
    p.setAttribute('stroke', stroke);
    p.setAttribute('stroke-width', hi ? 2.6 : 1.1);
    p.setAttribute('fill','none');
    p.setAttribute('opacity', hi ? 0.95 : 0.18);
    p.setAttribute('marker-end', zb ? 'url(#ahz)' : (xx ? 'url(#ahx)' : 'url(#ah)'));
    if(zb) p.setAttribute('stroke-dasharray','6 4');
    svg.appendChild(p);
    const t = document.createElementNS('http://www.w3.org/2000/svg','text');
    t.setAttribute('class','edge-lab');
    t.setAttribute('x', mx);
    t.setAttribute('y', my - 4);
    t.setAttribute('text-anchor','middle');
    t.setAttribute('opacity', hi ? 1 : 0.25);
    t.textContent = reason;
    svg.appendChild(t);
  }});
}}
let hi=null;
document.querySelectorAll('.c').forEach(el=>{{
  el.addEventListener('mouseenter',()=>{{ hi=el.dataset.code; draw(hi); }});
  el.addEventListener('mouseleave',()=>{{ hi=null; draw(null); }});
  el.addEventListener('click',()=>{{
    document.getElementById('p-name').textContent=el.dataset.name+'（'+el.dataset.code+'）';
    document.getElementById('p-meta').textContent=el.dataset.meta;
    const rel = EDGES.filter(e=>e[0]===el.dataset.code || e[1]===el.dataset.code)
      .map(e=>{{
        const other = e[0]===el.dataset.code ? e[1] : e[0];
        const o = document.getElementById('s-'+other);
        const on = o ? o.dataset.name : other;
        const dir = e[0]===el.dataset.code ? '→' : '←';
        return dir+' '+on+'｜'+e[2];
      }});
    const base = el.dataset.logic;
    const sep = String.fromCharCode(10);
    document.getElementById('p-logic').textContent = rel.length
      ? (base + sep + sep + '盘口关系：' + sep + rel.join(sep))
      : base;
    document.getElementById('mask').classList.add('on');
  }});
}});
document.getElementById('p-close').onclick=()=>document.getElementById('mask').classList.remove('on');
document.getElementById('mask').onclick=e=>{{if(e.target.id==='mask') e.currentTarget.classList.remove('on');}};
window.addEventListener('resize',()=>draw(hi));
requestAnimationFrame(()=>draw(null));
setTimeout(()=>draw(null), 100);
</script>
</body></html>"""
    return html, zt_n, zb_n, wk_n, theme_counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-10-21", help="YYYY-MM-DD")
    args = ap.parse_args()
    date = args.date
    date_compact = date.replace("-", "")

    zt_path = RAW / "ths" / f"zt_pool_{date_compact}.json"
    zb_path = RAW / "ths" / f"open_pool_{date_compact}.json"
    em_zt = RAW / f"zt_{date_compact}.json"
    em_zb = RAW / f"zb_{date_compact}.json"
    for p in (zt_path, zb_path, em_zt, em_zb):
        if not p.exists():
            print(f"missing data: {p}", file=sys.stderr)
            sys.exit(1)

    block_map = load_block_reason_map(RAW / "ths" / f"block_top_{date_compact}.json")
    recs = build_records(date_compact, block_map)
    chain_within_logic(recs)
    edges = build_edges(recs)
    html, zt_n, zb_n, wk_n, theme_counts = render_html(date, recs, edges)

    out = OUT_DIR / f"{date}-涨停时间轴复盘.html"
    audit_out = OUT_DIR / f"{date}-zt-audit.json"
    out.write_text(html, encoding="utf-8")

    audit_list = []
    for r in recs:
        audit_list.append(
            {
                "code": r["code"],
                "name": r["name"],
                "status": r["status"],
                "first": r["first"],
                "last": r["last"],
                "seal": r["seal"],
                "reason": r["reason"],
                "theme": r["theme"],
                "board": r["board"],
                "open_num": r["open_num"],
                "high_days": r["high_days"],
                "limit_type": r["limit_type"],
                "reason_type": r.get("reason_type") or "",
                "hybk": r.get("hybk") or "",
            }
        )
    audit_out.write_text(json.dumps(audit_list, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Also keep dated build script symlink-friendly copy
    dated = RAW / f"build_day_{date}.py"
    # do not overwrite if identical path; write pointer comment file only if missing
    edge_stats = Counter(e[3] for e in edges)
    print(f"wrote {out} bytes={out.stat().st_size}")
    print(f"audit {audit_out} count={len(audit_list)}")
    print(f"zt={zt_n} zb={zb_n} weak={wk_n}")
    print("logics", theme_counts.most_common())
    print("edges", dict(edge_stats), "total", len(edges))
    for e in edges[:8]:
        print(" edge", e)
    # sample reasons
    for r in recs[:5]:
        print(" sample", r["code"], r["name"], r["theme"], r["reason"][:80])
    print(f"summary 炸板{zb_n} · 弱封单{wk_n} · 封板{zt_n} · 逻辑列复盘")


if __name__ == "__main__":
    main()
