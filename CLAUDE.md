# CLAUDE.md / Agents.md

本文档为 Claude Code 与各 AI Agent 在本代码仓库中工作时提供全局架构指引与开发规范。

## Project Overview

哔哩轻小说（`linovelib.com` / `bilinovel.com`）极速并发全自动爬虫与 EPUB 电子书制作工具。
通用支持日轻（多分卷、卷首全彩画廊、人物插画卡、长章节多子分页、场景变换分隔符）与韩轻小说，支持真实 DOM 物理渲染坐标图文精准对齐、Cloudflare Turnstile 自动绕过、广告拦截过滤、多 Tab 异步并发协同、失效章节正反向自愈修复及嵌入 Calibre/Kavita 系列元数据的高保真 EPUB 打包。

## Directory & Architecture Layout

项目本体与小说产物完全解耦隔离，目录组织如下：

```
哔哩轻小说爬取/
├── scrape_linovelib.py                # 核心爬虫与异步并发抓取流水线主入口
├── to_epub.py                         # EPUB 转换与打包引擎（集成 Calibre/Kavita 系列元数据）
├── .edge_profile/                     # 浏览器持久化 Context（包含已通过的 Cloudflare 验证状态）
├── references/                        # 站点参考 JS 脚本与分析工具
│   ├── chapterlog.js
│   ├── common.js
│   ├── readtools.js
│   └── zation.js
├── novels/                            # 产出小说专属目录（与项目本体代码隔离）
│   └── 败北女角太多了！/                # 示例：日轻多分卷、画廊与多子分页
│       └── 第9卷/
│           ├── 封面.jpg               # 卷首提取的高清全彩封面
│           ├── 败北女角太多了！_第9卷.epub
│           ├── 败北女角太多了！_第9卷_完整版.txt
│           └── 插图/                  # 28 张高清插图（18张卷首原画/角色卡 + 10张章节黑白插图）
├── Agents.md                          # AI Agent 指南
└── CLAUDE.md                          # Claude 运行指南
```

## Dependencies

- Python 3.10+ (已在 Python 3.14 上验证)
- `playwright` (异步浏览器自动化与反爬绕过)
- `beautifulsoup4` (HTML 目录与结构解析)
- `ebooklib` (EPUB 电子书封装)
- 本地系统 Edge 浏览器 (`channel="msedge"`) — 无需额外下载 Chromium

安装依赖：
```bash
pip install playwright beautifulsoup4 ebooklib
```

## Commands & Usage

```bash
# 1. 爬取指定小说的单卷链接（自动提取小说ID与分卷ID，如第9卷）
python scrape_linovelib.py "https://www.linovelib.com/novel/3095/vol_328281.html"

# 2. 爬取目录页并指定分卷序号（如第1卷）
python scrape_linovelib.py https://www.linovelib.com/novel/5131/catalog 1

# 3. 指定自定义小说名
python scrape_linovelib.py https://www.linovelib.com/novel/5131/catalog 1 "挚友的女朋友喜欢我"

# 4. 手动从已有分卷目录重新生成 EPUB
python to_epub.py novels/败北女角太多了！/第9卷 "败北女角太多了！" "第9卷" "雨森焚火"
```

## Architecture & Workflow

### 1. `scrape_linovelib.py` — 核心爬虫与流水线

- **通用 URL 与分卷自适应解析 (`normalize_input_url` / `parse_catalog_volumes`)**：
  - 支持单卷链接（如 `vol_328281.html`）、全本目录、小说主页及纯小说 ID；
  - 自动兼容桌面版容器结构（`div.volume`）与移动响应式列表（`#volumes li`），自动提取准确分卷名称与所属章节。
- **广告与追踪请求精准拦截 (`route_intercept`)**：
  - 拦截 Google AdSense、Doubleclick、百度统计、CNZZ 等广告与第三方分析请求，大幅节省网络带宽与渲染等待。
- **多 Tab 章节异步并发流水线 (`scrape_volume_async`)**：
  - 基于 Playwright 原生 `async/await` 异步事件驱动架构；
  - 维持 3 个协同浏览器 Tab Worker 并发消费章节任务队列，提速数倍。
