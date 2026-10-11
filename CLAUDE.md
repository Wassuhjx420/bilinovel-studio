# CLAUDE.md / Agents.md

本文档为 Claude Code 与各 AI Agent 在本代码仓库中工作时提供全局架构指引与开发规范。

## Project Overview

哔哩轻小说（`linovelib.com` / `bilinovel.com`）极速并发全自动爬虫与出版级 EPUB 电子书制作工具。
通用支持日轻（多分卷、卷首全彩画廊、人物插画卡、长章节多子分页、场景变换分隔符）与韩轻小说，支持真实 DOM 物理渲染坐标图文精准对齐、Cloudflare Turnstile 自动绕过、广告拦截过滤、多 Tab 异步并发协同、失效章节正反向自愈修复、日轻出版级标准排版（封面 $\rightarrow$ 本卷信息与简介 $\rightarrow$ 纯全彩画廊 $\rightarrow$ 正文章节）及嵌入 Calibre/Kavita 系列元数据的高保真 EPUB 打包。

## Directory & Architecture Layout

项目本体与小说产物完全解耦隔离，目录组织如下：

```
哔哩轻小说爬取/
├── launch_gui.py                      # 桌面客户端主启动器 (PyWebView / 本地 REST 桥接)
├── gui_service.py                     # GUI 服务端调度引擎与事件总线
├── runtime_env.py                     # 运行时环境感知 (只读静态资源与物理持久化存储隔离)
├── scrape_linovelib.py                # 核心爬虫与异步并发抓取流水线主入口
├── to_epub.py                         # EPUB 转换与打包引擎（集成 Calibre/Kavita 系列元数据）
├── rubbish_secret_map.py              # 站点字体反混淆字典
├── gui/                               # Vue 3 现代化毛玻璃前端交互界面
│   ├── index.html
│   ├── app.js
│   ├── styles.css
│   ├── app_icon.ico                   # Windows 原生多尺寸高保真品牌图标
│   └── app_icon.png
├── docs/images/                      # 官方文档与发布预览高清截图
├── installer.iss                      # Inno Setup 现代化极简中文安装向导编译规格
├── ChineseSimplified.isl              # Inno Setup 纯正简体中文语言包
├── start_gui.bat                      # Windows 源码一键检测与启动脚本
├── build_exe.spec                     # PyInstaller 绿色便携打包规格文件
├── build_release.bat                  # 自动化一键打包并生成 Portable.zip 与 Setup.exe 脚本
├── requirements.txt                   # 标准 Python 运行依赖清单
├── README.md                          # 官方开源说明文档（特性、排版标准、下载与运行）
├── LICENSE                            # MIT 开源许可证
├── .edge_profile/                     # 浏览器持久化 Context（包含已通过的 Cloudflare 验证状态）
├── references/                        # 站点参考 JS 脚本与分析工具
├── novels/                            # 产出小说专属目录（与项目本体代码隔离）
├── Agents.md                          # AI Agent 指南
└── CLAUDE.md                          # Claude 运行指南
```

## Dependencies

- Python 3.10+ (已在 Python 3.14 上验证)
- `playwright` (异步浏览器自动化与反爬绕过)
- `beautifulsoup4` (HTML 目录与结构解析)
- `ebooklib` (EPUB 电子书封装)
- `pywebview` (可选，原生磨砂毛玻璃桌面窗口模式)
- 本地系统 Edge 浏览器 (`channel="msedge"`) — 无需额外下载 Chromium

安装依赖：
```bash
pip install -r requirements.txt
```

## Commands & Usage

```bash
# 1. 启动现代化桌面客户端 (推荐)
python launch_gui.py
# 或 Windows 直接双击 start_gui.bat

# 2. 一键编译并打包 Windows 绿色便携 EXE 压缩包
build_release.bat

# 3. 命令行爬取指定分卷链接（自动提取小说ID与分卷ID，如第9卷）
python scrape_linovelib.py "https://www.linovelib.com/novel/3095/vol_328281.html"

# 4. 命令行爬取目录页并指定分卷序号（如第1卷）
python scrape_linovelib.py https://www.linovelib.com/novel/5131/catalog 1

# 5. 手动从已有分卷目录重新生成 EPUB
python to_epub.py novels/败北女角太多了！/第9卷 "败北女角太多了！" "第9卷" "雨森焚火"
```

## Architecture & Workflow

### 1. `scrape_linovelib.py` / `gui_service.py` — 核心爬虫与流水线

- **通用 URL 与分卷自适应解析 (`normalize_input_url` / `parse_catalog_volumes` / `gui_service._async_parse_novel`)**：
  - 支持单卷链接（如 `vol_328281.html`）、全本目录、小说主页及纯小说 ID；
  - 自动兼容桌面版容器结构（`div.volume`）与移动响应式列表（`#volumes li`），自动提取准确分卷名称与所属章节；
  - 针对公共目录规律性防爬遮蔽（如每隔 25 话出现的 `javascript:cid` 占位），完整保留章节占位，并自动从单卷专属页异步直读同步修复真实链接；
  - GUI 服务层与 CLI 流水线保持 100% 目录解析同构对齐，支持单卷 URL 直达预选并彻底杜绝调度层漏章。
