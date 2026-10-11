<div align="center">

# BiliNovel Studio Pro
### 哔哩轻小说极速爬虫 & 精排 EPUB 制作工作台

*极速多 Tab 异步并发抓取 · 精排日轻/韩轻 EPUB 封装 · 现代化桌面客户端*

[![Platform](https://img.shields.io/badge/Platform-Windows-blue.svg?style=flat-square&logo=windows)](https://github.com)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Playwright](https://img.shields.io/badge/Browser-Microsoft%20Edge-0078D7.svg?style=flat-square&logo=microsoftedge&logoColor=white)](https://www.microsoft.com/edge)
[![License](https://img.shields.io/badge/License-MIT-green.svg?style=flat-square)](LICENSE)
[![Release](https://img.shields.io/badge/Release-v1.0.0-orange.svg?style=flat-square)](https://github.com)

</div>

---

> [!WARNING]
> ### 免责声明
> 1. 本项目仅供 Python 自动化测试、Playwright 浏览器技术学习以及个人离线阅读备份研究使用。
> 2. 小说文本内容、插图、插画及相关素材版权均归原作者、插画师及原轻小说出版方所有。
> 3. 严禁将本项目、编译产物及其生成的任何电子书资源用于商业出版、牟利或非法传播。
> 4. 使用者因违反版权法或站点服务条款所引发的任何纠纷与法律责任，均由使用者自行承担，与本项目开发者无关。

---

## 界面预览与实机排版效果

### 1. 桌面客户端操作界面

#### 小说解析工作台
支持输入小说 ID、目录链接或单卷直达链接，自动解析全部分卷结构，提供分卷封面预览、一键全选/反选与批量队列下载。

![小说解析工作台](docs/images/preview_workbench.png)

#### 任务队列与并发 Worker 实时监控
支持 3 个异步 Worker Tab 错峰并发调度，实时展示网络速率、剩余预估时间、分卷进度及控制台日志面板。

![任务队列与并发监控](docs/images/preview_monitor.png)

### 2. 多看阅读器
适配多看阅读，原生手势缩放与日轻装帧规范，包括全屏自适应封面、规范目录结构导航（彩页/序章/正文章节独立编排）以及卷首纯全彩原画画廊。

<div align="center">

| 目录结构与章节导航 | 全彩画廊 |
| :---: | :---: |
| <img src="docs/images/reader_catalog.jpg" width="380" alt="多看阅读器目录结构" /> | <img src="docs/images/reader_color_gallery.jpg" width="380" alt="多看阅读器全彩画廊" /> |

</div>

---

## 核心特性
* **极速异步多 Tab 并发流水线**
  * 基于 Playwright 异步事件驱动架构，多浏览器标签页协同消费章节任务；
  * 内置**拟人化流量整形与微抖动（Traffic Shaping）**，彻底削平请求尖峰，智能绕过 Cloudflare Error 1015 限频保护。
* **精排EPUB**
  * 遵循日轻实体书装帧顺序：**封面 $\rightarrow$ 本卷制作信息与内容简介 $\rightarrow$ 纯全彩原画/人物卡画廊 $\rightarrow$ 正文章节**；
  * 自动剥离卷首彩页在正文中的重复，正文内嵌对应黑白插图；
  * 适配 **多看阅读** 手势双指缩放与全屏高清查看（`duokan-image-single`），同时兼容 Apple Books、微信读书、KOReader 等各大主流阅读器。
* **内核级反爬绕过与蜜罐穿透**
  * Chromium C++ 网络层重定向广告与追踪域名至本地，零 CDP IPC 往返开销；
  * 穿透源站 2000ms 延迟混淆定时器，自适应放行蜜罐段落；
  * 支持 Cloudflare Turnstile 验证框坐标探测与会话持久化保护。
* **失效章节正反向递归自愈修复**
  * 面对版权下架或残缺目录中遗留的占位链接，算法自动向前/向后提取临近有效章节并双向推导，消灭漏章。
* **Calibre & Kavita 媒体库系列元数据集成**
  * 自动从分卷标题提取卷号与系列名，写入 `calibre:series`、`calibre:series_index` 与 EPUB 3 `belongs-to-collection` 标签，导入媒体库即可自动分卷归类。

---

## 下载与开箱即用 (Windows 绿色版 / 安装版)

无需配置 Python 编程环境，项目提供了开箱即用的 Windows 发布版本：

前往 **[GitHub Releases 页面](../../releases)** 下载最新版本：

| 版本类型 | 文件名 | 说明 |
| :--- | :--- | :--- |
| **安装版** | `BiliNovelStudio_Setup_v1.0.0.exe` | 两步安装向导 |
| **绿色免安装便携版** | `BiliNovelStudio_Portable.zip` | 解压至任意文件夹即可直接运行 |

> **系统要求**：Windows 10 / Windows 11（系统自带 Microsoft Edge 浏览器即可，无需额外下载配置内核）。

---

## 开发者源码运行指引

如果你希望直接运行项目源码或参与二次开发：

### 1. 环境准备
* **Python**：3.10 或更高版本
* **操作系统**：Windows 10 / 11

### 2. 克隆仓库与安装依赖
```bash
# 克隆仓库
git clone https://github.com/your-username/bilinovel-studio.git
cd bilinovel-studio

# 安装核心依赖
pip install -r requirements.txt
```

### 3. 一键启动桌面客户端
```bash
# 启动桌面客户端
python launch_gui.py

# 或在 Windows 中直接双击
start_gui.bat
```

### 4. 命令行 (CLI) 快速用法
如果你习惯使用无图形界面的命令行：
```bash
# 爬取单卷直达链接 (自动识别小说 ID 与分卷 ID)
python scrape_linovelib.py "https://www.linovelib.com/novel/3095/vol_328281.html"

# 爬取目录页并指定分卷序号 (如第 1 卷)
python scrape_linovelib.py https://www.linovelib.com/novel/5131/catalog 1

# 从已有分卷抓取目录重新打包出 EPUB
python to_epub.py novels/败北女角太多了！/第1卷 "败北女角太多了！" "第1卷" "雨森焚火"
```

---

## 本地编译打包

项目自带完整的自动化编译与封装流水线：

```bash
# 一键编译 PyInstaller 目录并生成 Portable.zip 与 Setup.exe
build_release.bat
```
执行后将在 `dist/` 目录下生成：
* `dist/BiliNovelStudio/`：免安装绿色运行时目录（已内嵌专属文件夹图标）；
* `dist/BiliNovelStudio_Portable.zip`：便携发布压缩包；
* `dist/BiliNovelStudio_Setup_v1.0.0.exe`：全中文两步极简安装向导。

---

## 项目结构

```
bilinovel-studio/
├── launch_gui.py          # 桌面客户端主启动器 (PyWebView / 本地 REST 桥接)
├── gui_service.py         # GUI 服务端调度引擎与事件总线
├── runtime_env.py         # 运行时环境感知 (只读静态资源与持久化存储隔离)
├── scrape_linovelib.py    # 核心爬虫与异步并发抓取流水线
├── to_epub.py             # EPUB 转换与精排打包引擎
├── rubbish_secret_map.py  # 站点字体反混淆字典
├── gui/                   # Vue 3 现代化前端交互界面
│   ├── index.html
│   ├── app.js
│   ├── styles.css
│   └── app_icon.ico       # Windows 应用图标
├── docs/images/           # 官方文档预览截图
├── installer.iss          # Inno Setup 安装向导
├── ChineseSimplified.isl  # Inno Setup 简体中文语言包
├── build_exe.spec         # PyInstaller 绿色打包规格文件
├── build_release.bat      # 自动化一键打包脚本
├── requirements.txt       # 依赖清单
└── novels/                # 产出目录 (与核心代码解耦隔离)
```

---

## 开源许可证

本项目采用 [MIT License](LICENSE) 开源许可证。
欢迎提交 Issue 与 Pull Request 共同完善！
