"""
将爬取的小说文本 + 插图整合为标准 EPUB 电子书
支持独立运行或被爬虫脚本调用
"""

import os
import re
import sys
import html
from ebooklib import epub

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

CSS_CONTENT = """
@charset "utf-8";
body {
  font-family: "Noto Serif CJK SC", "Songti SC", "PingFang SC", "Microsoft YaHei", serif;
  line-height: 1.8;
  margin: 1em;
  text-align: justify;
  word-break: break-all;
}
h2 {
  text-align: center;
  margin: 1.5em 0 1em;
  font-size: 1.35em;
  font-weight: bold;
  border-bottom: 1px solid #e0e0e0;
  padding-bottom: 0.4em;
}
p {
  text-indent: 2em;
  margin: 0.5em 0;
}
.illustration {
  text-align: center;
  margin: 1.2em 0;
  page-break-inside: avoid;
}
.illustration img {
  max-width: 100%;
  height: auto;
  display: inline-block;
  border-radius: 4px;
}
.scene-break {
  margin: 1.8em auto !important;
  text-indent: 0 !important;
  text-align: center !important;
  color: #777;
  font-size: 1.15em;
  letter-spacing: 0.35em;
  line-height: 1;
}
.scene-break span {
  display: inline-block;
  opacity: 0.85;
}
.gallery-caption {
  text-indent: 0;
  text-align: center;
  font-size: 0.9em;
  color: #666;
  margin-top: 0.3em;
}
"""


def parse_chapters(text):
    """解析文本文件为章节列表 [(title, [paragraphs]), ...]"""
    chapters = []
    parts = re.split(r"\n={20,}\n", text)

    current_title = None
    current_body = []

    for part in parts:
        part = part.strip()
        if not part:
            continue

        lines = [l for l in part.split("\n") if l.strip()]

        # 判断是否是章节标题分隔块
        if len(lines) <= 3 and all(len(l.strip()) < 80 for l in lines) and not any(l.strip().startswith("[插图:") for l in lines) and not any(l.strip().startswith("[场景分隔") for l in lines):
            title = lines[0].strip()
            if title:
                if current_title and (current_body or len(chapters) == 0):
                    chapters.append((current_title, current_body))
                current_title = title
                current_body = []
            continue

        # 正文段落
        for line in part.split("\n"):
            line_str = line.strip()
            if line_str:
                current_body.append(line_str)

    if current_title:
        chapters.append((current_title, current_body))

    return chapters


def build_chapter_html(title, paragraphs, available_images, is_gallery=False):
    """构建单章 XHTML"""
    body_parts = []

    for para in paragraphs:
        if not para:
            continue

        # 1. 检查是否为显式场景分隔符标记
        m_break = re.match(r"^\[(?:场景分隔|分隔符|scene_break)(?::\s*(.+?))?\]$", para, re.IGNORECASE)
        if m_break:
            sym = m_break.group(1).strip() if m_break.group(1) else "◇"
            body_parts.append(f'<p class="scene-break"><span>{html.escape(sym)}</span></p>')
            continue

        # 2. 检查是否为单行独立符号分隔符（如 "◇", "◆", "* * *", "---", "——" 等）
        if re.match(r"^[\s\u3000]*[◇◆*＊☆★▲▼※§□■○●·•—\-_~=〜\.\s]{1,15}[\s\u3000]*$", para):
            sym = para.strip()
            if sym:
                body_parts.append(f'<p class="scene-break"><span>{html.escape(sym)}</span></p>')
                continue

        # 3. 检查是否为插图标记
        m = re.match(r"^\[插图:\s*(.+?)\]$", para)
        if m:
            img_ref = m.group(1).strip()
            # 提取文件名
            fname = os.path.basename(img_ref)
            if fname in available_images:
                body_parts.append(f'<div class="illustration"><img src="images/{fname}" alt="插图"/></div>')
            else:
                # 尝试通过名字模糊匹配可用图片
                matched = None
                for af in available_images:
                    if fname in af or os.path.splitext(fname)[0] in af:
                        matched = af
                        break
                if matched:
                    body_parts.append(f'<div class="illustration"><img src="images/{matched}" alt="插图"/></div>')
            continue

        # 4. 普通正文
        escaped = html.escape(para)
        body_parts.append(f"<p>{escaped}</p>")

    body_html = "\n  ".join(body_parts)

    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
  <meta charset="utf-8"/>
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
  <h2>{html.escape(title)}</h2>
  {body_html}
