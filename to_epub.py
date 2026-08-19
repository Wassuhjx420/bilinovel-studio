"""
将爬取的小说文本 + 插图整合为标准 EPUB 电子书
支持标准日轻排版规范：封面 -> 本卷信息和简介 -> 彩页 -> 正文（内嵌黑白插图）
"""

import os
import re
import sys
import html
import hashlib
from ebooklib import epub

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

CSS_CONTENT = """
@charset "utf-8";
body {
  font-family: "Noto Serif CJK SC", "Songti SC", "Source Han Serif", "PingFang SC", "Microsoft YaHei", serif;
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
.book-info {
  margin: 1.5em 0;
  text-align: center;
}
.book-info p {
  text-indent: 0 !important;
  text-align: center !important;
  color: #555;
  font-size: 0.95em;
  margin: 0.35em 0;
}
.divider {
  text-indent: 0 !important;
  text-align: center !important;
  color: #aaa;
  margin: 1.5em 0;
  letter-spacing: 0.2em;
}
.synopsis {
  margin: 1.8em 0;
  padding: 1.2em 1.5em;
  background: rgba(0, 0, 0, 0.025);
  border-left: 4px solid #888;
  border-radius: 4px;
}
.synopsis-title {
  text-align: center;
  font-size: 1.15em;
  font-weight: bold;
  margin: 0.2em 0 0.8em;
  text-indent: 0 !important;
  color: #333;
}
.synopsis p {
  text-indent: 2em;
  line-height: 1.8;
  color: #444;
}
.illustration {
  text-align: center;
  text-indent: 0 !important;
  margin: 1.8em 0;
  page-break-inside: avoid;
}
.illustration img {
  max-width: 100%;
  height: auto;
  display: inline-block;
  border-radius: 4px;
}
.gallery-item {
  text-align: center;
  text-indent: 0 !important;
  margin: 1.8em 0;
  page-break-inside: avoid;
}
.gallery-item img {
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


def build_color_page_html(title, paragraphs, available_images, story_images=None, story_hashes=None):
    """
    构建日轻标准【彩页与卷首信息】页面（封面-本卷信息和简介-彩页-正文）
    包含：制作/录入信息、简介框、仅卷首全彩插图（彻底排除正文黑白插图）
    """
    info_lines = []
    synopsis_lines = []
    gallery_images = []

    in_synopsis = False
    in_hidden_section = False

    for para in paragraphs:
        if not para:
            continue

        # 忽略剧透提示及折叠黑白图声明
        if "※黑白插图已内嵌正文※" in para or "点击可查看完整插图" in para or "读者请无视" in para:
            in_hidden_section = True
            continue

        if in_hidden_section:
            continue

        m_img = re.match(r"^\[插图:\s*(.+?)\]$", para)
        if m_img:
            img_ref = m_img.group(1).strip()
            fname = os.path.basename(img_ref)
            # 如果该图片在正文中已经被引用为黑白插图，则彩页部分不重复收录
            if story_images and fname in story_images:
                continue

            resolved_fname = None
            resolved_path = None
            if fname in available_images:
                resolved_fname = fname
                resolved_path = available_images[fname]
            else:
                for af, ap in available_images.items():
                    if fname in af or os.path.splitext(fname)[0] in af:
                        resolved_fname = af
                        resolved_path = ap
                        break

            if resolved_path and os.path.isfile(resolved_path):
                if story_hashes:
                    try:
                        with open(resolved_path, "rb") as f:
                            img_h = hashlib.md5(f.read()).hexdigest()
                        if img_h in story_hashes:
                            # 属于正文黑白插图副本，彩页中剔除
                            continue
                    except Exception:
                        pass
                if resolved_fname not in gallery_images:
                    gallery_images.append(resolved_fname)
            continue

        # 简介开始标记
        if para.startswith("内容简介") or para.startswith("简介"):
            in_synopsis = True
            continue

        if para.startswith("———") or para.startswith("───") or para.startswith("==="):
            in_synopsis = False
            continue

        if in_synopsis:
            synopsis_lines.append(para)
        else:
            info_lines.append(para)

    body_parts = []
    body_parts.append(f'<h2>{html.escape(title)}</h2>')

    if info_lines:
        body_parts.append('<div class="book-info">')
        for l in info_lines:
            body_parts.append(f'  <p>{html.escape(l)}</p>')
        body_parts.append('</div>')
        body_parts.append('<p class="divider">————————————————</p>')

    if synopsis_lines:
        body_parts.append('<div class="synopsis">')
        body_parts.append('  <h3 class="synopsis-title">内容简介</h3>')
        for l in synopsis_lines:
            body_parts.append(f'  <p>{html.escape(l)}</p>')
        body_parts.append('</div>')

    if gallery_images:
        for img_name in gallery_images:
            body_parts.append(f'<div class="gallery-item"><img src="images/{img_name}" alt="彩页"/></div>')

    body_html = "\n  ".join(body_parts)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
  <meta charset="utf-8"/>
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body class="color-page">
  {body_html}
</body>
</html>"""


