"""
哔哩轻小说极速爬虫 & 出版级 EPUB 制作工具 - 桌面 GUI 启动器
支持 PyWebView 原生桌面客户端窗口模式 与 浏览器双向 REST/SSE 桥接通信模式

Disclaimer / 免责声明:
本项目仅供 Python 自动化技术交流与个人离线阅读研究使用。
小说内容及插图版权均归原作者及轻小说出版方所有。
严禁将本项目及衍生工具用于任何商业营利目的。
"""

import json
import os
import queue
import sys
import threading
import urllib.parse
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# 在无控制台 (Windows GUI / pythonw) 运行时确保标准输出流安全
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w', encoding='utf-8')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w', encoding='utf-8')

from gui_service import gui_service, JsApi
from runtime_env import get_gui_dir, get_novels_dir

GUI_DIR = get_gui_dir()



class BridgeHTTPHandler(SimpleHTTPRequestHandler):
    """支持静态资源托管与前后端双向 REST/SSE 桥接通信的 HTTP 处理器"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=GUI_DIR, **kwargs)

    def log_message(self, format, *args):
        # 静默常规 HTTP 静态资源日志
        pass

    def _send_json(self, data, status=200):
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass
        except Exception as e:
            pass


    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 1. 扫描书架
        if path == "/api/bookshelf":
            dl_dir = query.get("dir", [None])[0]
            books = gui_service.scan_bookshelf(dl_dir)
            self._send_json({"status": "success", "books": books})
            return

        # 2. 事件长轮询/流式获取
        if path == "/api/events":
            # 返回当前积攒的历史或最新事件
            sub_q = queue.Queue()
            gui_service.event_subscribers.append(sub_q)
            try:
                # 等待 0.1~2.0 秒获取事件，若无事件则返回空
                events = []
                try:
                    ev = sub_q.get(timeout=1.5)
                    events.append(ev)
                    while not sub_q.empty():
                        events.append(sub_q.get_nowait())
                except queue.Empty:
                    pass
                self._send_json({"events": events})
            finally:
                if sub_q in gui_service.event_subscribers:
                    gui_service.event_subscribers.remove(sub_q)
            return

        # 3. 选择文件夹
        if path == "/api/choose_folder":
            folder = gui_service.choose_folder()
            self._send_json({"status": "success", "folder": folder})
            return

        # 4. 获取动态默认环境配置（避免前端写死任何个人绝对路径）
        if path == "/api/defaults":
            from gui_service import DEFAULT_NOVELS_DIR
            self._send_json({"status": "success", "downloadDir": os.path.normpath(DEFAULT_NOVELS_DIR)})
            return

        # 静态文件正常处理
        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_len = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_len) if content_len > 0 else b"{}"
        try:
            body = json.loads(post_body.decode("utf-8"))
        except Exception:
            body = {}

        # 1. 智能解析小说
        if path == "/api/parse":
            novel_url = body.get("url", "3095")
            try:
                res = gui_service.parse_novel(novel_url)
                self._send_json({"status": "success", "book": res})
            except Exception as e:
                self._send_json({"status": "error", "message": str(e)}, status=500)
            return

        # 2. 启动下载
        if path == "/api/download/start":
            tasks = body.get("tasks", [])
            settings = body.get("settings", {})
            res = gui_service.start_download(tasks, settings)
            self._send_json(res)
            return

        # 3. 暂停下载
        if path == "/api/download/pause":
            res = gui_service.pause_download()
            self._send_json(res)
            return

        # 4. 恢复下载
        if path == "/api/download/resume":
            res = gui_service.resume_download()
            self._send_json(res)
            return

        # 5. 打开目录
        if path == "/api/open_folder":
            folder_path = body.get("path", "")
            ok = gui_service.open_folder(folder_path)
            self._send_json({"status": "success" if ok else "error"})
            return

        # 6. 打开 EPUB 电子书
        if path == "/api/open_epub":
            epub_path = body.get("path", "")
            ok = gui_service.open_epub(epub_path)
            self._send_json({"status": "success" if ok else "error"})
            return

        # 7. 手动重新封装 EPUB
        if path == "/api/rebuild_epub":
            vol_dir = body.get("dir", "")
            title = body.get("title", "轻小说")
            vol_name = body.get("volume", "第1卷")
            author = body.get("author", "佚名")
            res = gui_service.build_epub_manually(vol_dir, title, vol_name, author)
            self._send_json(res)
            return

        self._send_json({"status": "not_found"}, status=404)


def start_local_server(port=8765):
    server = ThreadingHTTPServer(('127.0.0.1', port), BridgeHTTPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{port}/index.html"


def check_environment():
    """检查启动前必要核心依赖，若缺失则给出友好中文安装指引"""
    missing = []
    try:
        import playwright
    except ImportError:
        missing.append("playwright")
    try:
        import bs4
    except ImportError:
        missing.append("beautifulsoup4")
    try:
        import ebooklib
    except ImportError:
        missing.append("ebooklib")

    if missing:
        print("\n" + "!" * 64)
        print(" [!] 启动失败：检测到当前 Python 环境缺少必要核心依赖:")
        for pkg in missing:
            print(f"     - {pkg}")
        print("\n [*] 请在当前项目目录下打开终端，执行以下命令安装依赖:")
        print("     pip install -r requirements.txt")
        print("!" * 64 + "\n")
        sys.exit(1)


def main():
    check_environment()
    print("=" * 60)
    print(" 🚀 哔哩轻小说极速爬虫 & 出版级 EPUB 制作客户端 Pro (GUI)")
    print("=" * 60)

    url = start_local_server(8765)
    print(f"[*] 本地前后端同构服务已就绪: {url}")

    # 尝试加载 pywebview 原生窗口并注入 js_api 桥接
    try:
        import webview
        print("[*] 检测到 pywebview，正在启动原生磨砂毛玻璃桌面客户端窗口...")
        window = webview.create_window(
            title='哔哩轻小说 Studio Pro',
            url=url,
            width=1260,
            height=820,
            min_size=(1000, 680),
            background_color='#07090e',
            js_api=JsApi()
        )
        gui_service.set_window(window)

        webview.start(debug=False)
    except Exception as e:
        print(f"[!] PyWebView 窗口启动提示 ({e})，自动启动浏览器同构模式...")
        webbrowser.open(url)
        print("[*] 已在浏览器中打开前端交互界面，后端 REST/SSE 桥接通信已全量激活！")
        print("[*] 按 Ctrl+C 可停止本地服务。")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            print("\n[*] 服务已退出。")


if __name__ == '__main__':
    main()