- **失效章节正反向递归自愈修复 (`repair_volume_chapters`)**：
  - 针对版权下架或残缺目录中出现的 `javascript:cid` 失效章节，算法自动向后寻找最近有效章节提取“上一页”反向推导，或向前寻找有效章节末尾提取“下一页”正向推导，实现残缺目录自动修复。
- **反爬防御绕过 & 智能 Turnstile 穿透**：
  - 注入 `navigator.webdriver = false` 与平台伪装代码；
  - 采用 DOM 内容探针与 Turnstile 验证框坐标探测自动拟人化点击，配合 `.edge_profile` 会话持久化。
- **长章节多子页递归合并 (`scrape_chapter_with_pagination`)**：
  - 多源冗余聚合 `ReadParams.url_next`（移动版）、`window.nextpage`（桌面版）以及 DOM 中的 `<a>下一页</a>` 链接；
  - 自动检测并识别同章节子分页（如 `328283.html` -> `328283_2.html` -> ... -> `328283_7.html`），自动循环抓取并拼接。
- **场景变换分隔符精准捕获 (`extract_subpage_items`)**：
  - 深度识别 `<center>` 标签、`<hr>` 标签及单行符号段落（如 `◇`, `◆`, `* * *`, `***`, `◇◇◇`, `——` 等）；
  - 输出为标准的 `[场景分隔: {symbol}]` 语法标记，按真实 Y 轴绝对坐标与正文精准对齐。
- **DOM 物理渲染坐标排序 (`extract_subpage_items`)**：
  - 执行 `window.scrollTo(0, document.body.scrollHeight)` 触发懒加载渲染；
  - 严格按 `rect.top + scrollY` 真实 Y 轴绝对坐标升序排序，实现插图与分隔符在正文中的 100% 精确锚定。
- **产物分级存储与插图管理**：
  - 所有输出保存至 `novels/<书名>/<分卷名>/` 目录；
  - 章节内容抓取完成后并发异步下载与校对全卷插图，自动将卷首全彩插图 (`插图_1.jpg`) 设定为电子书主封面 (`封面.jpg`)。

### 2. `to_epub.py` — EPUB 电子书生成引擎

- **章节解析**：按 `={20,}` 分隔符切分章节标题与正文；
- **排版优化**：正文首行缩进 2 字符、自然段间距；
- **场景分隔符美化**：解析 `[场景分隔: {symbol}]` 及独立符号行，渲染为精美居中字距扩展的 `<p class="scene-break"><span>{symbol}</span></p>` 节点；
- **图文混排**：精准识别 `[插图: 文件名.jpg]` 标记并转为自适应宽度的 XHTML `<img>` 标签；
- **Calibre 与 Kavita 媒体库系列元数据集成**：
  - 自动从卷名提取卷号与系列名；
  - 写入 `calibre:series`、`calibre:series_index` 以及 EPUB 3 `belongs-to-collection`（Collection Type / Group Position）规范系列标签，支持 Calibre 与 Kavita 媒体库分卷自动归类；
- **元数据封装**：自动绑定主封面（Cover Page）、目录导航（NCX & Nav）、作者信息与 UUID。

## Anti-Patterns & Best Practices

- **禁止直接使用 `requests` / `cloudscraper`**：目标站点部署了 Cloudflare 5秒盾，必须使用 Playwright 持久化 Context (`.edge_profile`)。
- **禁止在 document 请求上使用路由代理 (`route.fetch`)**：内部 fetch 不具备完整浏览器 TLS 指纹，会触发 Cloudflare 验证页并导致文本被截断；统一使用 `page.add_init_script` 在客户端阻断跳转。
- **必须处理章节多子页（Pagination）**：长章节由 2~10+ 个子页组成（如 `328283.html` + `328283_2.html` ~ `328283_7.html`），必须使用包含 `window.nextpage`、`ReadParams.url_next` 及 DOM `<a>下一页</a>` 的多源探测算法。
