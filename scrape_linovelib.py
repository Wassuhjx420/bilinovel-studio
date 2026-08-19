"""
哔哩轻小说通用爬虫与 EPUB 一键打包流水线（日轻/韩轻全通用版）

功能特性：
1. 通用 URL 解析：支持全本目录、单卷链接（如 vol_328281.html）、小说主页及纯小说 ID 输入
2. 多分卷与多模板智能解析：自动兼容桌面版 (.volume) 与响应式 (#volumes) 目录结构，支持按卷号、卷 ID (vol_XXXXX) 或关键词自动匹配
3. 全子分页无损递归合并：自动探测每章 ReadParams.url_next，合并长章节内所有分页（1/2, 2/2, 1/7...），彻底杜绝缺页与截断
4. 真实 DOM 渲染物理坐标排序：使用 getBoundingClientRect() 绝对 Y 坐标，精准锚定正文、场景分隔符与插图物理位置
5. 卷首全彩画廊与封面自动化：提取卷首彩插及角色卡，自动设置电子书封面（封面.jpg）
6. 结构化分层输出：严格保存于 novels/<小说名>/<分卷名>/ 目录，与代码本体解耦
7. 标准 EPUB 封装：自动生成并覆盖旧版本，包含目录导航、精美排版与插图清单
"""

import os
import re
import sys
import time
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from to_epub import generate_epub

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DOMAIN = "https://www.linovelib.com"
REQUEST_DELAY = 0.8


def normalize_input_url(raw_url):
    """
    智能解析用户输入的各种 URL 形式：
    - https://www.linovelib.com/novel/3095/vol_328281.html
    - https://www.bilinovel.com/novel/3095/catalog
    - https://www.linovelib.com/novel/3095.html
    - 3095
    返回 (catalog_url, novel_id, vol_target_id)
    """
    if not raw_url:
        return f"{BASE_DOMAIN}/novel/5131/catalog", "5131", None

    url = raw_url.strip()
    novel_id = None
    vol_target = None

    m_novel = re.search(r"/novel/(\d+)", url)
    if m_novel:
        novel_id = m_novel.group(1)
    elif url.isdigit():
        novel_id = url

    m_vol = re.search(r"vol_(\d+)", url)
    if m_vol:
        vol_target = m_vol.group(1)

    if not novel_id:
        novel_id = "5131"

    catalog_url = f"{BASE_DOMAIN}/novel/{novel_id}/catalog"
    return catalog_url, novel_id, vol_target


def wait_for_turnstile(page, max_wait=30):
    """等待 Cloudflare Turnstile 验证通过，如遇复选框则尝试自动物理点击"""
    clicked = False
    for i in range(max_wait):
        title = page.title()
        if "请稍候" not in title and "Just a moment" not in title and "Attention" not in title and "Checking" not in title:
            return True

        if not clicked:
            for f in page.frames:
                if "turnstile" in f.url or "cloudflare" in f.url:
                    try:
                        b = f.frame_element().bounding_box()
                        if b and b['width'] > 0:
                            cx = b['x'] + 30
                            cy = b['y'] + b['height'] / 2
                            print(f"  👆 检测到 Turnstile 验证，尝试自动点击 ({cx}, {cy})...")
                            page.mouse.move(cx, cy)
                            page.wait_for_timeout(200)
                            page.mouse.click(cx, cy)
                            clicked = True
                            break
                    except Exception:
                        pass
        page.wait_for_timeout(1000)
    return "请稍候" not in page.title()


def is_same_chapter_url(base_url, next_url):
    """判断 next_url 是否属于 base_url 的同一章节分页（如 316496.html 与 316496_2.html）"""
    m1 = re.search(r"/(\d+)(?:_\d+)?\.html", base_url)
    m2 = re.search(r"/(\d+)(?:_\d+)?\.html", next_url)
    if m1 and m2:
        return m1.group(1) == m2.group(1)
    return False