</body>
</html>"""


def generate_epub(volume_dir, novel_title="轻小说", volume_title="", author="佚名", output_file=None):
    """从卷目录生成 EPUB 电子书"""
    if not os.path.isdir(volume_dir):
        raise ValueError(f"目录不存在: {volume_dir}")

    images_dir = os.path.join(volume_dir, "插图")
    txt_files = [f for f in os.listdir(volume_dir) if f.endswith("_完整版.txt")]
    if not txt_files:
        txt_files = [f for f in os.listdir(volume_dir) if f.endswith(".txt")]
    if not txt_files:
        raise FileNotFoundError(f"在 {volume_dir} 中未找到小说文本文件（.txt）")

    text_file = os.path.join(volume_dir, txt_files[0])
    print(f"正在读取文本: {os.path.basename(text_file)}")
    with open(text_file, "r", encoding="utf-8") as f:
        full_text = f.read()

    chapters = parse_chapters(full_text)
    print(f"成功解析出 {len(chapters)} 个章节")

    # 扫描插图目录
    available_images = {}
    if os.path.isdir(images_dir):
        for fname in os.listdir(images_dir):
            if fname.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                available_images[fname] = os.path.join(images_dir, fname)
    print(f"找到 {len(available_images)} 张本地插图")

    full_book_title = novel_title
    if volume_title and volume_title not in novel_title:
        full_book_title = f"{novel_title}_{volume_title}"

    if not output_file:
        safe_name = re.sub(r'[\\/:*?"<>|]', "_", full_book_title)
        output_file = os.path.join(volume_dir, f"{safe_name}.epub")

    # 初始化 EPUB Book
    book = epub.EpubBook()
    book_id = f"linovelib-{re.sub(r'[^a-zA-Z0-9]', '_', full_book_title)}"
    book.set_identifier(book_id)
    book.set_title(full_book_title)
    book.set_language("zh")
    book.add_author(author)

    # 提取卷号与系列信息（支持 Calibre 与 Kavita 媒体库系列自动归类）
    m_idx = re.search(r"(\d+(?:\.\d+)?)", volume_title)
    if not m_idx:
        m_idx = re.search(r"(\d+(?:\.\d+)?)", full_book_title)
    series_index = m_idx.group(1) if m_idx else "1"

    # 写入 Calibre 2.0 / 3.0 系列元数据
    book.add_metadata(None, "meta", "", {"name": "calibre:series", "content": novel_title})
    book.add_metadata(None, "meta", "", {"name": "calibre:series_index", "content": series_index})

    # 写入 EPUB 3 / Kavita 规范 Collection 系列元数据
    book.add_metadata(None, "meta", novel_title, {"property": "belongs-to-collection", "id": "series_collection"})
    book.add_metadata(None, "meta", "series", {"refines": "#series_collection", "property": "collection-type"})
    book.add_metadata(None, "meta", series_index, {"refines": "#series_collection", "property": "group-position"})

    # 添加样式表
    css_item = epub.EpubItem(
        uid="style",
        file_name="style.css",
        media_type="text/css",
        content=CSS_CONTENT.encode("utf-8"),
    )
    book.add_item(css_item)

    # 确定封面
    cover_image_path = None
    # 优先检查是否存在 封面.jpg
    for cf in ["封面.jpg", "封面.png", "cover.jpg", "cover.png"]:
        p = os.path.join(volume_dir, cf)
        if os.path.isfile(p):
            cover_image_path = p
            break

    # 否则取插图目录中的第一张图（通常是卷首彩插/封面）
    if not cover_image_path and available_images:
        # 按文件名排序
        sorted_img_names = sorted(available_images.keys())
        cover_image_path = available_images[sorted_img_names[0]]

    if cover_image_path and os.path.isfile(cover_image_path):
        with open(cover_image_path, "rb") as cf:
            cdata = cf.read()
        ext = os.path.splitext(cover_image_path)[1].lower()
        media_type = "image/png" if ext == ".png" else "image/jpeg"
        book.set_cover("cover.jpg", cdata)
        print(f"已设置封面: {os.path.basename(cover_image_path)}")

    # 将所有插图添加到 EPUB 清单
    media_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    for fname, fpath in available_images.items():
        with open(fpath, "rb") as f:
            idata = f.read()
        ext = os.path.splitext(fname)[1].lower()
        mtype = media_map.get(ext, "image/jpeg")
        img_item = epub.EpubItem(
            uid=f"img_{re.sub(r'[^a-zA-Z0-9_]', '_', fname)}",
            file_name=f"images/{fname}",
            media_type=mtype,
            content=idata,
        )
        book.add_item(img_item)

    # 生成各章节 XHTML
    epub_chapters = []
    spine = ["nav"]
    toc = []

    for i, (title, paragraphs) in enumerate(chapters):
        # 判断是否为纯图画廊章节
        is_gallery = any(kw in title for kw in ["插图", "彩页", "插画", "画廊", "Gallery"])
        ch_html = build_chapter_html(title, paragraphs, available_images, is_gallery=is_gallery)

        ch_item = epub.EpubHtml(
            title=title,
            file_name=f"chapter_{i:04d}.xhtml",
            lang="zh",
        )
        ch_item.content = ch_html.encode("utf-8")
        ch_item.add_item(css_item)
        book.add_item(ch_item)

        epub_chapters.append(ch_item)
        spine.append(ch_item)
        toc.append(ch_item)

    book.toc = toc
    book.spine = spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    print(f"正在打包写入 EPUB: {output_file}")
    epub.write_epub(output_file, book)
    print(f"✅ EPUB 生成成功！")
    print(f"  文件位置: {output_file}")
    print(f"  总章节数: {len(chapters)}")
    print(f"  打包插图: {len(available_images)} 张")
    return output_file


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if len(sys.argv) >= 2:
        vol_dir = sys.argv[1]
        if not os.path.isabs(vol_dir):
            vol_dir = os.path.join(base_dir, vol_dir)
        novel_title = sys.argv[2] if len(sys.argv) >= 3 else os.path.basename(vol_dir).split("_")[0]
        volume_title = sys.argv[3] if len(sys.argv) >= 4 else ""
        author = sys.argv[4] if len(sys.argv) >= 5 else "老佛爷"
    else:
        # 默认自动搜寻 novels/ 目录下的子分卷
        candidate_dirs = [
            os.path.join(base_dir, "novels", "挚友的女朋友喜欢我", "第1卷"),
            os.path.join(base_dir, "novels", "配角在学院中生存", "正篇")
        ]
        vol_dir = None
        for d in candidate_dirs:
            if os.path.isdir(d):
                vol_dir = d
                break
        if not vol_dir:
            print("用法: python to_epub.py <小说分卷目录> [小说名] [卷名] [作者]")
            return

        novel_title = "挚友的女朋友喜欢我" if "挚友" in vol_dir else "配角在学院中生存"
        volume_title = "第1卷" if "第1卷" in vol_dir else ("正篇" if "正篇" in vol_dir else "")
        author = "老佛爷" if "挚友" in vol_dir else "Korita"

    generate_epub(vol_dir, novel_title=novel_title, volume_title=volume_title, author=author)


if __name__ == "__main__":
    main()
