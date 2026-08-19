"""
哔哩轻小说通用爬虫与 EPUB 一键打包流水线（日轻/韩轻全通用极速并发版）

功能特性：
1. 通用 URL 解析：支持全本目录、单卷链接（如 vol_308156.html）、小说主页及纯小说 ID 输入
2. 广告请求拦截（方案4）：拦截 Google AdSense、百度统计、CNZZ 等无用外链脚本与广告，大幅节约网络带宽与渲染等待
3. 多 Tab 章节异步并发（方案3）：多标签页同时并发抓取不同章节，速度倍增
4. 全子分页无损递归合并：自动探测每章 ReadParams.url_next 与 window.nextpage，合并长章节内所有分页（1/2, 2/2, 1/7...），彻底杜绝缺页与截断
5. 真实 DOM 渲染物理坐标排序：使用 getBoundingClientRect() 绝对 Y 坐标，精准锚定正文、场景分隔符与插图物理位置
6. 智能人机验证（Turnstile Stealth）：自动检测并突破 Cloudflare Turnstile 验证
7. 卷首全彩画廊与封面自动化：提取卷首彩插及角色卡，自动设置电子书封面（封面.jpg）
8. 结构化分层输出：严格保存于 novels/<小说名>/<分卷名>/ 目录，与代码本体解耦
9. 标准 EPUB 封装：自动生成并覆盖旧版本，包含目录导航、精美排版与插图清单
"""

import asyncio
import os
import re
import shutil
import sys
import time
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from to_epub import generate_epub

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DOMAIN = "https://www.linovelib.com"
CONCURRENT_TABS = 3  # 3~4 Tab 章节并发

AD_PATTERNS = [
    "googlesyndication", "doubleclick", "pagead2", "hm.baidu.com", "cnzz.com",
    "googletagmanager", "googletagservices", "adservice.google", "adsbygoogle",
    "bxb.im", "pos.baidu.com"
]


def is_ad_url(url):
    """检测 URL 是否为广告或追踪分析请求"""
    u = url.lower()
    return any(p in u for p in AD_PATTERNS)


