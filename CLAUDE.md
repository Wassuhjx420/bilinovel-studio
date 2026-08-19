# CLAUDE.md / Agents.md

本文档为 Claude Code 与各 AI Agent 在本代码仓库中工作时提供全局架构指引与开发规范。

## Project Overview

哔哩轻小说（`linovelib.com` / `bilinovel.com`）全自动爬虫与 EPUB 电子书制作工具。
通用支持日轻（多分卷、卷首全彩画廊、人物插画卡、长章节多子分页、场景变换分隔符）与韩轻小说，支持真实 DOM 物理渲染坐标图文精准对齐、Cloudflare Turnstile 自动绕过、多子分页自动递归合并及高保真 EPUB 打包。

## Directory & Architecture Layout

项目本体与小说产物完全解耦隔离，目录组织如下：

```
哔哩轻小说爬取/
├── scrape_linovelib.py                # 核心爬虫与抓取流水线主入口
├── to_epub.py                         # EPUB 转换与打包引擎
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
- `playwright` (浏览器自动化与反爬绕过)
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
- **反爬防御绕过 & 域名规范化**：
  - 使用 `page.add_init_script` 注入 `navigator.platform = 'MacIntel'` 并拦截 `window.location.replace`，彻底阻断站点针对 Windows / zh-cn 用户的强制失效跳转，保留原生 Edge 真实的 TLS 与 HTTP/2 协议栈；
  - 集成 Turnstile 验证框坐标探测与自动物理点击机制（`wait_for_turnstile`），结合 `.edge_profile` 自动持久化通行凭据。
- **长章节多子页递归合并 (`scrape_chapter_with_pagination`)**：
  - 多源冗余聚合 `ReadParams.url_next`（移动版）、`window.nextpage`（桌面版）以及 DOM 中的 `<a>下一页</a>` 链接；
  - 自动检测并识别同章节子分页（如 `328283.html` -> `328283_2.html` -> ... -> `328283_7.html`），自动循环抓取并将各子页段落去重后依序拼接，直到进入下一章节。
- **场景变换分隔符精准捕获 (`extract_subpage_items`)**：
  - 深度识别 `<center>` 标签、`<hr>` 标签及单行符号段落（如 `◇`, `◆`, `* * *`, `***`, `◇◇◇`, `——` 等）；
  - 输出为标准的 `[场景分隔: {symbol}]` 语法标记，按真实 Y 轴绝对坐标与正文精准对齐。
- **DOM 物理渲染坐标排序 (`extract_subpage_items`)**：
  - 执行 `window.scrollTo(0, document.body.scrollHeight)` 触发懒加载渲染；
  - 提取正文 `p`（过滤 `rect.height <= 0` 隐藏混淆副本、广告与 `內容加載失敗` 伪占位符）、插图 `img`（过滤加载骨架）及场景分割线；
  - 严格按 `rect.top + scrollY` 真实 Y 轴绝对坐标升序排序，实现插图与分隔符在正文中的 100% 精确锚定。
- **产物分级存储与插图管理**：
  - 所有输出保存至 `novels/<书名>/<分卷名>/` 目录；
  - 针对全彩画廊原画与正文黑白插图增加 3 轮重试下载机制，自动将卷首全彩插图 (`插图_1.jpg`) 设定为电子书主封面 (`封面.jpg`)。

### 2. `to_epub.py` — EPUB 电子书生成引擎

- **章节解析**：按 `={20,}` 分隔符切分章节标题与正文；
- **排版优化**：正文首行缩进 2 字符、自然段间距；
- **场景分隔符美化**：解析 `[场景分隔: {symbol}]` 及独立符号行，渲染为精美居中字距扩展的 `<p class="scene-break"><span>{symbol}</span></p>` 节点；
- **图文混排**：精准识别 `[插图: 文件名.jpg]` 标记并转为自适应宽度的 XHTML `<img>` 标签；
- **元数据封装**：自动绑定主封面（Cover Page）、目录导航（NCX & Nav）、作者信息与 UUID。

## Anti-Patterns & Best Practices

- **禁止直接使用 `requests` / `cloudscraper`**：目标站点部署了 Cloudflare 5秒盾，必须使用 Playwright 持久化 Context (`.edge_profile`)。
- **禁止在 document 请求上使用路由代理 (`route.fetch`)**：内部 fetch 不具备完整浏览器 TLS 指纹，会触发 Cloudflare 验证页并导致文本被截断；统一使用 `page.add_init_script` 在客户端阻断跳转。
- **必须处理章节多子页（Pagination）**：长章节由 2~10+ 个子页组成（如 `328283.html` + `328283_2.html` ~ `328283_7.html`），必须使用包含 `window.nextpage`、`ReadParams.url_next` 及 DOM `<a>下一页</a>` 的多源探测算法。
- **必须使用 `rect.height > 0` 过滤**：页面 DOM 中常包含大量隐藏混淆段落，直接选择所有 `<p>` 会导致正文重复或包含垃圾标记。
- **不要使用 `wait_until="networkidle"`**：由于广告脚本持续轮询，`networkidle` 容易超时；应使用 `domcontentloaded` + `window.scrollTo` + `wait_for_timeout`。
