"""Inject the day-page matrix zoom controls into a self-contained HTML file."""
from __future__ import annotations

import re
from pathlib import Path

OLD_DRAW_SIZE = """  const W = Math.max(stage.scrollWidth, stage.offsetWidth);
  const H = Math.max(stage.scrollHeight, stage.offsetHeight);"""

NEW_DRAW_SIZE = """  const table = document.getElementById('grid');
  const W = table.offsetWidth;
  const H = table.offsetHeight;"""

ZOOM_CSS = """/* ZOOM_CSS_START */
.zoombar{display:flex;align-items:center;gap:8px;margin-top:8px;padding-top:6px;border-top:1px solid #333;flex-wrap:wrap}
.zoombar button{appearance:none;background:#ff0;color:#000;border:2px solid #fff;border-radius:6px;font:inherit;font-weight:900;font-size:14px;cursor:pointer;min-height:36px;padding:4px 12px;line-height:1.1}
.zoombar button:hover{filter:brightness(1.06)}
.zoombar button:disabled{opacity:.35;cursor:default;filter:none}
.zoombar button:focus-visible{outline:2px solid #0ff;outline-offset:2px}
#zoom-pct{min-width:64px;text-align:center;font-weight:900;color:#ff0;font-size:16px;font-variant-numeric:tabular-nums;background:#000;border:1px solid #888;border-radius:6px;padding:6px 8px}
.zoom-hint{color:#ccc;font-size:11px;font-weight:600}
#stage.is-scaled{min-width:0}
#stage.is-scaled > table{min-width:max-content;width:max-content}
.wrap{touch-action:pan-x pan-y}
/* ZOOM_CSS_END */"""

ZOOM_BAR = """<!-- ZOOM_BAR_START -->
<div class="zoombar" id="zoombar">
  <button type="button" id="zoom-out" title="缩小">－ 缩小</button>
  <span id="zoom-pct" aria-live="polite" title="当前缩放比例">100%</span>
  <button type="button" id="zoom-in" title="放大">＋ 放大</button>
  <button type="button" id="zoom-reset" title="回到默认比例">重置</button>
  <span class="zoom-hint">默认按视口宽度适配 · Ctrl/⌘+滚轮缩放 · 按住拖动平移</span>
</div>
<!-- ZOOM_BAR_END -->"""

