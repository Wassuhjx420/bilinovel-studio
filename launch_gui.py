"""
哔哩轻小说极速爬虫 & 出版级 EPUB 制作工具 - 桌面 GUI 与 Linux 服务器 Web 启动器
支持 PyWebView 原生桌面窗口模式、桌面浏览器模式以及 Linux 无头服务器 / Docker Web 部署模式

Disclaimer / 免责声明:
本项目仅供 Python 自动化技术交流与个人离线阅读研究使用。
小说内容及插图版权均归原作者及轻小说出版方所有。
严禁将本项目及衍生工具用于任何商业营利目的。
"""

import argparse
import json
import os
import queue
import signal
import sys
import threading
import urllib.parse
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# 在无控制台 (Windows GUI / pythonw) 运行时确保标准输出流安全
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

from gui_service import gui_service, JsApi
from runtime_env import get_gui_dir, get_novels_dir, is_headless_linux

GUI_DIR = get_gui_dir()


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    """允许端口快速复用，避免 Linux 服务器重启时触发 TIME_WAIT Address already in use"""
    allow_reuse_address = True
    daemon_threads = True


class BridgeHTTPHandler(SimpleHTTPRequestHandler):
    """支持静态资源托管与前后端双向 REST/长轮询/文件下载的 HTTP 处理器"""

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
        except Exception:
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

        # 0. 根路径重定向至 index.html，方便服务器直接访问 http://<host>:<port>/
        if path == "/":
            self.path = "/index.html"
            super().do_GET()
            return

        # 0.1 健康检查接口（便于 Docker / systemd / 反向代理探活）
        if path == "/api/health":
            self._send_json({
                "status": "ok",
                "platform": sys.platform,
                "isHeadlessServer": is_headless_linux(),
            })
            return

        # 1. 扫描书架
        if path == "/api/bookshelf":
            dl_dir = query.get("dir", [None])[0]
            books = gui_service.scan_bookshelf(dl_dir)
            self._send_json({"status": "success", "books": books})
            return

        # 2. 事件长轮询/流式获取
        if path == "/api/events":
            sub_q = queue.Queue()
            gui_service.event_subscribers.append(sub_q)
            try:
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

        # 4. 获取动态默认环境配置
        if path == "/api/defaults":
            self._send_json({
                "status": "success",
                "downloadDir": os.path.normpath(get_novels_dir()),
                "isHeadlessServer": is_headless_linux(),
                "platform": sys.platform,
            })
            return

        # 5. 远程浏览器安全下载已生成的 EPUB 电子书
        if path == "/api/epub/download":
            req_path = query.get("path", [""])[0]
            if not gui_service.is_allowed_epub_path(req_path):
                self._send_json({"status": "error", "message": "无效或无权限访问的 EPUB 文件路径"}, status=403)
                return

            real_path = os.path.realpath(req_path)
            filename = os.path.basename(real_path)
            quoted_name = urllib.parse.quote(filename, safe="")
            file_size = os.path.getsize(real_path)
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/epub+zip")
                self.send_header("Content-Length", str(file_size))
                self.send_header(
                    "Content-Disposition",
                    f"attachment; filename=\"book.epub\"; filename*=UTF-8''{quoted_name}",
                )
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                with open(real_path, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                pass
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
            conv_sc = bool(body.get("convertToSimplified", True))
            res = gui_service.build_epub_manually(vol_dir, title, vol_name, author, convert_to_simplified=conv_sc)
            self._send_json(res)
            return

        self._send_json({"status": "not_found"}, status=404)


def start_local_server(port=8765, host="127.0.0.1"):
    server = ReusableThreadingHTTPServer((host, int(port)), BridgeHTTPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    display_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    return f"http://{display_host}:{port}/index.html"


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

    try:
        import opencc
    except ImportError:
        print("[!] 提示：未检测到 opencc-python-reimplemented，繁简转换功能将自动跳过。可执行 pip install -r requirements.txt 安装。")


def parse_args():
    headless_linux = is_headless_linux()
    default_host = os.environ.get("BILINOVEL_HOST", "0.0.0.0" if headless_linux else "127.0.0.1")
    default_port = int(os.environ.get("BILINOVEL_PORT", "8765"))

    parser = argparse.ArgumentParser(description="哔哩轻小说 Studio Pro 桌面客户端 / Linux Web 服务启动器")
    parser.add_argument("--host", default=default_host, help=f"HTTP 监听地址（默认 {default_host}）")
    parser.add_argument("--port", type=int, default=default_port, help=f"HTTP 监听端口（默认 {default_port}）")
    parser.add_argument("--web", "--server", dest="web_mode", action="store_true", help="强制以 Web 服务模式运行（跳过原生桌面窗口）")
    parser.add_argument("--no-browser", action="store_true", help="启动 Web 服务后不自动打开本地浏览器")
    return parser.parse_args()


def _wait_for_shutdown():
    stop_event = threading.Event()

    def _handle_signal(signum, frame):
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle_signal)
        except Exception:
            pass

    try:
        while not stop_event.is_set():
            stop_event.wait(0.5)
    except KeyboardInterrupt:
        pass
    print("\n[*] 服务已退出。")


def main():
    args = parse_args()
    check_environment()
    headless_linux = is_headless_linux()

    print("=" * 60)
    print(" 哔哩轻小说极速爬虫 & 精排 EPUB 制作客户端 Pro")
    print("=" * 60)

    url = start_local_server(port=args.port, host=args.host)
    print(f"[*] 本地前后端服务已就绪: http://{args.host}:{args.port}/")

    # 1. Linux 无头服务器环境或显式指定 --web/--server：直接以纯 Web 服务常驻运行
    if headless_linux or args.web_mode:
        if headless_linux:
            print("[*] 检测到 Linux 无头服务器环境，已自动启用 Web 服务部署模式。")
            print(f"[*] 请通过浏览器访问: http://<服务器IP>:{args.port}/")
        elif not args.no_browser:
            try:
                webbrowser.open(url)
                print(f"[*] 已在浏览器中打开交互界面: {url}")
            except Exception:
                pass
        print("[*] 按 Ctrl+C 或发送 SIGTERM 停止服务。")
        _wait_for_shutdown()
        return

    # 2. 桌面环境优先尝试加载 pywebview 原生窗口，失败时回退至浏览器模式
    try:
        import webview
        print("[*] 检测到 pywebview，正在启动原生桌面客户端窗口...")
        window = webview.create_window(
            title="哔哩轻小说 Studio Pro",
            url=url,
            width=1260,
            height=820,
            min_size=(1000, 680),
            background_color="#07090e",
            js_api=JsApi(),
        )
        gui_service.set_window(window)
        webview.start(debug=False)
    except Exception as e:
        print(f"[!] PyWebView 窗口启动提示 ({e})，自动启动浏览器模式...")
        if not args.no_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        print(f"[*] 已启动浏览器访问模式: {url}")
        print("[*] 按 Ctrl+C 可停止本地服务。")
        _wait_for_shutdown()


if __name__ == "__main__":
    main()