- **内核级网络过滤与并发平滑流量整形架构 (`--host-resolver-rules` / `--disable-background-timer-throttling` / `Traffic Shaping`)**：
  - 采用 Chromium 原生启动参数在 C++ 网络底层直接映射广告与追踪域名（Google AdSense、Doubleclick、百度统计、CNZZ 等）至 `127.0.0.1`，彻底替代 Playwright Python 层 `ctx.route("**/*")` 路由拦截，消除每秒数百次的 CDP IPC 通信往返与网络栈阻塞；
  - 禁用 Chromium 后台标签页降频与节电机制（`--disable-background-timer-throttling`、`--disable-backgrounding-occluded-windows`、`--disable-renderer-backgrounding`），保障并发 Worker Tab 保持全速高频运行；
  - **拟人化流量整形与频控防护（Rate Limit Protection）**：并发 Worker 错峰交错启动（0.5s/1.0s），长章节同章多子分页之间注入 350~650ms 拟人微抖动，章节任务切换注入 200~450ms 微呼吸，彻底削平突发请求峰值并避开 Cloudflare Error 1015；内建 1015 毫秒级探测与 15s 智能冷静退避机制，杜绝盲目重试封禁与任务中断。
- **多 Tab 章节异步并发流水线 (`scrape_volume_async`)**：
  - 基于 Playwright 原生 `async/await` 异步事件驱动架构；
  - 维持 3 个协同浏览器 Tab Worker 并发消费章节任务队列，提速数倍。
- **失效章节正反向递归自愈修复 (`repair_volume_chapters`)**：
  - 针对版权下架或残缺目录中遗留的 `javascript:cid` 失效章节，算法自动向后寻找最近有效章节提取“上一页”反向推导，或向前寻找有效章节末尾提取“下一页”正向推导，实现残缺目录自动修复双重兜底。

- **反爬防御绕过 & 蜜罐定时器高速穿透 (`wait_for_turnstile` / `__hasObfuscationTimer`)**：
  - 注入 `navigator.webdriver = false` 与平台伪装代码；
  - 拦截并穿透源站 2000ms 恶意延迟混淆定时器（`setTimeout(_0x..., 2000)`），将其无损压缩至 10ms 立即执行，让 `matrix(0, 0, 0, 0, 0, 0)` / `scale(0)` 蜜罐段落瞬时就绪并隐藏；
  - 采用事件驱动自适应探测替代盲目轮询，对含蜜罐章节在混淆生效瞬间（~50ms）立即放行，对无蜜罐/纯插图页面毫秒级快速通过，实现 100% 字节级排版保真与 10~20 倍极致抓取提速；
  - 采用 DOM 内容探针与 Turnstile 验证框坐标探测自动拟人化点击，配合 `.edge_profile` 会话持久化。
- **长章节多子页递归合并 (`scrape_chapter_with_pagination`)**：
  - 多源冗余聚合 `ReadParams.url_next`（移动版）、`window.nextpage`（桌面版）以及 DOM 中的 `<a>下一页</a>` 链接；
  - 自动检测并识别同章节子分页（如 `328283.html` -> `328283_2.html` -> ... -> `328283_7.html`），自动循环抓取并拼接。
- **DOM 源头过滤与物理渲染坐标排序 (`extract_subpage_items`)**：
  - 抓取阶段直接过滤 `#hidden-images`、`.dag`、`show-more-images` 等折叠剧透容器，彻底杜绝折叠黑白图污染卷首彩页；
  - 若页面包含插图，自动触发 `window.scrollTo` 激活 `lazysizes` 懒加载与图片预取；
  - 严格按 DOM 自然阅读时序与物理位置保序，同时在 `isElementVisible` 中解除对 `<img>` 标签的物理尺寸限制（`!isImg && rect.height === 0`），彻底杜绝冷网络环境下图片二进制下载延迟导致的误判过滤；
  - **插图差集对账与自愈补全（DOM Image Reconciliation）**：在抽取末尾扫描容器内所有真实非折叠合法插图节点，与捕获结果执行差集对账并自动补全，彻底消灭任何漏图盲区。
- **场景变换分隔符精准捕获 (`extract_subpage_items`)**：
  - 深度识别 `<center>` 标签、`<hr>` 标签、DOM `<br>` 节点、空段落 `<p>` 以及单行符号段落（如 `◇`, `◆`, `* * *`, `***`, `◇◇◇`, `——` 等）；
  - 对有符号的场景分隔输出标准的 `[场景分隔: {symbol}]`，对纯空行转场输出 `[场景分隔]`；在完整版 TXT 中以自然空行呈现，在 EPUB 中渲染为专属的 `<p class="scene-break blank">&#160;</p>` 优雅转场留白，100% 还原源站与出版级实体书视觉节奏。