def parse_catalog_volumes(page, catalog_url):
    """从目录页提取所有分卷及其所属章节列表（支持桌面版与响应式两种模板）"""
    print(f"正在访问目录页: {catalog_url} ...")
    page.goto(catalog_url, wait_until="domcontentloaded", timeout=45000)
    wait_for_turnstile(page)
    page.wait_for_timeout(1500)

    soup = BeautifulSoup(page.content(), "html.parser")

    # 提取小说名称
    novel_title = "未知小说"
    title_el = soup.select_one("h1.book-title, h1, meta[property='og:novel:book_name']")
    if title_el:
        if title_el.name == "meta":
            novel_title = title_el.get("content", "").strip()
        else:
            novel_title = title_el.get_text(strip=True)
    novel_title = re.sub(r"\s*(正文|在线阅读|_哔哩轻小说).*", "", novel_title).strip()

    # 提取作者
    author = "佚名"
    author_meta = soup.select_one("meta[property='og:novel:author']")
    if author_meta:
        author = author_meta.get("content", "").strip()
    else:
        author_el = soup.select_one(".book-author, .author")
        if author_el:
            author = author_el.get_text(strip=True).replace("作者：", "").strip()

    volumes = []

    # 模式 A: 桌面版 .volume 容器
    vol_divs = soup.select("div.volume, .volume-list .volume")
    if vol_divs:
        for vdiv in vol_divs:
            vol_header = vdiv.select_one(".volume-info h2, h2.v-line, h2, .chapter-bar, h3, .volume-title")
            vol_name = vol_header.get_text(strip=True) if vol_header else ""
            if not vol_name:
                img = vdiv.select_one("a.volume-cover img, img")
                if img and img.get("alt"):
                    vol_name = img.get("alt").strip()
            if not vol_name:
                vol_name = "分卷"
            vol_name = re.sub(r"\s+", " ", vol_name).strip()

            vid = None
            a_vol = vdiv.select_one("a[href*='vol_']")
            if a_vol:
                m_vid = re.search(r"vol_(\d+)", a_vol.get("href", ""))
                if m_vid:
                    vid = m_vid.group(1)

            chs = []
            for a in vdiv.select("ul.chapter-list li a, .chapter-li a"):
                href = a.get("href", "")
                title = a.get_text(strip=True)
                if href and not href.startswith("javascript") and "/novel/" in href and not "/vol_" in href:
                    full_url = href if href.startswith("http") else f"{BASE_DOMAIN}{href}"
                    if title:
                        chs.append({
                            "title": title,
                            "url": full_url
                        })
            if chs:
                volumes.append({
                    "volume_name": vol_name,
                    "volume_id": vid,
                    "chapters": chs
                })
    else:
        # 模式 B: 扁平 li 结构 (#volumes li, li.chapter-bar)
        items = soup.select("#volumes li, .chapter-list li, .dir-list li")
        current_vol_name = None
        current_vol_id = None
        current_vol_chapters = []

        for li in items:
            classes = li.get("class", [])
            if "chapter-bar" in classes:
                vol_name = li.get_text(strip=True)
                a_vol = li.select_one("a")
                vol_href = a_vol.get("href", "") if a_vol else ""
                m_vid = re.search(r"vol_(\d+)", vol_href)
                vid = m_vid.group(1) if m_vid else None

                if current_vol_name and current_vol_chapters:
                    volumes.append({
                        "volume_name": current_vol_name,
                        "volume_id": current_vol_id,
                        "chapters": current_vol_chapters
                    })
                    current_vol_chapters = []
                current_vol_name = vol_name
                current_vol_id = vid
            elif "chapter-li" in classes:
                a = li.select_one("a")
                if a:
                    href = a.get("href", "")
                    title = a.get_text(strip=True)
                    if href and not href.startswith("javascript") and "/novel/" in href and not "/vol_" in href:
                        full_url = href if href.startswith("http") else f"{BASE_DOMAIN}{href}"
                        if title:
                            if not current_vol_name:
                                current_vol_name = "第1卷"
                            current_vol_chapters.append({
                                "title": title,
                                "url": full_url
                            })

        if current_vol_name and current_vol_chapters:
            volumes.append({
                "volume_name": current_vol_name,
                "volume_id": current_vol_id,
                "chapters": current_vol_chapters
            })

    print(f"\n📖 小说名称: 《{novel_title}》 | 作者: {author}")
    print(f"共解析到 {len(volumes)} 个分卷:")
    for idx, v in enumerate(volumes, 1):
        vid_str = f" [vol_{v['volume_id']}]" if v.get("volume_id") else ""
        print(f"  [{idx}] {v['volume_name']}{vid_str} (包含 {len(v['chapters'])} 章)")

    return novel_title, author, volumes