def build_chapter_html(title, paragraphs, available_images):
    """构建正文单章 XHTML（正文段落 + 场景分隔符 + 内嵌黑白插图）"""
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
            fname = os.path.basename(img_ref)
            if fname in available_images:
                body_parts.append(f'<div class="illustration"><img src="images/{fname}" alt="插图"/></div>')
            else:
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
    """从卷目录生成符合日轻标准排版的 EPUB 电子书（封面 -> 本卷信息和简介 -> 彩页 -> 正文）"""
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
    for cf in ["封面.jpg", "封面.png", "cover.jpg", "cover.png"]:
        p = os.path.join(volume_dir, cf)
        if os.path.isfile(p):
            cover_image_path = p
            break

    if not cover_image_path and available_images:
        sorted_img_names = sorted(available_images.keys())
        cover_image_path = available_images[sorted_img_names[0]]

    if cover_image_path and os.path.isfile(cover_image_path):
        with open(cover_image_path, "rb") as cf:
            cdata = cf.read()
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

    # 扫描正文章节中引用过的黑白插图与 MD5 二进制指纹，用于彩页排重
    story_images = set()
    story_hashes = set()
    first_ch_is_gallery = False
    if chapters:
        first_title = chapters[0][0]
        first_ch_is_gallery = any(kw in first_title for kw in ["插图", "彩页", "插画", "画廊", "Gallery"]) or any("内容简介" in p for p in chapters[0][1])
        start_idx = 1 if first_ch_is_gallery else 0
        for _, paras in chapters[start_idx:]:
            for p in paras:
                m = re.match(r"^\[插图:\s*(.+?)\]$", p)
                if m:
                    fname = os.path.basename(m.group(1).strip())
                    story_images.add(fname)
                    fpath = available_images.get(fname)
                    if not fpath:
                        for af, ap in available_images.items():
                            if fname in af or os.path.splitext(fname)[0] in af:
                                fpath = ap
                                break
                    if fpath and os.path.isfile(fpath):
                        try:
                            with open(fpath, "rb") as f:
                                story_hashes.add(hashlib.md5(f.read()).hexdigest())
                        except Exception:
                            pass

    epub_chapters = []
    spine = ["nav"]
    toc = []

    for i, (title, paragraphs) in enumerate(chapters):
        if i == 0 and first_ch_is_gallery:
            # 封面后的第一页：本卷信息、简介与卷首全彩插图
            ch_html = build_color_page_html("彩页", paragraphs, available_images, story_images=story_images, story_hashes=story_hashes)
            ch_item = epub.EpubHtml(
                title="彩页",
                file_name="color.xhtml",
                lang="zh",
            )
        else:
            # 正文章节
            ch_html = build_chapter_html(title, paragraphs, available_images)
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
        author = sys.argv[4] if len(sys.argv) >= 5 else "佚名"
    else:
        candidate_dirs = [
            os.path.join(base_dir, "novels", "败北女角太多了！", "第9卷"),
            os.path.join(base_dir, "novels", "在男性禁入的游戏世界里，我唯一该做的事情 我转生成了夹在百合之间的男人", "第9卷")
        ]
        vol_dir = None
        for d in candidate_dirs:
            if os.path.isdir(d):
                vol_dir = d
                break
        if not vol_dir:
            print("用法: python to_epub.py <小说分卷目录> [小说名] [卷名] [作者]")
            return

        novel_title = "败北女角太多了！" if "败北" in vol_dir else "在男性禁入的游戏世界里，我唯一该做的事情 我转生成了夹在百合之间的男人"
        volume_title = "第9卷"
        author = "雨森焚火" if "败北" in vol_dir else "端桜了"

    generate_epub(vol_dir, novel_title=novel_title, volume_title=volume_title, author=author)


if __name__ == "__main__":
    main()