- **产物分级存储与全生命周期插图审计台账**：
  - 所有输出保存至 `novels/<书名>/<分卷名>/` 目录；
  - **全卷插图台账审计（Illustration Audit Ledger）**：Worker 实时输出各章节插图捕获日志；打包前自动汇总输出“卷首彩插 + 章节内嵌黑白插图”分布台账，并在下载完成后执行 100% 双向校对与失败显式告警，彻底免除人工手动比对原文的负担；
  - 章节内容抓取完成后并发异步下载与校对全卷插图，自动将卷首全彩插图 (`插图_1.jpg`) 设定为电子书主封面 (`封面.jpg`)；若开启 `cleanup_temp`（自动清理抓取临时缓存）则在 EPUB 封装完成后自动清理外层 `插图/` 散装目录与独立封面文件，释放磁盘空间。
- **集中容灾二次补救通道与分层重试体系 (`extract_subpage_items` / `scrape_chapter_with_pagination` / `failed_targets rescue`)**：
  - 子分页与导航加载内置 3 级指数退避重试，杜绝单次网络抖动导致章节提前终止；
  - 并发工作线程执行完毕后，自动扫描缺失或内容为空的异常章节，启动专用独立单通道二次补救，杜绝并发请求限制导致的偶发丢章；
  - 电子书生成前执行全卷完整性校验，若有无法挽回的异常章节，自动注入标准格式的醒目警告占位框，拒绝静默丢失内容。

### 2. `to_epub.py` — EPUB 电子书生成引擎

- **日轻出版级标准排版流程**：
  - **第 1 页（全屏主封面 `cover.xhtml`）**：作为 `spine` 首位，在阅读器翻开第一面即呈现全屏自适应高清封面，并从 `spine` 中剔除 `nav`（杜绝出现难看的纯文本目录列表第一面）；
  - **第 2 页（彩页 `color.xhtml`）**：整合本卷制作与录入信息、居中分隔线、内容简介引用框及纯全彩原画/人物介绍卡画廊；自动过滤卷首制作信息中的场景分隔标记，将简介内部的空行转场渲染为优雅留白，并将作者/画师简介格式化为居中二级标题；
  - **第 3 页起（正文章节）**：序章及后续故事章节，内嵌专属黑白插图与场景分隔符。
- **排版优化**：正文首行缩进 2 字符、自然段间距；
- **场景分隔符美化**：解析 `[场景分隔: {symbol}]`、无符号 `[场景分隔]` 及独立符号行，渲染为精美居中字距扩展的 `<p class="scene-break"><span>{symbol}</span></p>` 或纯空行自适应留白 `<p class="scene-break blank">&#160;</p>` 节点；
- **图文混排与多看手势缩放支持**：
  - 精准识别 `[插图: 文件名.jpg]` 标记并转为自适应宽度的 XHTML `<img>` 标签；
  - 封面大图、卷首彩页及正文插图容器全量适配注入单图交互规范 `duokan-image-single` 扩展类名（杜绝使用多看私有未初始化的 `duokan-image-gallery` 容器避免导致彩图隐藏），原生激活多看阅读（小米阅读）等移动阅读器的点击全屏放大、双指手势缩放与原图保存特性，同时 100% 保持对 Apple Books、微信读书、KOReader 等标准阅读器的无损兼容；
- **Calibre 与 Kavita 媒体库系列元数据集成**：
  - 自动从卷名提取卷号与系列名；
  - 写入 `calibre:series`、`calibre:series_index` 以及 EPUB 3 `belongs-to-collection`（Collection Type / Group Position）规范系列标签，支持 Calibre 与 Kavita 媒体库分卷自动归类；
- **元数据封装**：自动绑定主封面（Cover Page）、目录导航（NCX & Nav）、作者信息与 UUID。

## Anti-Patterns & Best Practices

- **禁止直接使用 `requests` / `cloudscraper`**：目标站点部署了 Cloudflare 5秒盾，必须使用 Playwright 持久化 Context (`.edge_profile`)。
- **禁止在 document 请求上使用路由代理 (`route.fetch`)**：内部 fetch 不具备完整浏览器 TLS 指纹，会触发 Cloudflare 验证页并导致文本被截断；统一使用 `page.add_init_script` 在客户端阻断跳转。
- **必须处理章节多子页（Pagination）**：长章节由 2~10+ 个子页组成（如 `328283.html` + `328283_2.html` ~ `328283_7.html`），必须使用包含 `window.nextpage`、`ReadParams.url_next` 及 DOM `<a>下一页</a>` 的多源探测算法。
- **保持 CLAUDE.md 与 Agents.md 100% 内容一致**：任何针对项目规范与文档的修改必须同时写入两个文件。