ZOOM_JS = r"""/* ZOOM_JS_START */
/* 默认比例：把矩阵自然宽度缩进视口（不超过 100%，不低于 20%）。
   竖向放不下时预留滚动条宽度，避免重置后比例跳动；若仍溢出则再减 1%。
   重置回到该比例。放大/缩小对齐到 10% 刻度。Ctrl/⌘+滚轮以光标为中心缩放。范围 20%–200%。
   缩放用 CSS zoom 作用在 #stage 上，表格与 SVG 箭头同一层一起变，吸顶表头仍相对滚动区固定。 */
(function(){
  const MIN_Z = 0.2, MAX_Z = 2;
  const table = document.getElementById('grid');
  const pctEl = document.getElementById('zoom-pct');
  const btnIn = document.getElementById('zoom-in');
  const btnOut = document.getElementById('zoom-out');
  const btnReset = document.getElementById('zoom-reset');
  let zoom = 1;
  let userZoomed = false;
  let fitting = false;

  function roundZ(z){
    return Math.min(MAX_Z, Math.max(MIN_Z, Math.round(z * 100) / 100));
  }
  function padBox(){
    const cs = getComputedStyle(wrap);
    return {
      l: parseFloat(cs.paddingLeft) || 0,
      t: parseFloat(cs.paddingTop) || 0,
      x: (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0)
    };
  }
  function applyScaleClass(){
    stage.classList.toggle('is-scaled', Math.abs(zoom - 1) > 0.001);
  }
  function naturalSize(){
    const prevZoom = stage.style.zoom;
    const scaled = stage.classList.contains('is-scaled');
    stage.style.zoom = '1';
    stage.classList.add('is-scaled');
    const size = {w: table.offsetWidth, h: table.offsetHeight};
    stage.style.zoom = prevZoom;
    stage.classList.toggle('is-scaled', scaled);
    return size;
  }
  function defaultZoom(){
    const size = naturalSize();
    if (!size.w) return 1;
    const cs = getComputedStyle(wrap);
    const padX = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0);
    const padY = (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
    const gutter = Math.max(0, wrap.offsetWidth - wrap.clientWidth);
    const base = wrap.clientWidth + gutter;
    let avail = Math.max(1, base - padX - 2);
    let fit = Math.min(1, avail / size.w);
    if (size.h * fit + padY > wrap.clientHeight + 1) {
      avail = Math.max(1, avail - (gutter > 2 ? gutter : 16));
      fit = Math.min(1, avail / size.w);
    }
    const z = Math.floor(fit * 100 + 1e-6) / 100;
    return Math.min(MAX_Z, Math.max(MIN_Z, z));
  }
  function applyDefault(resetScroll){
    if (fitting) return;
    fitting = true;
    userZoomed = false;
    setZoom(defaultZoom(), null, false);
    let guard = 0;
    while (wrap.scrollWidth > wrap.clientWidth + 1 && zoom > MIN_Z + 0.001 && guard < 8) {
      setZoom((Math.round(zoom * 100) - 1) / 100, null, false);
      guard++;
    }
    if (resetScroll) {
      wrap.scrollLeft = 0;
      wrap.scrollTop = 0;
    }
    userZoomed = false;
    fitting = false;
  }
  function updateUi(){
    pctEl.textContent = Math.round(zoom * 100) + '%';
    btnOut.disabled = zoom <= MIN_Z + 0.001;
    btnIn.disabled = zoom >= MAX_Z - 0.001;
  }
  function setZoom(next, anchor, fromUser){
    const prev = zoom || 1;
    next = roundZ(next);
    const rect = wrap.getBoundingClientRect();
    const vx = anchor ? (anchor.clientX - rect.left) : (wrap.clientWidth / 2);
    const vy = anchor ? (anchor.clientY - rect.top) : (wrap.clientHeight / 2);
    const pad = padBox();
    const localX = (wrap.scrollLeft + vx - pad.l) / prev;
    const localY = (wrap.scrollTop + vy - pad.t) / prev;
    zoom = next;
    if (fromUser) userZoomed = true;
    stage.style.zoom = String(zoom);
    applyScaleClass();
    draw(typeof hi === 'undefined' ? null : hi);
    const maxL = Math.max(0, wrap.scrollWidth - wrap.clientWidth);
    const maxT = Math.max(0, wrap.scrollHeight - wrap.clientHeight);
    wrap.scrollLeft = Math.min(maxL, Math.max(0, localX * zoom + pad.l - vx));
    wrap.scrollTop = Math.min(maxT, Math.max(0, localY * zoom + pad.t - vy));
    updateUi();
  }

  function stepZoom(dir){
    const pct = Math.round(zoom * 100);
    const nextPct = dir > 0
      ? Math.min(MAX_Z * 100, Math.ceil((pct + 1) / 10) * 10)
      : Math.max(MIN_Z * 100, Math.floor((pct - 1) / 10) * 10);
    setZoom(nextPct / 100, null, true);
  }
  btnOut.addEventListener('click', function(){ stepZoom(-1); });
  btnIn.addEventListener('click', function(){ stepZoom(1); });
  btnReset.addEventListener('click', function(){ applyDefault(true); });

  document.addEventListener('wheel', function(e){
    if (!e.ctrlKey && !e.metaKey) return;
    const mask = document.getElementById('mask');
    if (mask && mask.classList.contains('on')) return;
    e.preventDefault();
    let dy = e.deltaY;
    if (e.deltaMode === 1) dy *= 16;
    else if (e.deltaMode === 2) dy *= wrap.clientHeight || 800;
    const factor = Math.exp(-dy * 0.0015);
    setZoom(zoom * factor, {clientX: e.clientX, clientY: e.clientY}, true);
  }, {passive: false, capture: true});

  let pinch = null;
  function pinchDist(touches){
    const dx = touches[0].clientX - touches[1].clientX;
    const dy = touches[0].clientY - touches[1].clientY;
    return Math.hypot(dx, dy) || 1;
  }
  wrap.addEventListener('touchstart', function(e){
    if (e.touches.length === 2) pinch = {d: pinchDist(e.touches), z: zoom};
  }, {passive: true});
  wrap.addEventListener('touchmove', function(e){
    if (!(e.touches.length === 2 && pinch)) return;
    e.preventDefault();
    const d = pinchDist(e.touches);
    setZoom(pinch.z * (d / pinch.d), {
      clientX: (e.touches[0].clientX + e.touches[1].clientX) / 2,
      clientY: (e.touches[0].clientY + e.touches[1].clientY) / 2
    }, true);
  }, {passive: false});
  wrap.addEventListener('touchend', function(){ pinch = null; }, {passive: true});
  wrap.addEventListener('touchcancel', function(){ pinch = null; }, {passive: true});

  window.addEventListener('resize', function(){
    if (!userZoomed) applyDefault(false);
  });

  applyDefault(false);
})();
/* ZOOM_JS_END */"""