def extract_subpage_items(page, subpage_url):
    """提取单张子页中的所有可见段落、插图及场景分隔符（按真实物理渲染 Y 坐标排序）"""
    page.goto(subpage_url, wait_until="domcontentloaded", timeout=35000)
    wait_for_turnstile(page)
    page.wait_for_timeout(800)

    # 滚动到底部触发正文与插图完整渲染
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(1000)

    items = page.evaluate('''() => {
        const container = document.querySelector('#acontent') || document.querySelector('#TextContent') || document.querySelector('.read-content');
        if (!container) return [];

        const scrollY = window.scrollY || window.pageYOffset || 0;
        const results = [];
        const seenImgs = new Set();

        function traverse(node) {
            if (!node || node.nodeType !== 1) return;
            const tag = node.tagName.toLowerCase();
            const rect = node.getBoundingClientRect();

            if (tag === 'img') {
                if (!seenImgs.has(node)) {
                    seenImgs.add(node);
                    const src = node.getAttribute('data-src') || node.getAttribute('data-original') || node.getAttribute('src') || '';
                    if (src && src.indexOf('sloading') === -1 && src.indexOf('book-cover-no') === -1) {
                        const fullSrc = src.startsWith('http') ? src : 'https://www.linovelib.com' + src;
                        results.push({
                            type: 'img',
                            src: fullSrc,
                            top: Math.round(rect.top + scrollY)
                        });
                    }
                }
                return;
            }

            if (tag === 'center') {
                const imgs = node.querySelectorAll('img');
                if (imgs.length > 0) {
                    for (const img of imgs) {
                        traverse(img);
                    }
                }
                const text = node.textContent.trim();
                if (text && !text.includes('adsbygoogle') && !text.includes('加載失敗')) {
                    const isDivider = /^[\\s\\u3000]*[◇◆*＊☆★▲▼※§□■○●·•—\\-_~=〜\\.\\s\\dIVXLCDMivxlcdm]{1,15}[\\s\\u3000]*$/.test(text);
                    if (isDivider || text.length <= 10) {
                        results.push({
                            type: 'scene_break',
                            symbol: text,
                            top: Math.round(rect.top + scrollY)
                        });
                    } else {
                        results.push({
                            type: 'text',
                            text: text,
                            top: Math.round(rect.top + scrollY)
                        });
                    }
                } else if (imgs.length === 0) {
                    results.push({
                        type: 'scene_break',
                        symbol: '◇',
                        top: Math.round(rect.top + scrollY)
                    });
                }
                return;
            }

            if (tag === 'hr') {
                results.push({
                    type: 'scene_break',
                    symbol: '◇',
                    top: Math.round(rect.top + scrollY)
                });
                return;
            }

            if (tag === 'p') {
                const imgs = node.querySelectorAll('img');
                if (imgs.length > 0) {
                    for (const img of imgs) {
                        traverse(img);
                    }
                }
                if (rect.height > 0) {
                    const text = node.textContent.trim();
                    if (text && !text.includes('adsbygoogle') && !text.includes('內容加載失敗') && !text.includes('内容加载失败')) {
                        const isDivider = /^[\\s\\u3000]*[◇◆*＊☆★▲▼※§□■○●·•—\\-_~=〜\\.\\s]{1,15}[\\s\\u3000]*$/.test(text);
                        if (isDivider) {
                            results.push({
                                type: 'scene_break',
                                symbol: text,
                                top: Math.round(rect.top + scrollY)
                            });
                        } else {
                            results.push({
                                type: 'text',
                                text: text,
                                top: Math.round(rect.top + scrollY)
                            });
                        }
                    }
                }
                return;
            }

            for (const child of node.children) {
                traverse(child);
            }
        }

        traverse(container);
        results.sort((a, b) => a.top - b.top);
        return results;
    }''')

    # 获取下一页 URL（同时兼容桌面版与移动版）
    url_next = page.evaluate('''() => {
        if (typeof ReadParams !== 'undefined' && ReadParams && ReadParams.url_next) {
            return ReadParams.url_next;
        }
        if (typeof nextpage !== 'undefined' && nextpage) {
            return nextpage;
        }
        const links = Array.from(document.querySelectorAll('a'));
        for (const a of links) {
            const txt = a.textContent.trim();
            const href = a.getAttribute('href');
            if (txt === '下一页' || txt === '下一頁' || a.id === 'nextlink' || a.className.includes('nextlink')) {
                if (href && !href.startsWith('javascript')) {
                    return href;
                }
            }
        }
        return null;
    }''')
    full_next = None
    if url_next:
        full_next = url_next if url_next.startswith("http") else f"{BASE_DOMAIN}{url_next}"

    return items, full_next