def normalize_input_url(raw_url):
    """
    智能解析用户输入的各种 URL 形式：
    - https://www.linovelib.com/novel/3768/vol_308156.html
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


async def safe_goto(page, url, max_retries=3, timeout=35000):
    """安全导航带自动重试机制"""
    for attempt in range(max_retries):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            return True
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            await asyncio.sleep(1)


async def wait_for_turnstile(page, max_wait=25):
    """等待 Cloudflare Turnstile 验证通过，如遇复选框则尝试自动物理点击"""
    clicked = False
    for _ in range(max_wait):
        try:
            has_content = await page.evaluate("() => !!document.querySelector('#TextContent, #acontent, .volume, #volumes, .chapter-list')")
            if has_content:
                return True
        except Exception:
            pass

        if not clicked:
            for f in page.frames:
                if "turnstile" in f.url or "challenges.cloudflare.com" in f.url:
                    try:
                        b = await f.frame_element().bounding_box()
                        if b and b['width'] > 0:
                            cx = b['x'] + 35
                            cy = b['y'] + b['height'] / 2
                            print(f"  👆 检测到 Turnstile 验证，尝试自动点击 ({cx}, {cy})...")
                            await page.mouse.move(cx, cy, steps=8)
                            await page.wait_for_timeout(200)
                            await page.mouse.click(cx, cy)
                            clicked = True
                            break
                    except Exception:
                        pass
        await page.wait_for_timeout(500)
    return True


def is_same_chapter_url(base_url, next_url):
    """判断 next_url 是否属于 base_url 的同一章节分页（如 316496.html 与 316496_2.html）"""
    m1 = re.search(r"/(\d+)(?:_\d+)?\.html", base_url)
    m2 = re.search(r"/(\d+)(?:_\d+)?\.html", next_url)
    if m1 and m2:
        return m1.group(1) == m2.group(1)
    return False


def is_valid_chapter_url(url):
    """检验章节 URL 是否有效（过滤 javascript 伪链接与缺失占位符）"""
    if not url:
        return False
    u = str(url).strip().lower()
    if "javascript:" in u or "cid" in u or "/vol_" in u or "/catalog" in u:
        return False
    return bool(re.search(r"/\d+(?:_\d+)?\.html", u))


async def repair_volume_chapters(page, chapters):
    """
    章节失效时的正反向递归自愈修复算法：
    1. 反向修复 (Backward Repair)：当章节 N 失效时，向后寻找最近的有效章节 K，提取其阅读器 DOM 底部“上一页/上一章”链接逆向推导；
    2. 正向修复 (Forward Repair)：若无法反向修复，则向前寻找最近的有效章节 J，遍历至其末尾子页提取“下一页/下一章”链接正向推导。
    """
    total_chs = len(chapters)
    invalid_indices = [i for i, ch in enumerate(chapters) if not is_valid_chapter_url(ch.get("url"))]

    if not invalid_indices:
        return chapters

    print(f"\n⚠️ 检测到 {len(invalid_indices)} 个失效/缺失章节链接，启动正反向自愈修复算法...")

    for target_idx in invalid_indices:
        if is_valid_chapter_url(chapters[target_idx].get("url")):
            continue

        ch_name = chapters[target_idx]["title"]
        print(f"  🔧 正在尝试修复失效章节 [{target_idx+1}/{total_chs}] 《{ch_name}》...")

        # 策略 1: 反向递归修复 (Backward Fix) - 寻找到后方最近的有效章节并提取其“上一页”
        repaired = False
        for next_idx in range(target_idx + 1, total_chs):
            if is_valid_chapter_url(chapters[next_idx].get("url")):
                curr_k = next_idx
                while curr_k > target_idx:
                    k_url = chapters[curr_k]["url"]
                    await safe_goto(page, k_url, max_retries=2)
                    await wait_for_turnstile(page)

                    prev_url = await page.evaluate('''() => {
                        const links = Array.from(document.querySelectorAll('a'));
                        for (const a of links) {
                            const txt = a.textContent.trim();
                            const href = a.getAttribute('href');
                            if (txt === '上一页' || txt === '上一頁' || txt === '上一章' || a.id === 'prevlink' || (a.className && a.className.includes('prevlink'))) {
                                if (href && !href.startsWith('javascript')) return href;
                            }
                        }
                        const mlfy = document.querySelector('.mlfy_page a');
                        if (mlfy && mlfy.getAttribute('href') && !mlfy.getAttribute('href').startsWith('javascript')) {
                            return mlfy.getAttribute('href');
                        }
                        return null;
                    }''')

                    if prev_url:
                        full_prev = prev_url if prev_url.startswith("http") else f"{BASE_DOMAIN}{prev_url}"
                        if is_valid_chapter_url(full_prev):
                            clean_prev = re.sub(r"_(\d+)\.html$", ".html", full_prev)
                            chapters[curr_k - 1]["url"] = clean_prev
                            print(f"    ✨ 反向修复成功: [{curr_k}/{total_chs}] 《{chapters[curr_k-1]['title']}》 -> {clean_prev}")
                            curr_k -= 1
                        else:
                            break
                    else:
                        break

                if is_valid_chapter_url(chapters[target_idx].get("url")):
                    repaired = True
                    break

        # 策略 2: 正向递归修复 (Forward Fix) - 从前方有效章节末尾提取“下一页”
        if not repaired:
            for prev_idx in range(target_idx - 1, -1, -1):
                if is_valid_chapter_url(chapters[prev_idx].get("url")):
                    curr_j = prev_idx
                    while curr_j < target_idx:
                        j_url = chapters[curr_j]["url"]
                        last_subpage = j_url
                        while last_subpage:
                            await safe_goto(page, last_subpage, max_retries=2)
                            await wait_for_turnstile(page)
                            next_url = await page.evaluate('''() => {
                                if (typeof ReadParams !== 'undefined' && ReadParams && ReadParams.url_next) return ReadParams.url_next;
                                if (typeof nextpage !== 'undefined' && nextpage) return nextpage;
                                const links = Array.from(document.querySelectorAll('a'));
                                for (const a of links) {
                                    const txt = a.textContent.trim();
                                    const href = a.getAttribute('href');
                                    if (txt === '下一页' || txt === '下一頁' || txt === '下一章' || a.id === 'nextlink' || (a.className && a.className.includes('nextlink'))) {
                                        if (href && !href.startsWith('javascript')) return href;
                                    }
                                }
                                return null;
                            }''')
                            if next_url:
                                full_next = next_url if next_url.startswith("http") else f"{BASE_DOMAIN}{next_url}"
                                if is_same_chapter_url(j_url, full_next) and full_next != last_subpage:
                                    last_subpage = full_next
                                else:
                                    clean_next = re.sub(r"_(\d+)\.html$", ".html", full_next)
                                    if is_valid_chapter_url(clean_next):
                                        chapters[curr_j + 1]["url"] = clean_next
                                        print(f"    ✨ 正向修复成功: [{curr_j+2}/{total_chs}] 《{chapters[curr_j+1]['title']}》 -> {clean_next}")
                                        curr_j += 1
                                    break
                            else:
                                break

                    if is_valid_chapter_url(chapters[target_idx].get("url")):
                        repaired = True
                        break

        if not is_valid_chapter_url(chapters[target_idx].get("url")):
            print(f"    ⚠️ 章节 《{ch_name}》 无法自动推导修复，可能已被完全下架。")

    return chapters


async def parse_catalog_volumes(page, catalog_url):
    """从目录页提取所有分卷及其所属章节列表（支持桌面版与响应式两种模板）"""
    print(f"正在访问目录页: {catalog_url} ...")
    await safe_goto(page, catalog_url, max_retries=3, timeout=45000)
    await wait_for_turnstile(page)

    try:
        await page.wait_for_selector(".volume, #volumes, .chapter-list, .dir-list, .volume-list", timeout=8000)
    except Exception:
        pass
    await page.wait_for_timeout(300)

    soup = BeautifulSoup(await page.content(), "html.parser")

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


async def extract_subpage_items(page, subpage_url):
    """提取单张子页中的所有可见段落、插图及场景分隔符（按真实物理渲染 Y 坐标排序）"""
    items = []
    for _ in range(3):
        await safe_goto(page, subpage_url, max_retries=2, timeout=35000)
        await wait_for_turnstile(page)

        try:
            await page.wait_for_selector("#TextContent p, #acontent p, .read-content p", timeout=2000)
        except Exception:
            pass

        # 滚动到底部触发正文与插图完整渲染
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(50)

        items = await page.evaluate('''() => {
            const container = document.querySelector('#TextContent') || document.querySelector('#acontent') || document.querySelector('.read-content');
            if (!container) return [];

            const scrollY = window.scrollY || window.pageYOffset || 0;
            const results = [];
            const seenImgs = new Set();

            function traverse(node) {
                if (!node || node.nodeType !== 1) return;

                // 忽略隐藏的黑白插图容器、广告及折叠区域（避免彩页重复收录正文黑白插图）
                if (node.id === 'hidden-images' || node.id === 'show-more-images') return;
                if (node.className && typeof node.className === 'string') {
                    if (node.className.includes('hidden-images') || node.className.includes('dag') || node.className.includes('google-auto-placed')) {
                        return;
                    }
                }

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
                    if (text && !text.includes('adsbygoogle') && !text.includes('加載失敗') && !text.includes('※黑白插图已内嵌正文※') && !text.includes('读者请无视')) {
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
                    } else if (imgs.length === 0 && !text.includes('※黑白插图已内嵌正文※') && !text.includes('读者请无视')) {
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
                        if (text && !text.includes('adsbygoogle') && !text.includes('內容加載失敗') && !text.includes('内容加载失败') && !text.includes('※黑白插图已内嵌正文※') && !text.includes('点击可查看完整插图') && !text.includes('读者请无视') && !text.includes('以下为告示')) {
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

        if items:
            break
        await asyncio.sleep(0.5)

    # 获取下一页 URL（同时兼容桌面版与移动版）
    url_next = await page.evaluate('''() => {
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


async def scrape_chapter_with_pagination(page, first_url):
    """
    抓取完整章节（自动循环遍历全部子分页，如 316496.html -> 316496_2.html 并去重合并）
    """
    all_items = []
    seen_texts = set()
    seen_imgs = set()

    curr_url = first_url
    subpage_idx = 1

    while curr_url:
        items, next_url = await extract_subpage_items(page, curr_url)

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

        if next_url and is_same_chapter_url(first_url, next_url) and next_url != curr_url:
            curr_url = next_url
            subpage_idx += 1
        else:
            curr_url = None

    return all_items


async def scrape_volume_async(novel_input, target_vol_param=None, custom_novel_name=None):
    """异步多 Tab 并发爬取指定分卷全部章节及子分页，并生成标准 EPUB"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    profile_dir = os.path.join(base_dir, ".edge_profile")

    catalog_url, novel_id, vol_target_from_url = normalize_input_url(novel_input)
    if not target_vol_param and vol_target_from_url:
        target_vol_param = vol_target_from_url

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            channel="msedge",
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox"
            ],
            ignore_default_args=["--enable-automation"]
        )

        # 方案 4：拦截广告及统计请求，加速网络
        async def route_intercept(route):
            if is_ad_url(route.request.url):
                await route.abort()
            else:
                await route.continue_()

        await ctx.route("**/*", route_intercept)

        main_page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # 客户端阻断重定向到失效域名与防反爬识别
        await main_page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' });
            window.location.replace = function(url) { console.log('Blocked replace to:', url); };
        """)

        # 1. 获取目录与分卷列表
        novel_title, author, volumes = await parse_catalog_volumes(main_page, catalog_url)
        if custom_novel_name:
            novel_title = custom_novel_name

        if not volumes:
            print("❌ 未在目录中解析到任何分卷，请检查网络或 Cloudflare 状态。")
            await ctx.close()
            return None

        # 2. 定位目标分卷
        target_vol_idx = 1
        if target_vol_param:
            target_str = str(target_vol_param).strip()
            # 情况 A: 按 volume_id (如 328281) 精确匹配
            found = False
            for idx, v in enumerate(volumes, 1):
                if v.get("volume_id") and (v["volume_id"] == target_str or f"vol_{v['volume_id']}" == target_str):
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

        # 执行失效/缺失章节链接正反向自愈修复
        chapters = await repair_volume_chapters(main_page, chapters)

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

        # 4. 方案 3：创建多 Tab Worker 并发抓取章节
        valid_chapters = [ch for ch in chapters if is_valid_chapter_url(ch.get("url"))]
        num_workers = min(CONCURRENT_TABS, len(valid_chapters)) if valid_chapters else 1
        worker_pages = [main_page]
        for _ in range(num_workers - 1):
            wp = await ctx.new_page()
            await wp.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => false });
                Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' });
                window.location.replace = function(url) { console.log('Blocked replace to:', url); };
            """)
            worker_pages.append(wp)

        task_queue = asyncio.Queue()
        for idx, ch in enumerate(chapters, 1):
            if is_valid_chapter_url(ch.get("url")):
                await task_queue.put((idx, ch))

        chapter_raw_results = {}
        t_crawl_start = time.time()

        async def chapter_worker(worker_id, page):
            while not task_queue.empty():
                idx, ch = await task_queue.get()
                ch_title = ch["title"]
                ch_url = ch["url"]
                t0 = time.time()
                print(f"  [Tab {worker_id+1}] 正在抓取 [{idx}/{len(chapters)}]: {ch_title} ...")

                try:
                    items = await scrape_chapter_with_pagination(page, ch_url)
                except Exception as e:
                    print(f"  ❌ [Tab {worker_id+1}] 抓取失败 {ch_title}: {e}")
                    items = []

                dur = time.time() - t0
                print(f"  ✅ [Tab {worker_id+1}] 完成 [{idx}/{len(chapters)}] {ch_title} (共 {len(items)} 条目, 耗时 {dur:.2f}s)")
                chapter_raw_results[idx] = (ch_title, items)
                task_queue.task_done()

        print(f"\n⚡ 启动 {num_workers} 个浏览器并发 Tab 协同抓取中...")
        await asyncio.gather(*[chapter_worker(i, worker_pages[i]) for i in range(num_workers)])
        crawl_duration = time.time() - t_crawl_start
        print(f"\n✨ 全部分卷章节内容抓取完毕！耗时: {crawl_duration:.2f}s (平均每章 {crawl_duration/len(chapters):.2f}s)")

        # 5. 按章节原本顺序装配段落与插图
        all_text_lines = []
        total_imgs = 0
        download_tasks = []

        for idx in range(1, len(chapters) + 1):
            if idx not in chapter_raw_results:
                continue
            ch_title, items = chapter_raw_results[idx]
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
                    download_tasks.append((img_url, img_path, img_filename))
                    ch_paragraphs.append(f"[插图: {img_filename}]")

            all_text_lines.append(f"\n{'='*40}")
            all_text_lines.append(f"  {ch_title}")
            all_text_lines.append(f"{'='*40}\n")
            all_text_lines.extend(ch_paragraphs)

        with open(full_text_file, "w", encoding="utf-8") as f:
            f.write("\n".join(all_text_lines))

        # 6. 并发下载插图
        print(f"\n🖼️ 正在并发下载与校对 {len(download_tasks)} 张插图...")
        async def download_image(img_url, save_path, filename):
            if os.path.isfile(save_path) and os.path.getsize(save_path) > 1000:
                return True
            for attempt in range(3):
                try:
                    resp = await ctx.request.get(
                        img_url,
                        headers={
                            "Referer": "https://www.linovelib.com/",
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                        },
                        timeout=15000
                    )
                    if resp.status == 200:
                        body = await resp.body()
                        if len(body) > 500:
                            with open(save_path, "wb") as f:
                                f.write(body)
                            print(f"  🖼️ 保存插图: {filename} ({len(body)//1024} KB)")
                            return True
                except Exception:
                    pass
                await asyncio.sleep(0.5)
            return False

        img_results = await asyncio.gather(*[download_image(u, p, fn) for u, p, fn in download_tasks])
        total_imgs = sum(1 for r in img_results if r)

        await ctx.close()

    print(f"\n🎉 抓取与下载全部完成！")
    print(f"  文本保存于: {full_text_file}")
    print(f"  插图保存于: {images_dir} (共 {total_imgs} 张)")

    # 7. 设置全彩封面图
    color_cover = os.path.join(images_dir, "插图_1.jpg")
    if os.path.isfile(color_cover):
        shutil.copyfile(color_cover, os.path.join(output_dir, "封面.jpg"))
        print(f"  🎨 已将卷首全彩插图设为主封面: 封面.jpg")

    # 8. 生成标准 EPUB 电子书并覆盖旧版本
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


def scrape_volume(novel_input, target_vol_param=None, custom_novel_name=None):
    """同步入口封装"""
    return asyncio.run(scrape_volume_async(novel_input, target_vol_param, custom_novel_name))


def main():
    novel_url = sys.argv[1] if len(sys.argv) >= 2 else "https://www.linovelib.com/novel/3768/vol_308156.html"
    target_vol = sys.argv[2] if len(sys.argv) >= 3 else None
    custom_name = sys.argv[3] if len(sys.argv) >= 4 else None

    scrape_volume(novel_url, target_vol_param=target_vol, custom_novel_name=custom_name)


if __name__ == "__main__":
    main()