def _strip(html: str) -> str:
    html = re.sub(r"\n*/\* ZOOM_CSS_START \*/.*?/\* ZOOM_CSS_END \*/\n*", "\n", html, count=1, flags=re.S)
    html = re.sub(r"\n*<!-- ZOOM_BAR_START -->.*?<!-- ZOOM_BAR_END -->\n*", "\n", html, count=1, flags=re.S)
    html = re.sub(r"\n*/\* ZOOM_JS_START \*/.*?/\* ZOOM_JS_END \*/\n*", "\n", html, count=1, flags=re.S)
    return html


def ensure_zoom(html: str) -> str:
    """Return day HTML with matrix zoom CSS, toolbar, and script installed."""
    html = _strip(html)
    for token in ('id="stage"', 'id="wrap"', 'id="grid"', "function draw"):
        if token not in html:
            raise SystemExit(f"day html missing {token}; cannot add zoom")
    if OLD_DRAW_SIZE in html:
        html = html.replace(OLD_DRAW_SIZE, NEW_DRAW_SIZE, 1)
    elif "document.getElementById('grid')" not in html.split("function draw", 1)[-1][:500]:
        raise SystemExit("draw() size measurement not found; cannot keep arrows aligned while zooming")
    if "</style>" not in html or "</script>" not in html:
        raise SystemExit("day html missing style/script; cannot add zoom")

    html = html.replace("</style>", "\n" + ZOOM_CSS + "\n</style>", 1)
    key = re.search(r'<div class="key">.*?</div>', html, flags=re.S)
    if key:
        html = html[: key.end()] + "\n" + ZOOM_BAR + html[key.end() :]
    else:
        html = html.replace('<div class="wrap"', ZOOM_BAR + '\n<div class="wrap"', 1)

    idx = html.rfind("</script>")
    if idx < 0:
        raise SystemExit("day html missing </script>")
    html = html[:idx] + "\n" + ZOOM_JS + "\n" + html[idx:]
    return html


def main() -> None:
    import sys

    if len(sys.argv) < 2:
        raise SystemExit("usage: zoom_inject.py days/YYYY-MM-DD.html [...]")
    for arg in sys.argv[1:]:
        path = Path(arg)
        path.write_text(ensure_zoom(path.read_text(encoding="utf-8")), encoding="utf-8")
        print(f"zoomed {path}")


if __name__ == "__main__":
    main()