def scrape_chapter_with_pagination(page, first_url):
    """
    抓取完整章节（自动循环遍历全部子分页，如 316496.html -> 316496_2.html 并去重合并）
    """
    all_items = []
    seen_texts = set()
    seen_imgs = set()

    curr_url = first_url
    subpage_idx = 1

    while curr_url:
        items, next_url = extract_subpage_items(page, curr_url)

        page_text_count = 0
        page_img_count = 0
        for item in items:
            itype = item["type"]
            if itype == "text":
                txt = item["text"]
                if txt and txt not in seen_texts:
                    seen_texts.add(txt)
                    all_items.append(item)
                    page_text_count += 1
            elif itype == "img":
                src = item["src"]
                if src not in seen_imgs:
                    seen_imgs.add(src)
                    all_items.append(item)
                    page_img_count += 1
            elif itype == "scene_break":
                all_items.append(item)

        print(f"    第 {subpage_idx} 页提取到 {page_text_count} 段落, {page_img_count} 插图")

        if next_url and is_same_chapter_url(first_url, next_url) and next_url != curr_url:
            curr_url = next_url
            subpage_idx += 1
            time.sleep(0.5)
        else:
            curr_url = None

    return all_items


def scrape_volume(novel_input, target_vol_param=None, custom_novel_name=None):
    """爬取指定分卷全部章节及子分页，并生成标准 EPUB"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    profile_dir = os.path.join(base_dir, ".edge_profile")

    catalog_url, novel_id, vol_target_from_url = normalize_input_url(novel_input)
    if not target_vol_param and vol_target_from_url:
        target_vol_param = vol_target_from_url

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            channel="msedge",
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox"
            ]
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # 客户端阻断重定向到失效域名
        page.add_init_script("""
            Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' });
            window.location.replace = function(url) { console.log('Blocked replace to:', url); };
        """)

        # 1. 获取目录与分卷列表
        novel_title, author, volumes = parse_catalog_volumes(page, catalog_url)
        if custom_novel_name:
            novel_title = custom_novel_name

        if not volumes:
            print("❌ 未在目录中解析到任何分卷，请检查网络或 Cloudflare 状态。")
            ctx.close()
            return None

        # 2. 定位目标分卷
        target_vol_idx = 1
        if target_vol_param:
            target_str = str(target_vol_param).strip()
            # 情况 A: 按 volume_id (如 328281) 精确匹配
            found = False
            for idx, v in enumerate(volumes, 1):
                if v.get("volume_id") and v["volume_id"] == target_str:
                    target_vol_idx = idx
                    found = True
                    break
            # 情况 B: 按分卷名称关键词模糊匹配（如 "9", "第9卷", "败北女角太多了！ 9"）
            if not found:
                for idx, v in enumerate(volumes, 1):
                    if target_str in v["volume_name"]:
                        target_vol_idx = idx
                        found = True
                        break
            # 情况 C: 纯数字在分卷序号范围内
            if not found and target_str.isdigit() and 1 <= int(target_str) <= len(volumes):
                target_vol_idx = int(target_str)
                found = True

        vol_info = volumes[target_vol_idx - 1]
        vol_name = vol_info["volume_name"]
        chapters = vol_info["chapters"]

        print(f"\n🚀 开始抓取目标分卷: [{vol_name}] (卷序号: {target_vol_idx}/{len(volumes)}, 共 {len(chapters)} 章)")

        # 3. 初始化保存目录
        safe_novel_name = re.sub(r'[\\/:*?"<>|]', "_", novel_title)
        safe_vol_name = re.sub(r'[\\/:*?"<>|]', "_", vol_name)
        safe_vol_name = safe_vol_name.replace(safe_novel_name, "").strip(" _-")
        if not safe_vol_name:
            safe_vol_name = f"第{target_vol_idx}卷"

        # 规范化卷名格式（如 "9" -> "第9卷"）
        if safe_vol_name.isdigit():
            safe_vol_name = f"第{safe_vol_name}卷"

        # 分级目录：novels/<小说名>/<分卷名>/
        output_dir = os.path.join(base_dir, "novels", safe_novel_name, safe_vol_name)
        images_dir = os.path.join(output_dir, "插图")
        full_text_file = os.path.join(output_dir, f"{safe_novel_name}_{safe_vol_name}_完整版.txt")

        os.makedirs(images_dir, exist_ok=True)

        all_text_lines = []
        total_imgs = 0

        # 4. 逐章抓取（含全部子页）
        for i, ch in enumerate(chapters, 1):
            ch_title = ch["title"]
            ch_url = ch["url"]
            print(f"\n[{i}/{len(chapters)}] 正在抓取: {ch_title} ({ch_url})")

            try:
                items = scrape_chapter_with_pagination(page, ch_url)
            except Exception as e:
                print(f"  ❌ 抓取失败: {e}")
                items = []

            ch_paragraphs = []
            ch_img_count = 0
            safe_ch_title = re.sub(r'[\\/:*?"<>|]', "_", ch_title)

            for item in items:
                itype = item["type"]
                if itype == "text":
                    ch_paragraphs.append(item["text"])
                elif itype == "scene_break":
                    symbol = item.get("symbol", "◇").strip()
                    if not symbol:
                        symbol = "◇"
                    ch_paragraphs.append(f"[场景分隔: {symbol}]")
                elif itype == "img":
                    img_url = item["src"]
                    ch_img_count += 1

                    ext = img_url.split(".")[-1].split("?")[0].lower()
                    if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
                        ext = "jpg"

                    img_filename = f"{safe_ch_title}_{ch_img_count}.{ext}"
                    img_path = os.path.join(images_dir, img_filename)

                    # 如果本地尚无此图片，尝试下载（带重试机制）
                    if not os.path.isfile(img_path) or os.path.getsize(img_path) < 1000:
                        for attempt in range(3):
                            try:
                                resp = ctx.request.get(
                                    img_url,
                                    headers={
                                        "Referer": "https://www.linovelib.com/",
                                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                                    },
                                    timeout=20000
                                )
                                if resp.status == 200 and len(resp.body()) > 500:
                                    with open(img_path, "wb") as f:
                                        f.write(resp.body())
                                    print(f"  🖼️ 保存插图: {img_filename} ({len(resp.body())//1024} KB)")
                                    total_imgs += 1
                                    break
                            except Exception as e:
                                if attempt == 2:
                                    print(f"  ⚠️ 下载插图失败: {e}")
                                else:
                                    time.sleep(1)
                    else:
                        total_imgs += 1
                        print(f"  🖼️ 插图已存在: {img_filename} ({os.path.getsize(img_path)//1024} KB)")

                    ch_paragraphs.append(f"[插图: {img_filename}]")

            # 组装文本
            all_text_lines.append(f"\n{'='*40}")
            all_text_lines.append(f"  {ch_title}")
            all_text_lines.append(f"{'='*40}\n")
            all_text_lines.extend(ch_paragraphs)

            print(f"  📝 本章合并完成: 共提取到 {len(ch_paragraphs)} 段落 / 标记 (包含 {ch_img_count} 张插图)")

            with open(full_text_file, "w", encoding="utf-8") as f:
                f.write("\n".join(all_text_lines))

            time.sleep(REQUEST_DELAY)

        ctx.close()

    print(f"\n🎉 抓取全部完成！")
    print(f"  文本保存于: {full_text_file}")
    print(f"  插图保存于: {images_dir} (共 {total_imgs} 张)")

    # 5. 设置全彩封面图
    color_cover = os.path.join(images_dir, "插图_1.jpg")
    if os.path.isfile(color_cover):
        import shutil
        shutil.copyfile(color_cover, os.path.join(output_dir, "封面.jpg"))
        print(f"  🎨 已将卷首全彩插图设为主封面: 封面.jpg")

    # 6. 生成标准 EPUB 电子书并覆盖旧版本
    print(f"\n📦 正在自动重新生成 EPUB 电子书...")
    out_epub = os.path.join(output_dir, f"{safe_novel_name}_{safe_vol_name}.epub")

    epub_path = generate_epub(
        volume_dir=output_dir,
        novel_title=novel_title,
        volume_title=safe_vol_name,
        author=author,
        output_file=out_epub
    )

    print(f"\n✨ 全部流程顺利结束！EPUB 电子书已生成: {epub_path}")
    return epub_path


def main():
    novel_url = sys.argv[1] if len(sys.argv) >= 2 else "https://www.linovelib.com/novel/3095/vol_328281.html"
    target_vol = sys.argv[2] if len(sys.argv) >= 3 else None
    custom_name = sys.argv[3] if len(sys.argv) >= 4 else None

    scrape_volume(novel_url, target_vol_param=target_vol, custom_novel_name=custom_name)


if __name__ == "__main__":
    main()
