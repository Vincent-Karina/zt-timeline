# 涨停时间轴复盘网站

- 打开首页：双击 `index.html`，或在目录下执行 `python3 -m http.server 8765` 后浏览器访问 `http://127.0.0.1:8765/`
- 每日页：`days/YYYY-MM-DD.html`
- 发布新一天：`python3 tools/publish_day.py --date YYYY-MM-DD --html /path/to/file.html --summary "一句话摘要"`
