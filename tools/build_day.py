#!/usr/bin/env python3
"""Build 涨停时间轴复盘 HTML — columns by 涨停逻辑 (reason_type), not industry.

大列 vs 子逻辑：
  - 列名（theme）可为视觉归并大列：消费 / 医药 / 商业航天 / AI硬件 / 机器人 / 三季报 / 基建（见 SUB_TO_BUCKET）。
  - 每条记录保留 sub_logic（细逻辑）：箭头匹配与线上标签按子逻辑；
    卡片 reason 文案仍写各自主要涨停原因，禁止只写「消费」「医药」糊弄。
  - 同列黄实线接力：仅连共享子逻辑的票（如两只都是对台贸易 →「对台贸易接力」）；
    禁止「同题材接力·消费/大消费/医药」等伪串线。
  - 未入 SUB_TO_BUCKET / 当日大列的细逻辑归「其他」。
  - 羊字辈降级：有明确产业主线时 theme 归主线，羊只进 reason/关键词。
  - 禁止列名「独立逻辑」；当日韭研大列可含「大消费」「其他」。

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
  /workspace/zt-raw/trends/{date}/{code}.json  (东财分时缓存，开板票)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from zoom_inject import ensure_zoom
except ImportError:  # pragma: no cover
    ensure_zoom = None
try:
    from page_theme import DAY_CSS, FOOT_HTML, head_html
except ImportError:  # pragma: no cover
    DAY_CSS = FOOT_HTML = None
    head_html = None
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
WEAK_SEAL = 30_000_000
RAW = Path("/workspace/zt-raw")
OUT_DIR = Path("/workspace")
TRENDS_DIR = RAW / "trends"
TRENDS_HOSTS = [
    "53.push2his.eastmoney.com",
    "push2his.eastmoney.com",
    "push2delay.eastmoney.com",
    "82.push2his.eastmoney.com",
]
LIMIT_TOL = 0.01
TRENDS_WORKERS = 6

# (logic_name, bg, fg) — order = 列序
# 大列=当日韭研简图大列；细逻辑经 SUB_TO_BUCKET 映射；尾部微列并入其他。
# 箭头与卡片文案仍按 sub_logic；禁止「独立逻辑」糊桶，禁止伪串线。
# 2026-11-12 韭研大列（左→右=简图上→下）。
LOGIC_PALETTE = [
    # 2026-11-18 韭研全天简图大列（左→右=简图上→下）
    ("国产算力", "#7c4dff", "#fff"),
    ("AI硬件", "#00bcd4", "#001"),
    ("家电", "#ff9100", "#001"),
    ("机器人", "#2979ff", "#fff"),
    ("光刻机（胶）", "#ff1744", "#fff"),
    ("其他", "#78909c", "#fff"),
]


LOGIC_COLOR = {n: (bg, fg) for n, bg, fg in LOGIC_PALETTE}

# Fine logic → visual bucket column. Unmapped / tail micros go to 其他.
SUB_TO_BUCKET = {
    # —— 国产算力 ——
    "国产算力": "国产算力", "算力": "国产算力", "华为算力": "国产算力", "昇腾算力": "国产算力",
    "华为昇腾": "国产算力", "智算中心": "国产算力", "液冷算力": "国产算力", "液冷": "国产算力",
    "液冷服务器": "国产算力", "算力服务": "国产算力", "算力租赁": "国产算力", "算力服务器": "国产算力",
    "算力系统服务": "国产算力", "智算平台": "国产算力", "词元出海": "国产算力", "词元算力": "国产算力",
    "数据中心": "国产算力", "数据中心电源": "国产算力", "国产GPU": "国产算力", "TGU推理芯片": "国产算力",
    "鸿华算力引擎": "国产算力", "高速背板连接器": "国产算力", "云计算": "国产算力",
    "DeepSeek概念": "国产算力", "AI智能体": "国产算力",
    # —— AI硬件 ——
    "AI硬件": "AI硬件", "PCB": "AI硬件", "ABF载板": "AI硬件", "CPO": "AI硬件", "CPO检测": "AI硬件",
    "CPO概念": "AI硬件", "光通信": "AI硬件", "铜缆高速连接": "AI硬件", "7N高纯铜": "AI硬件",
    "ITO靶材": "AI硬件",
    # —— 家电 ——
    "家电": "家电", "小家电": "家电", "家用电器": "家电", "厨卫电器": "家电", "厨房小家电": "家电",
    "家电零部件": "家电", "家电出口": "家电", "白色家电": "家电", "黑色家电": "家电",
    "空调出口": "家电", "母婴小家电": "家电",
    # —— 机器人 ——
    "机器人": "机器人", "人形机器人": "机器人", "机器视觉": "机器人", "机器狗": "机器人",
    "宇树合作": "机器人", "工业机器人": "机器人", "具身机器人": "机器人", "减速器": "机器人",
    # —— 光刻机（胶）——
    "光刻机（胶）": "光刻机（胶）", "光刻机": "光刻机（胶）", "光刻胶": "光刻机（胶）",
    "光刻胶配套试剂": "光刻机（胶）", "光刻机冷却系统": "光刻机（胶）",
    "光刻胶用显影液": "光刻机（胶）", "光刻机寄售维修": "光刻机（胶）",
    "光刻机光源": "光刻机（胶）", "光刻胶重要单体": "光刻机（胶）",
    "湿电子化学品": "光刻机（胶）", "电子化学": "光刻机（胶）", "光源光学": "光刻机（胶）",
    # —— 其他（尾部及其余）——
    "公告": "其他", "控制权拟变更": "其他", "AI安全": "其他",
    "氯化铵涨价": "其他", "空冷器": "其他", "商业航天": "其他",
    "消费电子": "其他", "金属镍": "其他", "民爆": "其他",
    "影视院线": "其他", "影视传媒": "其他", "游戏": "其他",
    "房屋建设": "其他", "农药": "其他", "新材料": "其他",
    "华为概念": "其他", "光学光电": "其他", "光伏": "其他", "储能": "其他",
    "化学制药": "其他", "陶瓷纤维": "其他", "太空算力": "其他",
    "低空经济": "其他", "成品油": "其他", "装修装饰": "其他", "装修建材": "其他",
    "6G": "其他", "汽车整车": "其他", "工业母机": "其他", "智能电网": "其他",
    "家居用品": "其他", "冰雪经济": "其他", "焦炭": "其他", "制冷空调": "其他",
    "物流": "其他", "汽车零部件": "其他", "电力": "其他", "变压器": "其他",
    "电网设备": "其他", "大消费": "其他", "半导体": "其他", "端侧AI": "其他",
    "其他": "其他",
}

BUCKET_NAMES = frozenset(SUB_TO_BUCKET.values())


JIUYAN_BIG_COLUMNS = frozenset({
    "国产算力", "AI硬件", "家电", "机器人", "光刻机（胶）", "其他",
})


def apply_theme_bucket(rec: dict) -> None:
    """2026-11-18：顶栏=韭研大列（国产算力/AI硬件/家电/机器人/光刻机（胶）/其他）；卡片保留细逻辑。"""
    banned = ("独立逻辑",)
    raw_theme = (rec.get("theme") or "").strip()
    raw_sub = (rec.get("sub_logic") or "").strip()
    reason = (rec.get("reason_type") or "").strip()

    fine = raw_sub
    if not fine or fine in JIUYAN_BIG_COLUMNS or fine in banned:
        if reason and reason not in JIUYAN_BIG_COLUMNS and reason not in banned:
            fine = reason.split("+")[0].strip() or reason
        elif raw_theme and raw_theme not in JIUYAN_BIG_COLUMNS and raw_theme not in banned:
            fine = raw_theme
        else:
            fine = reason.split("+")[0].strip() if reason else (raw_theme or "个股逻辑")
    for b in banned:
        if fine == b or fine.startswith(b):
            fine = "个股逻辑"
            break
    # 羊字辈降级为关键词：细逻辑若仅羊字辈则保留文案，但下面进大列时不靠它成列
    rec["sub_logic"] = fine

    theme = None
    if raw_theme in JIUYAN_BIG_COLUMNS:
        theme = raw_theme
    elif raw_theme in SUB_TO_BUCKET:
        theme = SUB_TO_BUCKET[raw_theme]
    elif fine in SUB_TO_BUCKET:
        theme = SUB_TO_BUCKET[fine]
    else:
        blob = "+".join([reason, raw_theme, fine] + list(rec.get("tags") or []))
        for key, bucket in SUB_TO_BUCKET.items():
            if bucket == "其他":
                continue
            if key and key in blob:
                theme = bucket
                break
    if theme in banned or theme is None:
        theme = "其他"
    if theme not in JIUYAN_BIG_COLUMNS:
        theme = SUB_TO_BUCKET.get(theme, "其他")
        if theme not in JIUYAN_BIG_COLUMNS:
            theme = "其他"
    rec["theme"] = theme


CODE_OVERRIDES: dict[str, dict] = {
    "000017": {"theme": "黄金珠宝", "inject_tags": ["黄金珠宝", "黄金", "深中华A"]},
    "000032": {"theme": "AI智能体", "inject_tags": ["AI智能体", "DeepSeek概念"]},
    "000096": {"theme": "成品油", "inject_tags": ["成品油", "广聚能源"]},
    "000419": {"theme": "消费", "inject_tags": ["消费"]},
    "000426": {"theme": "白银", "inject_tags": ["白银", "兴业银锡"]},
    "000506": {"theme": "黄金", "inject_tags": ["黄金", "黄金", "招金黄金"]},
    "000518": {"theme": "生物医药"},
    "000525": {"theme": "农药", "inject_tags": ["百草枯", "农药"]},
    "000530": {"theme": "冰雪经济", "inject_tags": ["冰雪经济", "消费", "冰山冷热"]},
    "000592": {"theme": "对台贸易", "inject_tags": ["对台贸易", "福建板块"]},
    "000596": {"theme": "白酒", "inject_tags": ["白酒", "中期分红"]},
    "000603": {"theme": "黄金", "inject_tags": ["黄金", "黄金", "盛达资源"]},
    "000636": {"theme": "PCB", "inject_tags": ["PCB"]},
    "000657": {"theme": "PCB钻针", "inject_tags": ["PCB钻针", "PCB", "中钨高新"]},
    "000679": {"theme": "商贸零售", "inject_tags": ["商贸零售", "消费", "大连友谊"]},
    "000788": {"theme": "化学制药"},
    "000919": {"theme": "创新药", "inject_tags": ["创新药", "医药", "金陵药业"]},
    "000962": {"theme": "半导体靶材", "inject_tags": ["半导体靶材", "半导体", "东方钽业"]},
    "000975": {"theme": "黄金", "inject_tags": ["黄金", "黄金", "山金国际"]},
    "000995": {"theme": "消费", "inject_tags": ["消费", "白酒"]},
    "001201": {"theme": "生猪养殖"},
    "001216": {"theme": "MLCC", "inject_tags": ["MLCC粉体", "MLCC"]},
    "001219": {"theme": "三季报增长", "inject_tags": ["三季报增长", "青啤拟入主", "休闲食品"]},
    "001233": {"theme": "次新股", "inject_tags": ["次新股", "次新", "海安集团"]},
    "001239": {"theme": "盾构风电"},
    "001282": {"theme": "人形机器人", "inject_tags": ["人形机器人", "机器人", "三联锻造"], "zb_reason": "冲板未回封｜减速器+小米汽车+液冷服务器｜炸×{open_num}"},
    "001337": {"theme": "黄金采选", "inject_tags": ["黄金采选", "黄金", "四川黄金"]},
    "001339": {"theme": "物理AI", "inject_tags": ["物理AI", "物理AI", "智微智能"]},
    "001359": {"theme": "电子布", "inject_tags": ["电子布", "PCB", "平安电工"]},
    "001360": {"theme": "金矿并购", "inject_tags": ["金矿并购", "黄金", "南矿集团"], "zb_reason": "冲板未回封｜专用设备+能源及重型设备｜炸×{open_num}"},
    "001389": {"theme": "算力PCB", "inject_tags": ["算力PCB", "PCB", "广合科技"]},
    "002008": {"theme": "PCB设备", "inject_tags": ["PCB设备", "PCB", "大族激光"]},
    "002029": {"theme": "消费", "inject_tags": ["消费"]},
    "002058": {"theme": "固态电池", "inject_tags": ["固态电池", "电池产业链", "紫竹高科"]},
    "002081": {"theme": "半导体洁净室", "inject_tags": ["半导体洁净室", "半导体", "金螳螂"]},
    "002086": {"theme": "水产品", "inject_tags": ["水产品", "海参养殖"]},
    "002088": {"theme": "陶瓷纤维", "inject_tags": ["陶瓷纤维", "鲁阳节能"]},
    "002150": {"theme": "光伏", "inject_tags": ["光伏"]},
    "002155": {"theme": "黄金", "inject_tags": ["黄金", "黄金", "湖南黄金"]},
    "002156": {"theme": "先进封装", "inject_tags": ["先进封装", "半导体", "通富微电"]},
    "002172": {"theme": "脑机接口", "inject_tags": ["脑机接口", "医疗服务"]},
    "002222": {"theme": "光通信", "inject_tags": ["光通信", "AI硬件", "福晶科技"]},
    "002275": {"theme": "创新药", "inject_tags": ["创新药", "医药", "桂林三金"]},
    "002307": {"theme": "路桥基建", "inject_tags": ["基础建设", "基建市政工程"], "zb_reason": "冲板未回封｜基础建设+基建市政工程｜炸×{open_num}"},
    "002309": {"theme": "光伏组件", "inject_tags": ["光伏组件", "光伏", "中利集团"]},
    "002317": {"theme": "创新药", "inject_tags": ["创新药", "医药", "众生药业"]},
    "002353": {"theme": "燃气轮机", "inject_tags": ["燃气轮机", "燃气轮机", "杰瑞股份"]},
    "002355": {"theme": "低空经济", "inject_tags": ["低空经济", "华为概念", "算力概念", "通信技术"]},
    "002364": {"theme": "数据中心电源", "inject_tags": ["数据中心电源", "AI硬件", "中恒电气"]},
    "002371": {"theme": "半导体设备", "inject_tags": ["半导体设备", "半导体", "北方华创"]},
    "002388": {"theme": "固态电池", "inject_tags": ["固态电池", "电池产业链", "新亚制程"]},
    "002403": {"theme": "机器人", "inject_tags": ["机器人"]},
    "002409": {"theme": "前驱体材料", "inject_tags": ["前驱体材料", "半导体", "雅克科技"]},
    "002420": {"theme": "人形机器人", "inject_tags": ["人形机器人", "机器人概念"]},
    "002428": {"theme": "磷化铟长单", "inject_tags": ["磷化铟长单", "公告", "云南锗业"]},
    "002436": {"theme": "ABF载板", "inject_tags": ["ABF载板", "PCB", "兴森科技"]},
    "002462": {"theme": "医疗医药", "inject_tags": ["医疗医药"]},
    "002463": {"theme": "PCB", "inject_tags": ["PCB", "PCB", "沪电股份"]},
    "002529": {"theme": "光伏组件", "inject_tags": ["光伏组件", "光伏", "海源复材"]},
    "002535": {"theme": "军工装备", "inject_tags": ["军工", "军工装备"]},
    "002536": {"theme": "液冷泵", "inject_tags": ["液冷泵", "AI硬件", "飞龙股份"]},
    "002549": {"theme": "半导体材料", "inject_tags": ["工业气体", "氦气概念", "半导体概念"]},
    "002565": {"theme": "太空算力", "inject_tags": ["太空算力", "顺灏股份"]},
    "002578": {"theme": "光伏边框", "inject_tags": ["光伏边框", "光伏", "闽发铝业"]},
    "002580": {"theme": "锂电重组", "inject_tags": ["锂电重组"]},
    "002636": {"theme": "覆铜板", "inject_tags": ["覆铜板", "PCB", "金安国纪"]},
    "002652": {"theme": "半导体洁净室", "inject_tags": ["半导体洁净室", "半导体", "扬子新材"]},
    "002674": {"theme": "磷化铟", "inject_tags": ["磷化铟", "AI硬件", "兴业科技"]},
    "002716": {"theme": "黄金白银", "inject_tags": ["黄金白银", "湖南白银", "白银", "黄金"]},
    "002741": {"theme": "PCB化学品", "inject_tags": ["PCB化学品", "PCB", "光华科技"]},
    "002768": {"theme": "机器人", "inject_tags": ["机器人"]},
    "002811": {"theme": "深子半导", "inject_tags": ["深子半导", "半导体", "郑中设计"]},
    "002821": {"theme": "CDMO", "inject_tags": ["CDMO", "医药", "凯莱英"]},
    "002827": {"theme": "重组复牌", "inject_tags": ["重组复牌", "公告", "高争民爆"]},
    "002865": {"theme": "光伏BC", "inject_tags": ["BC电池", "光伏设备"]},
    "002876": {"theme": "偏光片", "inject_tags": ["偏光片", "三利谱"]},
    "002877": {"theme": "物理AI", "inject_tags": ["物理AI"]},
    "002889": {"theme": "半导体", "inject_tags": ["半导体"]},
    "002916": {"theme": "PCB", "inject_tags": ["PCB", "PCB", "深南电路"]},
    "002940": {"theme": "创新药", "inject_tags": ["创新药"]},
    "002943": {"theme": "半导体", "inject_tags": ["半导体"]},
    "002945": {"theme": "其他", "inject_tags": ["其他", "公告"]},
    "002971": {"theme": "六氟化钨", "inject_tags": ["六氟化钨", "电子特气", "和远气体", "AI硬件"]},
    "002975": {"theme": "磷化铟", "inject_tags": ["磷化铟", "AI硬件", "博杰股份"]},
    "002980": {"theme": "光模块检测", "inject_tags": ["光模块检测", "AI硬件", "华盛昌"]},
    "002990": {"theme": "机器人", "inject_tags": ["机器人"]},
    "002992": {"theme": "固态电池", "inject_tags": ["固态电池", "电池产业链", "宝明科技"]},
    "003021": {"theme": "灵巧手", "inject_tags": ["灵巧手", "机器人", "兆威机电"]},
    "003032": {"theme": "三季报增长", "inject_tags": ["三季报增长", "人工智能培训"]},
    "003033": {"theme": "灵巧手", "inject_tags": ["灵巧手", "机器人", "征和工业"]},
    "300006": {"theme": "抗癌药物"},
    "300030": {"theme": "医疗器械", "inject_tags": ["医疗器械", "智慧医疗", "真空采血"]},
    "300139": {"theme": "黄金", "inject_tags": ["黄金", "黄金", "晓程科技"]},
    "300489": {"theme": "磷化铟", "inject_tags": ["磷化铟", "AI硬件", "光智科技"]},
    "300666": {"theme": "靶材", "inject_tags": ["靶材", "半导体", "江丰电子"]},
    "300788": {"theme": "AI出版", "inject_tags": ["AI出版", "AI影视传媒", "中信出版"]},
    "300829": {"theme": "乳酸", "inject_tags": ["乳酸", "化学制品"], "zb_reason": "冲板未回封｜乳酸+化学制品｜炸×{open_num}"},
    "300943": {"theme": "SOFC", "inject_tags": ["SOFC", "燃气轮机", "春晖智控"]},
    "301070": {"theme": "无人驾驶AI", "inject_tags": ["无人驾驶AI", "AI硬件", "开勒股份"]},
    "301486": {"theme": "CPO光模块", "inject_tags": ["CPO概念", "光纤概念", "消费电子零部件及组装", "通信技术"], "zb_reason": "CPO+光纤概念+消费电子零部件｜冲板未回封｜炸×{open_num}"},
    "301520": {"theme": "创新药", "inject_tags": ["创新药", "CRO"]},
    "301583": {"theme": "次新股", "inject_tags": ["次新股", "次新", "托伦斯"]},
    "301658": {"theme": "光伏", "inject_tags": ["光伏"]},
    "301697": {"theme": "次新股", "inject_tags": ["次新股", "次新", "贝特利"]},
    "600113": {"theme": "商贸零售", "inject_tags": ["商贸零售", "农批市场"]},
    "600137": {"theme": "消费", "inject_tags": ["消费"]},
    "600172": {"theme": "基建", "inject_tags": ["基建"]},
    "600189": {"theme": "矿泉水", "inject_tags": ["矿泉水"]},
    "600206": {"theme": "靶材", "inject_tags": ["靶材", "半导体", "有研新材"]},
    "600215": {"theme": "工业机器人", "inject_tags": ["工业机器人", "仿生机器人"]},
    "600252": {"theme": "中药创新药"},
    "600261": {"theme": "商业航天", "inject_tags": ["商业航天", "激光通信"]},
    "600293": {"theme": "锂电重组", "inject_tags": ["重大重组", "锂电电解液"]},
    "600319": {"theme": "氯聚合物", "inject_tags": ["氯聚合物", "氯碱", "CPE"]},
    "600327": {"theme": "消费", "inject_tags": ["消费"]},
    "600371": {"theme": "玉米种业", "inject_tags": ["玉米种业", "万向德农"]},
    "600391": {"theme": "燃气轮机", "inject_tags": ["燃气轮机", "燃气轮机", "航发科技"]},
    "600510": {"theme": "牛仔布", "inject_tags": ["牛仔布", "新型城镇化"]},
    "600547": {"theme": "黄金", "inject_tags": ["黄金", "黄金", "山东黄金"]},
    "600584": {"theme": "先进封装", "inject_tags": ["先进封装", "半导体", "长电科技"]},
    "600605": {"theme": "半导体", "inject_tags": ["半导体"]},
    "600641": {"theme": "SOFC", "inject_tags": ["SOFC", "燃气轮机", "先导基电"]},
    "600699": {"theme": "人形机器人", "inject_tags": ["人形机器人", "机器人", "均胜电子"]},
    "600715": {"theme": "AI影视/传媒", "inject_tags": ["AI影视/传媒"]},
    "600721": {"theme": "医药外包", "inject_tags": ["医药外包", "复杂制剂"]},
    "600802": {"theme": "水泥基建"},
    "600838": {"theme": "商贸零售", "inject_tags": ["商贸零售", "商业地产"]},
    "600892": {"theme": "短剧", "inject_tags": ["短剧", "AI影视传媒", "大晟文化"]},
    "600988": {"theme": "黄金", "inject_tags": ["黄金", "黄金", "赤峰黄金"]},
    "601069": {"theme": "黄金", "inject_tags": ["黄金", "黄金", "西部黄金"]},
    "601123": {"theme": "次新股", "inject_tags": ["次新股", "次新", "马矿股份"]},
    "601208": {"theme": "高速树脂", "inject_tags": ["高速树脂", "PCB", "东材科技"]},
    "601212": {"theme": "黄金", "inject_tags": ["黄金", "黄金", "白银有色"]},
    "601222": {"theme": "低空经济", "inject_tags": ["低空经济"]},
    "601566": {"theme": "消费", "inject_tags": ["消费", "海峡两岸", "对台贸易"]},
    "601599": {"theme": "AI影视", "inject_tags": ["AI影视", "AI影视传媒", "浙文影业"]},
    "603048": {"theme": "冷锻工艺", "inject_tags": ["冷锻工艺", "机器人", "浙江黎明"]},
    "603058": {"theme": "半导体", "inject_tags": ["半导体", "半导体概念", "包装印刷"]},
    "603061": {"theme": "芯片测试设备", "inject_tags": ["芯片测试设备", "半导体", "金海通"]},
    "603067": {"theme": "军工装备", "inject_tags": ["军工装备"]},
    "603068": {"theme": "半导体", "inject_tags": ["半导体"]},
    "603115": {"theme": "电极箔", "inject_tags": ["电极箔", "PCB", "海星股份"]},
    "603127": {"theme": "CRO", "inject_tags": ["CRO", "医药", "昭衍新药"]},
    "603131": {"theme": "商业航天", "inject_tags": ["商业航天", "商业卫星"]},
    "603186": {"theme": "ABF膜", "inject_tags": ["ABF膜", "PCB", "华正新材"], "zb_reason": "冲板未回封｜PCB+半导体概念+印制电路板｜炸×{open_num}"},
    "603200": {"theme": "固态电池", "inject_tags": ["固态电池", "数据中心液冷"]},
    "603203": {"theme": "半导体封装", "inject_tags": ["半导体封装", "半导体", "快克智能"]},
    "603248": {"theme": "次新股", "inject_tags": ["次新股", "次新", "锡华科技"]},
    "603256": {"theme": "电子布", "inject_tags": ["电子布", "PCB", "宏和科技"]},
    "603259": {"theme": "创新药", "inject_tags": ["创新药", "医药", "药明康德"]},
    "603273": {"theme": "机器人", "inject_tags": ["机器人", "工业机器人", "机器人集成"]},
    "603283": {"theme": "半导体测试设备", "inject_tags": ["半导体测试设备", "半导体", "赛腾股份"]},
    "603330": {"theme": "电子膜", "inject_tags": ["电子膜", "CPO概念"], "zb_reason": "冲板未回封｜电子膜+CPO概念｜炸×{open_num}"},
    "603332": {"theme": "涤纶长丝", "inject_tags": ["差别化涤纶长丝", "涤纶"]},
    "603337": {"theme": "机器人", "inject_tags": ["机器人"]},
    "603351": {"theme": "化学制药", "inject_tags": ["化学制药"]},
    "603381": {"theme": "光伏边框", "inject_tags": ["光伏边框", "光伏", "永臻股份"]},
    "603598": {"theme": "AI短剧", "inject_tags": ["AI短剧", "AI影视传媒", "引力传媒"]},
    "603600": {"theme": "商贸零售", "inject_tags": ["家居用品", "跨境电商"], "zb_reason": "冲板未回封｜家居用品+跨境电商｜炸×{open_num}"},
    "603629": {"theme": "词元算力"},
    "603657": {"theme": "具身机器人", "inject_tags": ["具身机器人", "机器人", "春光科技"]},
    "603662": {"theme": "人形机器人", "inject_tags": ["人形机器人", "机器人", "柯力传感"]},
    "603696": {"theme": "对台贸易", "inject_tags": ["对台贸易"]},
    "603703": {"theme": "卫星通信", "inject_tags": ["卫星通信"]},
    "603721": {"theme": "数据要素", "inject_tags": ["数据要素"]},
    "603767": {"theme": "机器人减速器", "inject_tags": ["机器人减速器", "机器人", "中马传动"]},
    "603773": {"theme": "玻璃基板", "inject_tags": ["玻璃基板", "AI硬件", "沃格光电"]},
    "603777": {"theme": "休闲食品", "inject_tags": ["休闲食品", "消费", "来伊份"]},
    "603838": {"theme": "商贸零售", "inject_tags": ["商贸零售", "家居用品"]},
    "603893": {"theme": "端侧AI芯片", "inject_tags": ["端侧AI芯片", "半导体", "瑞芯微"]},
    "603950": {"theme": "燃气轮机", "inject_tags": ["燃气轮机", "燃气轮机", "长源东谷"]},
    "603955": {"theme": "羽毛球机器人", "inject_tags": ["羽毛球机器人", "机器人", "大千生态"]},
    "605058": {"theme": "PCB", "inject_tags": ["PCB", "HDI板", "AI服务器"]},
    "605111": {"theme": "功率半导体", "inject_tags": ["功率半导体", "半导体", "新洁能"]},
    "605258": {"theme": "PCB", "inject_tags": ["PCB"]},
    "605287": {"theme": "AI漫剧", "inject_tags": ["AI漫剧", "AI影视传媒", "德才股份"]},
    "605288": {"theme": "机器人零部件", "inject_tags": ["机器人零部件", "机器人", "凯迪股份"]},
    "605338": {"theme": "中式面点", "inject_tags": ["中式面点", "小笼包"]},
    "605358": {"theme": "机器人", "inject_tags": ["机器人"]},
    "605376": {"theme": "MLCC镍粉", "inject_tags": ["MLCC镍粉", "AI硬件", "博迁新材"]},
    "605488": {"theme": "物理AI手套", "inject_tags": ["物理AI手套", "机器人", "福莱新材"]},
    "605577": {"theme": "AI漫剧", "inject_tags": ["AI漫剧", "AI影视传媒", "龙版传媒"]},
    "688037": {"theme": "涂胶显影设备", "inject_tags": ["涂胶显影设备", "半导体", "芯源微"]},
    "688045": {"theme": "三季报增长", "inject_tags": ["三季报扭亏", "数字电源"]},
    "688072": {"theme": "薄膜沉积设备", "inject_tags": ["薄膜沉积设备", "半导体", "拓荆科技"]},
    "688082": {"theme": "半导体", "inject_tags": ["半导体"]},
    "688200": {"theme": "半导体测试设备", "inject_tags": ["半导体测试设备", "半导体", "华峰测控"]},
    "688361": {"theme": "半导体量检测", "inject_tags": ["半导体量检测", "半导体", "中科飞测"]},
    "688409": {"theme": "半导体零部件", "inject_tags": ["半导体零部件", "半导体", "富创精密"]},
    "688507": {"theme": "物理AI", "inject_tags": ["物理AI", "物理AI", "索辰科技"]},
    "688517": {"theme": "光储充", "inject_tags": ["光储充", "光伏", "金冠电气"]},
    "688536": {"theme": "模拟芯片", "inject_tags": ["模拟芯片", "半导体", "思瑞浦"]},
    "688596": {"theme": "电子特气", "inject_tags": ["电子特气", "半导体", "正帆科技"]},
    "688627": {"theme": "半导体设备", "inject_tags": ["半导体设备"]},
    "688652": {"theme": "半导体设备", "inject_tags": ["半导体设备", "半导体", "京仪装备"]},
    "688809": {"theme": "半导体探针卡", "inject_tags": ["半导体探针卡", "半导体", "强一股份"]},
    "688835": {"theme": "次新股", "inject_tags": ["次新股", "次新", "高凯技术"]},
    "920298": {"theme": "次新股", "inject_tags": ["次新股", "次新", "腾信精密"]},
    "920770": {"theme": "光伏电站", "inject_tags": ["光伏电站", "光伏", "艾能聚"]},
}

# 2026-11-17 韭研 code→大列 覆盖（简图确认）
_JIUYAN_OV = Path("/workspace/jiuyan/2026-11-18-code-overrides.json")
if _JIUYAN_OV.is_file():
    try:
        _ext = json.loads(_JIUYAN_OV.read_text(encoding="utf-8"))
        for _code, _ov in _ext.items():
            if not isinstance(_ov, dict) or "theme" not in _ov:
                continue
            _merged = dict(CODE_OVERRIDES.get(_code) or {})
            _merged["theme"] = _ov["theme"]
            if _ov.get("inject_tags"):
                _merged["inject_tags"] = list(_ov["inject_tags"])
            if _ov.get("zb_reason"):
                _merged["zb_reason"] = _ov["zb_reason"]
            if _ov.get("zt_reason"):
                _merged["zt_reason"] = _ov["zt_reason"]
            if _ov.get("high_days"):
                _merged["high_days"] = _ov["high_days"]
            if _ov.get("_fine"):
                _merged["sub_logic"] = _ov["_fine"]
            elif _ov.get("sub_logic"):
                _merged["sub_logic"] = _ov["sub_logic"]
            CODE_OVERRIDES[_code] = _merged
        print(f"[jiuyan] loaded {len(_ext)} code overrides from {_JIUYAN_OV}")
    except Exception as _e:  # pragma: no cover
        print(f"[jiuyan] override load failed: {_e}")

# Matchers: tag substring / synonym → logic. More specific first within each group.
TAG_TO_LOGIC = [
    ("羊字辈", ["“羊”字辈", "羊字辈", "羊字"]),
    ("飞行汽车", ["飞行汽车"]),
    ("低空经济", ["低空经济", "无人机"]),
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
        "云数服务", "数字政府", "政务智能体", "财税数字化",
    ]),
    ("AI智能体", ["AI智能体", "DeepSeek概念", "智谱AI概念"]),
    ("光模块材料", ["光模块胶", "电子胶"]),
    ("CPO光模块", ["CPO概念", "CPO", "光纤概念"]),
    ("商业航天", ["商业航天", "异轨激光", "激光通信"]),
    ("卫星通信", ["卫星通信", "SpaceX", "卫星互联网", "卫星通信终端"]),
    ("脑机接口", ["脑机接口"]),
    ("医疗器械", ["医疗器械", "真空采血", "智慧医疗"]),
    ("医药外包", ["医药外包", "CRO"]),
    ("白酒", ["白酒", "老窖池", "徽酒"]),
    ("矿泉水", ["矿泉水"]),
    ("中式面点", ["中式面点", "小笼包"]),
    ("水产品", ["水产品", "海参养殖"]),
    ("休闲食品", ["休闲食品", "饼干食品", "黑色食养"]),
    ("青啤拟入主", ["青啤拟入主"]),
    ("中期分红", ["中期分红"]),
    ("覆铜板", ["覆铜板", "CCL", "电子级玻纤"]),
    ("PCB", ["PCB", "HDI板", "印制电路板"]),
    ("AI硬件", ["AI硬件", "AI服务器"]),
    ("电子膜", ["电子膜"]),
    ("三季报增长", [
        "三季报增长", "三季报大增", "三季报高增", "三季报净利增长",
        "三季报扭亏", "三季报增", "三季报落地", "三季度净利增", "业绩环增",
    ]),
    ("固态电池", ["固态电池"]),
    ("陶瓷纤维", ["陶瓷纤维"]),
    ("农药", ["百草枯", "农药"]),
    ("牛仔布", ["牛仔布"]),
    ("乳酸", ["乳酸"]),
    ("益生菌", ["益生菌食品", "益生菌出海", "菌株研发", "益生菌"]),
    ("生猪养殖", ["生猪养殖", "供港活猪"]),
    ("中药创新药", ["中药创新药", "医药制造"]),
    ("抗癌药物", ["抗癌药物", "纳米炭铁"]),
    ("化学制药", ["化学制药", "降脂复方药", "原料制剂一体化"]),
    ("生物医药", ["生物医药", "长源并表", "中润老化"]),
    ("创新药", ["创新药"]),
    ("对台贸易", ["对台贸易", "海峡两岸"]),
    ("商贸零售", ["商贸零售", "商业地产", "洗染服务"]),
    ("MLCC", ["MLCC粉体", "MLCC"]),
    ("锂电重组", ["锂电电解液", "重大重组"]),
    ("光伏BC", ["BC电池", "光伏BC"]),
    ("半导体材料", ["工业气体", "氦气概念", "半导体概念", "光刻机"]),
    ("涤纶长丝", ["差别化涤纶长丝", "仿皮草纤维", "涤纶"]),
    ("氯聚合物", ["氯聚合物", "氯碱", "CPE"]),
    ("AI设计", ["AI设计", "半导体入股"]),
    ("油气装备", ["油气装备", "油气工程"]),
    ("军工装备", ["军工装备", "军工"]),
    ("水泥基建", ["水泥熟料", "重点工程", "福建国资"]),
    ("盾构风电", ["盾构机", "风电锻件"]),
    ("数字能源", ["变压器", "空冷器", "飞翼空冷器", "压缩机"]),
    ("安防AI", ["视频监控", "人工智能安防", "AI ISP", "信息安全", "网络安全大模型"]),
]

# Eastmoney CoreConception board name → logic (for zb with only industry hybk)
CONCEPT_TO_LOGIC = [
    ("人形机器人", ["人形机器人", "具身智能", "减速器"]),
    ("CPO光模块", ["CPO概念", "光纤概念"]),
    ("低空经济", ["低空经济"]),
    ("飞行汽车", ["飞行汽车", "eVTOL"]),
    ("数据要素", ["数据要素", "财税数字化"]),
    ("AI智能体", ["AI智能体", "DeepSeek概念"]),
    ("半导体材料", ["工业气体", "氦气概念", "光刻机", "半导体概念"]),
    ("光伏BC", ["BC电池"]),
    ("对台贸易", ["对台贸易", "海峡两岸"]),
    ("MLCC", ["MLCC"]),
    ("军工装备", ["军工"]),
    ("油气装备", ["油气"]),
    ("商业航天", ["商业航天", "异轨激光", "激光通信"]),
    ("卫星通信", ["卫星通信", "卫星互联网", "SpaceX"]),
    ("PCB", ["PCB", "印制电路板", "HDI"]),
    ("覆铜板", ["覆铜板", "CCL"]),
    ("脑机接口", ["脑机接口"]),
    ("医疗器械", ["医疗器械"]),
    ("医药外包", ["医药外包", "CRO"]),
    ("词元算力", ["算力概念", "英伟达概念"]),
    ("氯聚合物", ["氯碱"]),
    ("涤纶长丝", ["涤纶"]),
    ("工业机器人", ["机器人概念", "专用设备", "能源及重型设备"]),
    ("创新药", ["创新药"]),
    ("化学制药", ["化学制药"]),
    ("生物医药", ["生物医药"]),
    ("中药创新药", ["中药"]),
    ("抗癌药物", ["抗癌"]),
    ("路桥基建", ["基础建设", "基建市政工程", "工程建设", "PPP模式"]),
    ("商贸零售", ["跨境电商", "电商概念", "家居用品", "成品家居"]),
]

# Fallback keyword rules on name/hybk/reason text for zb or unmatched
# Banned: 大消费 / broad 消费零售 / 先进材料 paste-buckets
FALLBACK_KW = [
    ("商业航天", ["商业航天", "激光通信"]),
    ("卫星通信", ["盛洋", "卫星通信", "卫星"]),
    ("脑机接口", ["脑机接口"]),
    ("医疗器械", ["医疗器械", "采血"]),
    ("白酒", ["白酒"]),
    ("矿泉水", ["矿泉水"]),
    ("中式面点", ["中式面点", "小笼包"]),
    ("水产品", ["海参", "水产品"]),
    ("覆铜板", ["覆铜板"]),
    ("PCB", ["PCB", "HDI"]),
    ("三季报增长", ["三季报", "业绩环增"]),
    ("固态电池", ["固态电池"]),
    ("陶瓷纤维", ["陶瓷纤维"]),
    ("农药", ["百草枯", "农药"]),
    ("中药创新药", ["中药"]),
    ("抗癌药物", ["抗癌"]),
    ("创新药", ["创新药"]),
    ("化学制药", ["化学制药", "制药", "药业"]),
    ("生物医药", ["生物医药", "生物制品"]),
    ("数据要素", ["数据", "软件", "税友", "银海", "财税", "IT服务"]),
    ("词元算力", ["算力", "词元", "Token", "数据中心"]),
    ("短剧传媒", ["传媒", "短剧", "出版", "影视", "广电"]),
    ("人形机器人", ["人形"]),
    ("工业机器人", ["机器人", "机械"]),
    ("端侧AI", ["模组"]),
    ("飞行汽车", ["飞行", "eVTOL"]),
    ("低空经济", ["低空"]),
    ("商贸零售", ["零售", "洗染", "家居", "电商", "跨境"]),
    ("路桥基建", ["基建", "路桥", "市政"]),
    ("对台贸易", ["对台", "海峡两岸"]),
    ("光伏BC", ["光伏", "BC电池"]),
    ("半导体材料", ["半导体", "氦气", "工业气体"]),
    ("油气装备", ["油气", "石油"]),
    ("军工装备", ["军工"]),
    ("水泥基建", ["水泥"]),
    ("盾构风电", ["盾构", "风电锻件"]),
    ("数字能源", ["电力", "空调", "能源"]),
    ("氯聚合物", ["氯碱", "CPE"]),
    ("涤纶长丝", ["涤纶", "化纤"]),
    # 羊字辈最后：仅字辈情绪、无产业关键词时才命中
    ("羊字辈", ["“羊”字辈", "羊字辈"]),
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


def plate_of(code: str) -> str:
    """A-share exchange segment from code: 科创/创业/北证/主板."""
    c = str(code or "").strip()
    if c.startswith("688"):
        return "科创"
    if c.startswith(("300", "301")):
        return "创业"
    if c.startswith(("8", "4")) and len(c) == 6:
        return "北证"
    if c.startswith("92") and len(c) == 6:
        return "北证"
    return "主板"


def secid_of(code: str) -> str:
    """Eastmoney secid: 沪市 1.xxxxxx，深市/北证 0.xxxxxx."""
    c = str(code or "").strip()
    if c.startswith("92") and len(c) == 6:
        return f"0.{c}"
    if c.startswith(("5", "6")) or c.startswith("900") or c.startswith("688"):
        return f"1.{c}"
    return f"0.{c}"


def limit_up_pct(code: str) -> float:
    plate = plate_of(code)
    if plate in ("创业", "科创"):
        return 0.20
    if plate == "北证":
        return 0.30
    return 0.10


def limit_up_price(pre_price: float, code: str) -> float:
    return round(float(pre_price) * (1.0 + limit_up_pct(code)) + 1e-8, 2)


def _hhmm_to_hms(hhmm: str) -> str:
    hhmm = (hhmm or "").strip()
    if len(hhmm) == 5 and hhmm[2] == ":":
        return hhmm + ":00"
    if len(hhmm) >= 8 and hhmm[2] == ":":
        return hhmm[:8]
    return hhmm


def fetch_trends2(code: str, date: str, use_cache: bool = True) -> dict | None:
    """Fetch/cached Eastmoney trends2 for one code; filter bars to ``date``."""
    day_dir = TRENDS_DIR / date
    day_dir.mkdir(parents=True, exist_ok=True)
    cache = day_dir / f"{code}.json"
    if use_cache and cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            trends = data.get("trends") or []
            if trends and any(date in (t.split(",")[0] if isinstance(t, str) else "") for t in trends[:3] + trends[-3:]):
                return data
        except (json.JSONDecodeError, OSError):
            pass

    secid = secid_of(code)
    fields = (
        "fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13"
        "&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
    )
    last_err: Exception | None = None
    for ndays in (1, 5):
        for host in TRENDS_HOSTS:
            url = (
                f"https://{host}/api/qt/stock/trends2/get?{fields}"
                f"&secid={secid}&ndays={ndays}&iscr=0"
            )
            for attempt in range(3):
                try:
                    req = urllib.request.Request(
                        url,
                        headers={
                            "User-Agent": "Mozilla/5.0 (compatible; zt-timeline/1.0)",
                            "Referer": "https://quote.eastmoney.com/",
                            "Accept": "application/json,*/*",
                        },
                    )
                    with urllib.request.urlopen(req, timeout=25) as resp:
                        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
                    data = payload.get("data") or {}
                    trends = data.get("trends") or []
                    if not trends:
                        last_err = RuntimeError(f"empty trends {code}@{host}")
                        break
                    day_bars = [t for t in trends if isinstance(t, str) and t.startswith(date)]
                    if not day_bars and ndays == 1:
                        # likely wrong day; try more ndays
                        last_err = RuntimeError(f"no bars for {date}")
                        break
                    if not day_bars:
                        continue
                    out = dict(data)
                    out["trends"] = day_bars
                    out["_fetched_host"] = host
                    out["_target_date"] = date
                    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
                    return out
                except Exception as e:  # noqa: BLE001 — network soft-fail
                    last_err = e
                    time.sleep(0.35 * (attempt + 1))
            time.sleep(0.15)
    if last_err:
        print(f"trends fail {code}: {last_err}", file=sys.stderr)
    return None


def infer_blast_reseal(
    trends_data: dict,
    code: str,
    first: str,
) -> tuple[list[str], list[str]]:
    """Minute close state machine: 封=进入涨停，炸=离开涨停.

    09:25/≤09:30 首封：分时从 09:30 起视为已封（池子 first 为准）。
    若 close 推演炸板为空但分时曾探低，再用 low 补一次（仍不强造）。
    """
    pre = float(trends_data.get("prePrice") or trends_data.get("preClose") or 0)
    if pre <= 0:
        return [], []
    lim = limit_up_price(pre, code)
    trends = trends_data.get("trends") or []

    def run(use_low: bool) -> tuple[list[str], list[str]]:
        try:
            fh, fm, _ = map(int, first.split(":"))
        except Exception:
            fh, fm = 9, 30
        sealed = (fh * 60 + fm) <= (9 * 60 + 30)
        blasts: list[str] = []
        reseals: list[str] = []
        for line in trends:
            if not isinstance(line, str):
                continue
            parts = line.split(",")
            if len(parts) < 5:
                continue
            try:
                hhmm = parts[0].split(" ")[1]
                close = float(parts[2])
                low = float(parts[4])
            except (IndexError, ValueError):
                continue
            end_at = close >= lim - LIMIT_TOL
            ts = _hhmm_to_hms(hhmm)
            if use_low:
                if sealed:
                    if low < lim - LIMIT_TOL:
                        blasts.append(ts)
                        if end_at:
                            if blasts:
                                reseals.append(ts)
                            sealed = True
                        else:
                            sealed = False
                elif end_at:
                    if blasts:
                        reseals.append(ts)
                    sealed = True
            else:
                if sealed and not end_at:
                    blasts.append(ts)
                    sealed = False
                elif (not sealed) and end_at:
                    # 首封不记入回封；仅炸板之后的再次封板记 reseal
                    if blasts:
                        reseals.append(ts)
                    sealed = True
        return blasts, reseals

    blasts, reseals = run(False)
    if not blasts:
        b2, r2 = run(True)
        if b2:
            return b2, r2
    return blasts, reseals


def apply_open_board_fallback(rec: dict) -> None:
    """Degrade when trends missing: last→回封；炸板不强造."""
    rec.setdefault("blast_times", [])
    rec.setdefault("reseal_times", [])
    rec.setdefault("last_blast", "")
    rec.setdefault("last_reseal", "")
    if int(rec.get("open_num") or 0) <= 0:
        return
    if rec["status"] == "zt" and rec.get("first") != rec.get("last"):
        if not rec["last_reseal"]:
            rec["last_reseal"] = rec["last"]
        if not rec["reseal_times"]:
            rec["reseal_times"] = [rec["last"]]


def enrich_records_blast_reseal(recs: list[dict], date: str) -> None:
    """Pull trends2 for open_num>0 names; fill blast/reseal fields."""
    targets = [r for r in recs if int(r.get("open_num") or 0) > 0]
    if not targets:
        for r in recs:
            r.setdefault("blast_times", [])
            r.setdefault("reseal_times", [])
            r.setdefault("last_blast", "")
            r.setdefault("last_reseal", "")
        return

    def work(rec: dict) -> tuple[str, list[str], list[str], bool]:
        data = fetch_trends2(rec["code"], date, use_cache=True)
        if not data:
            return rec["code"], [], [], False
        blasts, reseals = infer_blast_reseal(data, rec["code"], rec.get("first") or "09:30:00")
        return rec["code"], blasts, reseals, True

    results: dict[str, tuple[list[str], list[str], bool]] = {}
    with ThreadPoolExecutor(max_workers=TRENDS_WORKERS) as pool:
        futs = {pool.submit(work, r): r["code"] for r in targets}
        for fut in as_completed(futs):
            code, blasts, reseals, ok = fut.result()
            results[code] = (blasts, reseals, ok)

    for r in recs:
        r.setdefault("blast_times", [])
        r.setdefault("reseal_times", [])
        r.setdefault("last_blast", "")
        r.setdefault("last_reseal", "")
        if int(r.get("open_num") or 0) <= 0:
            continue
        blasts, reseals, ok = results.get(r["code"], ([], [], False))
        if ok:
            r["blast_times"] = blasts
            r["reseal_times"] = reseals
            r["last_blast"] = blasts[-1] if blasts else ""
            r["last_reseal"] = reseals[-1] if reseals else ""
            # zt 最终回封：分时未抓到时用池子 last
            if r["status"] == "zt" and not r["last_reseal"] and r.get("first") != r.get("last"):
                r["last_reseal"] = r["last"]
                r["reseal_times"] = list(reseals) + [r["last"]]
        apply_open_board_fallback(r)


def logic_with_times(r: dict) -> str:
    base = r.get("reason") or ""
    extras = []
    if r.get("blast_times"):
        extras.append("炸板:" + ",".join(t[:5] for t in r["blast_times"]))
    elif r.get("last_blast"):
        extras.append("炸板:" + r["last_blast"][:5])
    if r.get("reseal_times"):
        extras.append("回封:" + ",".join(t[:5] for t in r["reseal_times"]))
    elif r.get("last_reseal"):
        extras.append("回封:" + r["last_reseal"][:5])
    if extras:
        return base + "｜" + "｜".join(extras)
    return base


def card_em_html(r: dict) -> str:
    """Right-side pill on main card: seal / 炸HH:MM / 回HH:MM."""
    if r["status"] == "zb":
        lb = r.get("last_blast") or ""
        on = int(r.get("open_num") or 1)
        if lb:
            label = f"炸{lb[:5]}" + (f"×{on}" if on > 1 else "")
        else:
            label = f"炸×{on}"
        return f'<em class="r">{html_esc(label)}</em>'
    on = int(r.get("open_num") or 0)
    if on > 0:
        parts = []
        lb = r.get("last_blast") or ""
        if lb:
            parts.append(f"炸{lb[:5]}" + (f"×{on}" if on > 1 else ""))
        else:
            parts.append(f"炸×{on}")
        lr = r.get("last_reseal") or ""
        if not lr and r.get("first") != r.get("last"):
            lr = r.get("last") or ""
        if lr:
            parts.append(f"回{lr[:5]}")
        if r["seal"] < WEAK_SEAL:
            parts.append("弱")
        return f'<em class="r">{html_esc(" ".join(parts))}</em>'
    wk = r["seal"] < WEAK_SEAL
    if wk:
        return f'<em class="r">{fmt_seal2(r["seal"])} 弱</em>'
    return f'<em class="">{fmt_seal2(r["seal"])}</em>'


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
    # Singleton from first token — never 「独立逻辑/其他/大消费」糊桶
    for part in re.split(r"[+｜|\s,，/]", (text or "").strip()):
        part = part.strip()
        if part and part not in {"冲板未回封", "炸板"} and len(part) <= 12:
            return part[:10]
    return "个股逻辑"


def specificity_rank(logic: str) -> int:
    """Higher = more specific."""
    order = [
        "飞行汽车", "低空经济", "人形机器人", "端侧AI", "CPO光模块",
        "光模块材料", "商业航天", "卫星通信", "异轨激光", "脑机接口", "医疗器械",
        "白酒", "矿泉水", "中式面点", "水产品", "休闲食品", "青啤拟入主",
        "益生菌", "生猪养殖", "AI智能体", "AI设计", "覆铜板", "PCB", "AI硬件", "电子膜",
        "MLCC", "锂电重组", "光伏BC", "半导体材料", "涤纶长丝", "氯聚合物",
        "对台贸易", "油气装备", "军工装备", "词元算力", "短剧传媒", "数据要素",
        "工业机器人", "安防AI", "中药创新药", "抗癌药物", "化学制药", "生物医药",
        "创新药", "医药外包", "商贸零售", "中期分红", "数字能源", "水泥基建", "盾构风电",
        "固态电池", "陶瓷纤维", "农药", "牛仔布", "乳酸",
        "三季报增长", "羊字辈",
    ]
    try:
        return len(order) - order.index(logic)
    except ValueError:
        return 0


def load_concepts(date_compact: str) -> dict[str, dict]:
    """Load cached Eastmoney CoreConception boards: {code: {boards, keys}}."""
    p = RAW / "ths" / f"concepts_{date_compact}.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def concept_board_names(concepts: dict, code: str) -> list[str]:
    item = concepts.get(code) or {}
    boards = item.get("boards") or []
    return [b.get("BOARD_NAME") or "" for b in boards if b.get("BOARD_NAME")]


def match_logic_from_concepts(board_names: list[str]) -> tuple[str | None, list[str]]:
    """Return (logic, matched_board_names) from CoreConception boards."""
    if not board_names:
        return None, []
    for logic, keys in CONCEPT_TO_LOGIC:
        hits = []
        for bn in board_names:
            for k in keys:
                if bn == k or k in bn:
                    hits.append(bn)
                    break
        if hits:
            return logic, hits
    return None, []


FORBIDDEN_LABEL_FRAGMENTS = (
    "大消费",
    "独立逻辑",
    "其他",
    "同题材接力·其他",
    "同题材接力·大消费",
    "同题材接力·消费",
    "同题材接力·医药",
    "同题材接力·基建",
    "同题材接力·商业航天",
    "同题材接力·AI硬件",
    "同题材接力·机器人",
    "同题材接力·三季报",
    "同题材接力·行业",
    # 仅禁大列糊名接力；勿加「机器人接力」等后缀，否则会误伤「工业机器人接力」
    "消费接力",
    "医药接力",
    "基建接力",
)


def sanitize_label(s: str) -> str:
    out = s
    for frag in FORBIDDEN_LABEL_FRAGMENTS:
        out = out.replace(frag, "")
    return out


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
    if any("对台贸易" in t or "海峡两岸" in t for t in tags) and "对台贸易" in cands:
        return "对台贸易"
    if any(t in ("MLCC粉体", "MLCC") or "MLCC" in t for t in tags) and "MLCC" in cands:
        return "MLCC"
    if any("锂电电解液" in t or t == "重大重组" for t in tags) and "锂电重组" in cands:
        return "锂电重组"
    if any("差别化涤纶长丝" in t or t == "涤纶" for t in tags) and "涤纶长丝" in cands:
        return "涤纶长丝"
    if any("AI设计" in t or "半导体入股" in t for t in tags) and "AI设计" in cands:
        return "AI设计"
    if any("CPO" in t or "光纤概念" in t for t in tags) and "CPO光模块" in cands:
        return "CPO光模块"
    if any("AI智能体" in t or "DeepSeek" in t for t in tags) and "AI智能体" in cands:
        return "AI智能体"
    if any("低空经济" in t for t in tags) and "低空经济" in cands:
        return "低空经济"
    # 医药/基建：按具体主逻辑标签，禁止糊桶
    if any("中药创新药" in t for t in tags) and "中药创新药" in cands:
        return "中药创新药"
    if any("抗癌药物" in t or "纳米炭铁" in t for t in tags) and "抗癌药物" in cands:
        return "抗癌药物"
    if any(t in ("化学制药", "降脂复方药") or "原料制剂" in t for t in tags) and "化学制药" in cands:
        return "化学制药"
    if any(t in ("生物医药", "长源并表") or "中润老化" in t for t in tags) and "生物医药" in cands:
        return "生物医药"
    if any(t == "创新药" or t.startswith("创新药") for t in tags) and "创新药" in cands:
        return "创新药"
    if any("水泥熟料" in t or "福建国资" in t for t in tags) and "水泥基建" in cands:
        return "水泥基建"
    if any("盾构机" in t or "风电锻件" in t for t in tags) and "盾构风电" in cands:
        return "盾构风电"

    # 广电网络 → 短剧传媒 over 数据中心→词元算力
    if "短剧传媒" in cands and any(t in ("广电网络", "微短剧", "AI漫剧", "AI短剧", "出版发行") for t in tags):
        return "短剧传媒"

    # 商业航天 / 卫星（优先于羊字辈与三季报）
    if any("商业航天" in t or "激光通信" in t or "异轨激光" in t for t in tags):
        if "商业航天" in cands:
            return "商业航天"
        if "卫星通信" in cands:
            return "卫星通信"
    if any("卫星通信" in t or t == "SpaceX" or "卫星通信终端" in t for t in tags) and "卫星通信" in cands:
        return "卫星通信"
    # 医药细逻辑（含脑机/器械）优先于羊字辈
    if any("脑机接口" in t for t in tags) and "脑机接口" in cands:
        return "脑机接口"
    if any("医疗器械" in t or "真空采血" in t or "智慧医疗" in t for t in tags) and "医疗器械" in cands:
        return "医疗器械"
    if any("医药外包" in t or t == "CRO" for t in tags) and "医药外包" in cands:
        return "医药外包"
    # 消费细逻辑
    if any("白酒" in t or "老窖池" in t for t in tags) and "白酒" in cands:
        return "白酒"
    if any("矿泉水" in t for t in tags) and "矿泉水" in cands:
        return "矿泉水"
    if any("中式面点" in t or "小笼包" in t for t in tags) and "中式面点" in cands:
        return "中式面点"
    if any("海参养殖" in t or "水产品" in t for t in tags) and "水产品" in cands:
        return "水产品"
    # AI硬件
    if any("覆铜板" in t or t == "CCL" for t in tags) and "覆铜板" in cands:
        return "覆铜板"
    if any(t == "PCB" or "HDI" in t or "印制电路板" in t for t in tags) and "PCB" in cands:
        return "PCB"
    if any("AI服务器" in t or t == "AI硬件" for t in tags) and "AI硬件" in cands:
        return "AI硬件"

    # 羊字辈降级：仅当无其它产业候选时才成列；有主线则羊只留 reason/关键词
    if "羊字辈" in cands and any("羊" in t and "字" in t for t in tags):
        others = [c for c in cands if c != "羊字辈"]
        if not others:
            return "羊字辈"
        cands = others

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
        lb = r.get("last_blast") or ""
        if lb:
            parts.append(f"炸{lb[:5]}")
        elif r.get("blast_times"):
            parts.append(f"炸{r['blast_times'][-1][:5]}")
    else:
        parts.append(r["limit_type"])
        parts.append(r["high_days"])
        if r["open_num"]:
            parts.append(f"开{r['open_num']}")
        if r["open_num"] and r["first"] != r["last"]:
            parts.append(f"{r['first'][:5]}→{r['last'][:5]}")
        else:
            parts.append(r["first"][:5])
        lb = r.get("last_blast") or ""
        lr = r.get("last_reseal") or ""
        if lb:
            parts.append(f"炸{lb[:5]}")
        if lr and lr != r.get("first"):
            parts.append(f"回{lr[:5]}")
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


def _weak_industry_reason(reason_type: str, hybk: str) -> bool:
    rt = (reason_type or "").strip()
    if not rt:
        return True
    if "+" in rt:
        return False
    # single token that looks like EM industry bucket
    if rt == (hybk or "") or rt in {
        "消费电子", "塑料", "化学原料", "化学制品", "光伏设备", "包装印刷",
        "林业Ⅱ", "家居用品", "专用设备", "专业工程", "汽车零部", "综合Ⅱ",
        "光学光电", "家电零部", "IT服务Ⅱ",
    }:
        return True
    return False


def apply_code_override(rec: dict) -> None:
    """Force theme/tags/reason for explicitly remapped codes."""
    ov = CODE_OVERRIDES.get(rec["code"])
    if not ov:
        return
    rec["theme"] = ov["theme"]
    if ov.get("sub_logic"):
        rec["sub_logic"] = ov["sub_logic"]
    if ov.get("high_days"):
        rec["high_days"] = ov["high_days"]
        board, hd = board_from_high_days(ov["high_days"])
        rec["board"] = board
        rec["high_days"] = hd
        # keep card reason board-label in sync
        parts = (rec.get("reason") or "").split("｜")
        if len(parts) >= 2:
            parts[1] = hd
            rec["reason"] = "｜".join(parts)
    inject = list(ov.get("inject_tags") or [])
    if inject:
        # 韭研简图关键词为准，避免同花顺误标（如阳字辈写成羊字辈）造成伪串线
        rec["tags"] = [t for t in inject if t]
    if rec["status"] == "zb" and ov.get("zb_reason"):
        rec["reason"] = ov["zb_reason"].format(open_num=rec.get("open_num") or 1)
        if "｜" in rec["reason"]:
            rec["reason_type"] = rec["reason"].split("｜")[0]
    elif rec["status"] == "zb" and inject and _weak_industry_reason(
        rec.get("reason_type") or "", rec.get("hybk") or ""
    ):
        syn = "+".join(inject[:4])
        open_num = rec.get("open_num") or 1
        rec["reason_type"] = syn
        rec["reason"] = f"冲板未回封｜{syn}｜炸×{open_num}"
    elif rec["status"] == "zt" and ov.get("zt_reason"):
        rec["reason"] = ov["zt_reason"]
        if "｜" in rec["reason"]:
            rec["reason_type"] = rec["reason"].split("｜")[0]
    elif rec["status"] == "zt" and inject:
        syn = "+".join(inject)
        rec["reason_type"] = syn
        rest = rec.get("reason") or ""
        if "｜" in rest:
            rec["reason"] = syn + "｜" + "｜".join(rest.split("｜")[1:])
        else:
            rec["reason"] = syn


def build_records(date_compact: str, block_map: dict) -> list[dict]:
    ths_zt = json.loads((RAW / "ths" / f"zt_pool_{date_compact}.json").read_text(encoding="utf-8"))
    ths_op = json.loads((RAW / "ths" / f"open_pool_{date_compact}.json").read_text(encoding="utf-8"))
    em_zt = {x["c"]: x for x in json.loads((RAW / f"zt_{date_compact}.json").read_text(encoding="utf-8"))["data"]["pool"]}
    em_zb = {x["c"]: x for x in json.loads((RAW / f"zb_{date_compact}.json").read_text(encoding="utf-8"))["data"]["pool"]}
    concepts = load_concepts(date_compact)

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

        rec = {
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
            "plate": plate_of(code),
            "open_num": open_num,
            "high_days": high_days,
            "limit_type": lt,
            "hybk": hybk,
            "to": "",
        }
        apply_code_override(rec)
        apply_theme_bucket(rec)
        records.append(rec)

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
        boards = concept_board_names(concepts, code)
        concept_logic, concept_hits = match_logic_from_concepts(boards)

        # Infer tags/logic for zb — prefer THS reason_type, else CoreConception, else hybk
        if not tags:
            tip = first_sentence_reason(reason_info)
            if concept_hits:
                # use precise concept boards as reason_type tags (skip ultra-generic industry)
                prefer = [b for b in concept_hits if b not in {hybk, name}]
                # also pull a few high-signal boards even if not the matched key
                HIGH = (
                    "人形机器人", "CPO概念", "光纤概念", "低空经济", "AI智能体",
                    "DeepSeek概念", "BC电池", "工业气体", "氦气概念", "半导体概念",
                    "军工", "数据要素", "算力概念", "卫星通信", "卫星互联网",
                    "商业航天", "创新药", "氯碱", "消费电子零部件及组装", "通信技术",
                    "减速器", "PCB", "印制电路板", "基础建设", "跨境电商", "家居用品",
                )
                extra = [b for b in boards if b in HIGH and b not in prefer]
                syn_tags = (prefer + extra)[:4] or concept_hits[:3]
                reason_type = "+".join(syn_tags)
                tags = list(syn_tags)
                theme = concept_logic or fallback_logic(f"{name} {hybk} {tip}")
            else:
                text_fb = f"{name} {hybk} {tip} {bm.get('block') or ''}"
                theme = fallback_logic(text_fb)
                if tip:
                    reason_type = tip[:60]
                else:
                    reason_type = hybk or theme
                tags = split_tags(reason_type) if "+" in reason_type else ([reason_type] if reason_type else [])
        else:
            theme = assign_logic(tags, reason_type, name, hybk, "炸板", logic_freq)
            # if only weak industry tag, let concepts upgrade
            if theme in ("个股逻辑", "水泥基建") and concept_logic:
                theme = concept_logic
                for h in concept_hits:
                    if h not in tags:
                        tags.append(h)

        logic = f"冲板未回封｜{reason_type}｜炸×{open_num}"
        rec = {
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
            "plate": plate_of(code),
            "open_num": open_num,
            "high_days": "炸板",
            "limit_type": "炸板",
            "hybk": hybk,
            "to": "",
        }
        apply_code_override(rec)
        apply_theme_bucket(rec)
        records.append(rec)

    return records


def shared_tags(a: dict, b: dict) -> list[str]:
    ta = set(a.get("tags") or [])
    tb = set(b.get("tags") or [])

    def norm(t: str) -> str:
        if "羊" in t and "字" in t:
            return "羊字辈"
        if t in ("海峡两岸", "对台贸易") or "对台" in t:
            return "对台贸易"
        if "CPO" in t:
            return "CPO概念"
        if "光纤" in t:
            return "光纤概念"
        if t in ("MLCC粉体", "MLCC"):
            return "MLCC"
        return t

    ta = {norm(t) for t in ta}
    tb = {norm(t) for t in tb}
    common = ta & tb
    return sorted(common, key=lambda t: -len(t))


def chain_within_logic(recs: list[dict]) -> None:
    """Yellow/orange chain within visual columns, but only same sub_logic.

    Bucket columns (消费/医药/商业航天/AI硬件/机器人/三季报/基建) must NOT
    paste-chain across different sub_logics (e.g. 生猪养殖 ↔ 对台贸易).
    """
    by_theme = defaultdict(list)
    for r in recs:
        by_theme[r["theme"]].append(r)
    for th, lst in by_theme.items():
        lst.sort(key=lambda x: (x["first"], 0 if x["status"] == "zt" else 1, x["code"]))
        zts = [x for x in lst if x["status"] == "zt"]
        for i, r in enumerate(zts):
            r["to"] = ""
            for j in range(i + 1, len(zts)):
                nxt = zts[j]
                if (r.get("sub_logic") or r["theme"]) != (nxt.get("sub_logic") or nxt["theme"]):
                    continue
                r["to"] = nxt["code"]
                break
        for r in lst:
            if r["status"] == "zb":
                sub = r.get("sub_logic") or r["theme"]
                later = [
                    z for z in zts
                    if z["first"] >= r["first"]
                    and (z.get("sub_logic") or z["theme"]) == sub
                ]
                if later:
                    scored = []
                    for z in later:
                        sh = shared_tags(r, z)
                        scored.append((1 if sh else 0, z["first"], z))
                    scored.sort(key=lambda x: (-x[0], x[1]))
                    r["to"] = scored[0][2]["code"]
                else:
                    # fallback: shared concrete tags with any later zt in column
                    later_any = [z for z in zts if z["first"] >= r["first"]]
                    scored = []
                    for z in later_any:
                        sh = shared_tags(r, z)
                        if sh:
                            scored.append((len(sh), z["first"], z))
                    if scored:
                        scored.sort(key=lambda x: (-x[0], x[1]))
                        r["to"] = scored[0][2]["code"]
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
        edges.append([a, b, sanitize_label(reason), st])

    # Yellow: same-column zt chain — label by sub_logic only (never bucket paste)
    for r in recs:
        if r["status"] != "zt" or not r.get("to"):
            continue
        sub = r.get("sub_logic") or r["theme"]
        tgt = by.get(r["to"])
        if not tgt:
            continue
        tsub = tgt.get("sub_logic") or tgt["theme"]
        if sub != tsub:
            continue  # safety: no yellow across different sub_logics
        if sub in BUCKET_NAMES or any(f in sub for f in FORBIDDEN_LABEL_FRAGMENTS):
            continue
        label = f"{sub}接力"
        add(r["code"], r["to"], label, "zt")

    # Orange: zb → later same-sub_logic or shared-tag zt (never bucket-name labels)
    for r in recs:
        if r["status"] != "zb" or not r.get("to"):
            continue
        tgt = by.get(r["to"])
        if not tgt:
            continue
        sh = shared_tags(r, tgt)
        sub = r.get("sub_logic") or r["theme"]
        tsub = tgt.get("sub_logic") or tgt["theme"]
        same_sub = sub == tsub
        if sub == "个股逻辑" and tsub == "个股逻辑" and not sh:
            continue
        if sh:
            lab = f"炸板→{'/'.join(sh[:2])}"
        elif same_sub and sub not in BUCKET_NAMES and sub != "个股逻辑":
            lab = f"炸板→{sub}"
        elif same_sub:
            continue
        else:
            # cross sub_logic only when shared tags already handled above
            if tsub in BUCKET_NAMES or tsub == "个股逻辑":
                continue
            lab = f"炸板→{tsub}"
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

    grid = defaultdict(lambda: defaultdict(list))
    marks = defaultdict(lambda: defaultdict(list))  # bucket -> theme -> [(kind, rec)]
    bucket_set = set()
    for r in recs:
        fb = bucket_time(r["first"])
        bucket_set.add(fb)
        grid[fb][r["theme"]].append(r)
        lb = r.get("last_blast") or ""
        if lb:
            bb = bucket_time(lb)
            bucket_set.add(bb)
            if bb != fb:
                marks[bb][r["theme"]].append(("blast", r))
        lr = r.get("last_reseal") or ""
        if r["status"] == "zt" and lr and lr != r.get("first"):
            rb = bucket_time(lr)
            bucket_set.add(rb)
            if rb != fb:
                marks[rb][r["theme"]].append(("reseal", r))
    buckets = sorted(bucket_set)
    for b in grid:
        for th in grid[b]:
            grid[b][th].sort(key=lambda x: (x["first"], 0 if x["status"] == "zt" else 1, x["code"]))

    leg = "".join(
        f'<span class="lg"><i style="background:{bg}"></i>{th} {theme_counts[th]}</span>'
        for th, bg, fg in themes_present
    )
    plate_counts = Counter(r.get("plate") or plate_of(r["code"]) for r in recs)
    plate_leg = (
        '<span class="plate-leg" title="按 A 股代码板别">'
        f'<span class="pl"><span class="plate-main">主板</span>{plate_counts.get("主板", 0)}</span>'
        f'<span class="pl"><span class="plate-cy">创业</span>{plate_counts.get("创业", 0)}</span>'
        f'<span class="pl"><span class="plate-kc">科创</span>{plate_counts.get("科创", 0)}</span>'
    )
    if plate_counts.get("北证"):
        plate_leg += f'<span class="pl"><span class="plate-bj">北证</span>{plate_counts.get("北证", 0)}</span>'
    plate_leg += "</span>"

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
                em = card_em_html(r)
                title = f'→ {name_of[r["to"]]}' if r.get("to") and r["to"] in name_of else ""
                to = r.get("to") or ""
                plate = r.get("plate") or plate_of(r["code"])
                plate_cls = {"主板": "main", "创业": "cy", "科创": "kc", "北证": "bj"}.get(plate, "main")
                logic = logic_with_times(r)
                parts.append(
                    f'<button type="button" class="{cls}" id="s-{r["code"]}" '
                    f'data-to="{to}" data-logic="{html_esc(logic)}" '
                    f'data-name="{html_esc(r["name"])}" data-code="{r["code"]}" '
                    f'data-meta="{html_esc(r["meta"])}" data-plate="{html_esc(plate)}" '
                    f'style="--bg:{bg};--fg:{fg}" title="{html_esc(title)}">'
                    f'<b>{html_esc(r["name"])}</b>'
                    f'<span class="plate plate-{plate_cls}">{html_esc(plate)}</span>'
                    f'<i>{badge(r)}</i>{em}</button>'
                )
            for kind, r in marks[b].get(th, []):
                plate = r.get("plate") or plate_of(r["code"])
                logic = logic_with_times(r)
                if kind == "blast":
                    ts = (r.get("last_blast") or "")[:5]
                    mid = f's-{r["code"]}-blast'
                    cls = "c mk zb-mk"
                    label = f'{r["name"]} 炸{ts}'
                else:
                    ts = (r.get("last_reseal") or "")[:5]
                    mid = f's-{r["code"]}-reseal'
                    cls = "c mk hf-mk"
                    label = f'{r["name"]} 回{ts}'
                parts.append(
                    f'<button type="button" class="{cls}" id="{mid}" '
                    f'data-to="" data-logic="{html_esc(logic)}" '
                    f'data-name="{html_esc(r["name"])}" data-code="{r["code"]}" '
                    f'data-meta="{html_esc(r["meta"])}" data-plate="{html_esc(plate)}" '
                    f'style="--bg:{bg};--fg:{fg}" title="{html_esc(label)}">'
                    f'<b>{html_esc(label)}</b></button>'
                )
            cells.append(f'<td class="cell">{"".join(parts)}</td>')
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    edges_js = json.dumps(edges, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{date} 涨停时间轴</title>
<style>
{DAY_CSS}
</style></head><body>
<div class="page">
<div class="head">
{head_html(date, zt_n, zb_n, wk_n, leg, plate_leg)}
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
{FOOT_HTML}
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
    const plateTxt = el.dataset.plate ? ('板别：'+el.dataset.plate+' · ') : '';
    document.getElementById('p-meta').textContent=plateTxt+el.dataset.meta;
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
/* PAN: left/middle mouse drag pans #wrap scroll; threshold keeps card clicks */
(function(){{
  const THRESH = 5;
  let active = false;
  let panned = false;
  let sx = 0, sy = 0, sl = 0, st = 0;
  function onMove(e){{
    if(!active) return;
    const dx = e.clientX - sx;
    const dy = e.clientY - sy;
    if(!panned && (Math.abs(dx) > THRESH || Math.abs(dy) > THRESH)){{
      panned = true;
      wrap.classList.add('is-panning');
    }}
    if(panned){{
      wrap.scrollLeft = sl - dx;
      wrap.scrollTop = st - dy;
      e.preventDefault();
    }}
  }}
  function onUp(){{
    if(!active) return;
    active = false;
    wrap.classList.remove('is-panning');
    window.removeEventListener('mousemove', onMove, true);
    window.removeEventListener('mouseup', onUp, true);
    if(panned){{
      const block = (ev)=>{{
        ev.preventDefault();
        ev.stopPropagation();
        wrap.removeEventListener('click', block, true);
      }};
      wrap.addEventListener('click', block, true);
      setTimeout(()=>wrap.removeEventListener('click', block, true), 0);
    }}
  }}
  wrap.addEventListener('mousedown', (e)=>{{
    if(e.button !== 0 && e.button !== 1) return;
    if(e.target.closest && e.target.closest('a,input,textarea,select,option,.zoombar,.dlg')) return;
    active = true;
    panned = false;
    sx = e.clientX; sy = e.clientY;
    sl = wrap.scrollLeft; st = wrap.scrollTop;
    if(e.button === 1) e.preventDefault();
    window.addEventListener('mousemove', onMove, true);
    window.addEventListener('mouseup', onUp, true);
  }});
  wrap.addEventListener('dragstart', (e)=>{{ if(panned || active) e.preventDefault(); }});
}})();
</script>
</body></html>"""
    return html, zt_n, zb_n, wk_n, theme_counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-11-18", help="YYYY-MM-DD")
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
    enrich_records_blast_reseal(recs, date)
    chain_within_logic(recs)
    edges = build_edges(recs)
    html, zt_n, zb_n, wk_n, theme_counts = render_html(date, recs, edges)

    out = OUT_DIR / f"{date}-涨停时间轴复盘.html"
    audit_out = OUT_DIR / f"{date}-zt-audit.json"
    if ensure_zoom is not None:
        html = ensure_zoom(html)
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
                "sub_logic": r.get("sub_logic") or r["theme"],
                "board": r["board"],
                "plate": r.get("plate") or plate_of(r["code"]),
                "open_num": r["open_num"],
                "high_days": r["high_days"],
                "limit_type": r["limit_type"],
                "reason_type": r.get("reason_type") or "",
                "hybk": r.get("hybk") or "",
                "blast_times": list(r.get("blast_times") or []),
                "reseal_times": list(r.get("reseal_times") or []),
                "last_blast": r.get("last_blast") or "",
                "last_reseal": r.get("last_reseal") or "",
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
    opened = [r for r in recs if int(r.get("open_num") or 0) > 0]
    for r in (opened[:5] or recs[:5]):
        print(
            " sample",
            r["code"],
            r["name"],
            r["theme"],
            f"blast={r.get('last_blast')}",
            f"reseal={r.get('last_reseal')}",
            f"nB={len(r.get('blast_times') or [])}",
            r["reason"][:60],
        )
    pc = Counter(r.get("plate") or plate_of(r["code"]) for r in recs)
    print("plates", dict(pc))
    print(f"summary 炸板{zb_n} · 弱封单{wk_n} · 封板{zt_n} · 逻辑列复盘（2026-11-18韭研：国产算力/AI硬件/家电/机器人/光刻机（胶）/其他）")


if __name__ == "__main__":
    main()
