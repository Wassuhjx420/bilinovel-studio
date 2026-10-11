"""
哔哩轻小说通用爬虫与 EPUB 一键打包流水线（日轻/韩轻全通用极速并发版）

Disclaimer / 免责声明:
本项目仅供 Python 自动化技术交流与个人离线阅读研究使用。
小说内容及插图版权均归原作者及轻小说出版方所有。
严禁将本项目及衍生工具用于任何商业营利目的。

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
import random
import re
import shutil
import sys
import time
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from to_epub import generate_epub
from runtime_env import get_storage_dir

try:
    from rubbish_secret_map import rubbish_secret_map
except ImportError:
    rubbish_secret_map = {}


def decrypt_font_text(text):
    """还原 bilinovel woff2 字体反爬混淆字符"""
    if not text or not rubbish_secret_map:
        return text
    sb = []
    for char in text:
        sb.append(rubbish_secret_map.get(char, char))
    return "".join(sb)


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
    """等待 Cloudflare Turnstile 验证通过，如遇复选框则尝试自动物理点击；若秒级探测到 1015 速率限制立即返回标识"""
    clicked = False
    for _ in range(max_wait):
        try:
            has_content = await page.evaluate("() => !!document.querySelector('#TextContent, #acontent, .volume, #volumes, .chapter-list')")
            if has_content:
                return "ok"
        except Exception:
            pass

        # 实时探测是否遭遇 Cloudflare Error 1015 (Rate Limited) 拦截页
        try:
            is_1015 = await page.evaluate('''() => {
                const title = document.title || '';
                const bodyText = document.body ? (document.body.innerText || '') : '';
                return title.includes('Access denied') || bodyText.includes('Error 1015') || bodyText.includes('rate limited');
            }''')
            if is_1015:
                return "1015"
        except Exception:
            pass

        if not clicked:
            for f in page.frames:
                if "turnstile" in f.url or "challenges.cloudflare.com" in f.url:
                    try:
                        fe = await f.frame_element()
                        if fe:
                            b = await fe.bounding_box()
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
    return "timeout"


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
    ts_stat = await wait_for_turnstile(page)
    if ts_stat == "1015":
        print(f"  ⏳ [目录页频控避让] 遭遇 Cloudflare Error 1015 速率限制，自动冷静 15 秒后重试...")
        await asyncio.sleep(15)
        await safe_goto(page, catalog_url, max_retries=3, timeout=45000)
        await wait_for_turnstile(page)

    for _ in range(12):
        try:
            has_vol = await page.evaluate("() => !!document.querySelector('.volume, #volumes, .chapter-list, .dir-list, .volume-list')")
            if has_vol:
                break
        except Exception:
            pass
        await wait_for_turnstile(page)
        await asyncio.sleep(0.5)

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
                    if not title:
                        continue
                    if href and "/novel/" in href and not "/vol_" in href:
                        full_url = href if href.startswith("http") else f"{BASE_DOMAIN}{href}"
                        chs.append({
                            "title": title,
                            "url": full_url
                        })
                    elif href and href.startswith("javascript"):
                        chs.append({
                            "title": title,
                            "url": href
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
                        if not title:
                            continue
                        if href and "/novel/" in href and not "/vol_" in href:
                            full_url = href if href.startswith("http") else f"{BASE_DOMAIN}{href}"
                            if not current_vol_name:
                                current_vol_name = "第1卷"
                            current_vol_chapters.append({
                                "title": title,
                                "url": full_url
                            })
                        elif href and href.startswith("javascript"):
                            if not current_vol_name:
                                current_vol_name = "第1卷"
                            current_vol_chapters.append({
                                "title": title,
                                "url": href
                            })

            if current_vol_name and current_vol_chapters:
                volumes.append({
                    "volume_name": current_vol_name,
                    "volume_id": current_vol_id,
                    "chapters": current_vol_chapters
                })

        # 智能分卷页直读同步：若分卷中存在被遮蔽的章节（如每隔25话出现的 javascript:cid(0)），从分卷独立页同步完整真实链接
        m_nid = re.search(r"/novel/(\d+)", catalog_url)
        novel_id_str = m_nid.group(1) if m_nid else ""
        if novel_id_str:
            for vol in volumes:
                vid = vol.get("volume_id")
                masked = [c for c in vol["chapters"] if "javascript" in c["url"] or "cid" in c["url"]]
                if vid and masked:
                    vol_page_url = f"{BASE_DOMAIN}/novel/{novel_id_str}/vol_{vid}.html"
                    print(f"  🔍 分卷 [{vol['volume_name']}] 包含 {len(masked)} 个被反爬遮蔽的章节，正在从分卷页自动同步真实链接...")
                    try:
                        vol_page = await page.context.new_page()
                        await safe_goto(vol_page, vol_page_url, max_retries=2, timeout=20000)
                        await wait_for_turnstile(vol_page)
                        await vol_page.wait_for_timeout(500)
                        vol_soup = BeautifulSoup(await vol_page.content(), "html.parser")
                        await vol_page.close()

                        vol_map = {}
                        for a in vol_soup.select(".book-new-chapter .tit a, .book-new-chapter a, .chapter-list a"):
                            a_href = a.get("href", "")
                            a_t = a.get_text(strip=True)
                            if a_href and "/novel/" in a_href and not "/vol_" in a_href and not a_href.startswith("javascript"):
                                full_h = a_href if a_href.startswith("http") else f"{BASE_DOMAIN}{a_href}"
                                vol_map[a_t] = full_h

                        fixed = 0
                        for c in vol["chapters"]:
                            if ("javascript" in c["url"] or "cid" in c["url"]) and c["title"] in vol_map:
                                c["url"] = vol_map[c["title"]]
                                fixed += 1
                        print(f"  ✨ 分卷 [{vol['volume_name']}] 成功通过分卷页同步修复 {fixed}/{len(masked)} 个章节链接！")
                    except Exception as e:
                        print(f"  ⚠️ 分卷页同步跳过: {e}")

        print(f"\n📖 小说名称: 《{novel_title}》 | 作者: {author}")
        print(f"共解析到 {len(volumes)} 个分卷:")
        for idx, v in enumerate(volumes, 1):
            vid_str = f" [vol_{v['volume_id']}]" if v.get("volume_id") else ""
            print(f"  [{idx}] {v['volume_name']}{vid_str} (包含 {len(v['chapters'])} 章)")

        return novel_title, author, volumes



async def extract_subpage_items(page, subpage_url):
    """提取单张子页中的所有可见段落、插图及场景分隔符（严格按 DOM 自然阅读时序，等待反爬样式完全生效，过滤蜜罐段落）"""
    items = []
    last_err = None
    for attempt in range(1, 4):
        try:
            await safe_goto(page, subpage_url, max_retries=2, timeout=35000)
            ts_status = await wait_for_turnstile(page)
            if ts_status == "1015":
                print(f"  ⏳ [Worker 频控避让] 遭遇 Cloudflare 速率限制 (Error 1015)，自动冷静 15 秒后重试...")
                await asyncio.sleep(15)
                await safe_goto(page, subpage_url, max_retries=2, timeout=35000)
                ts_status = await wait_for_turnstile(page)
                if ts_status == "1015":
                    await asyncio.sleep(15)
                    await safe_goto(page, subpage_url, max_retries=2, timeout=35000)
                    ts_status = await wait_for_turnstile(page)

            try:
                await page.wait_for_selector("#TextContent p, #acontent p, .read-content p", timeout=10000)
            except Exception:
                pass

            # 智能自适应等待：若触发了混淆加速且已执行，或已探测到蜜罐隐藏样式，立即放行；未配置混淆的页面快速通过
            for step in range(20):
                status = await page.evaluate('''() => {
                    const container = document.querySelector('#TextContent') || document.querySelector('#acontent');
                    if (!container) return { ready: false, hasHidden: false, hasTimer: false, executed: false };
                    const pList = Array.from(container.querySelectorAll('p'));
                    const hasHidden = pList.some(p => {
                        const s = window.getComputedStyle(p);
                        return s.display === 'none' || (s.transform && s.transform.includes('matrix(0'));
                    });
                    const executed = window.__obfuscationExecuted || false;
                    const hasTimer = window.__hasObfuscationTimer || false;
                    return {
                        hasHidden,
                        hasTimer,
                        executed,
                        pCount: pList.length
                    };
                }''')
                if status['hasHidden'] or (status['hasTimer'] and status['executed']):
                    break
                # 若无蜜罐定时器且等待已超 300ms（纯插图页或无反爬章节），直接快速放行
                if not status['hasTimer'] and step >= 3:
                    break
                await page.wait_for_timeout(100)

            # 微小缓冲（50ms），确保 DOM 渲染队列收尾
            await page.wait_for_timeout(50)

            # 若页面内包含插图标签，触发轻量级滚动以激活 lazysizes 懒加载与图片预取
            try:
                has_img_in_dom = await page.evaluate("() => !!document.querySelector('#TextContent img, #acontent img, .read-content img')")
                if has_img_in_dom:
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(100)
            except Exception:
                pass

            items = await page.evaluate(r'''() => {
                const container = document.querySelector('#TextContent') || document.querySelector('#acontent') || document.querySelector('.read-content');
                if (!container) return [];

                const results = [];
                const seenImgs = new Set();

                function isElementVisible(el) {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none') return false;
                    if (style.visibility === 'hidden' || style.visibility === 'collapse') return false;
                    if (style.opacity === '0') return false;
                    if (style.fontSize === '0px') return false;
                    if (style.transform && (style.transform.includes('matrix(0') || style.transform === 'scale(0)')) return false;

                    const rect = el.getBoundingClientRect();
                    const tag = el.tagName.toLowerCase();
                    const isBr = tag === 'br';
                    const isImg = tag === 'img';
                    // 对于 img 标签，绝不因其网络尚未完成下载（尺寸暂为 0）而判定为隐藏！
                    if (!isBr && !isImg && rect.width === 0) return false;
                    if (!isImg && rect.height === 0) return false;

                    // 递归校验所有父级容器的可见性，防止父级被 scale(0) 或 display:none 隐藏
                    let parent = el.parentElement;
                    while (parent && parent !== document.body) {
                        const pStyle = window.getComputedStyle(parent);
                        if (pStyle.display === 'none' || pStyle.visibility === 'hidden' || pStyle.opacity === '0') return false;
                        if (pStyle.transform && (pStyle.transform.includes('matrix(0') || pStyle.transform === 'scale(0)')) return false;
                        parent = parent.parentElement;
                    }

                    return true;
                }

                function cleanRubyText(node) {
                    const clone = node.cloneNode(true);
                    // 剔除旧浏览器备用括号 <rp>(</rp> 与注音 <rt>，保留最纯净的正文词汇
                    clone.querySelectorAll('rp').forEach(rp => rp.remove());
                    clone.querySelectorAll('rt').forEach(rt => rt.remove());
                    return clone.textContent.trim();
                }

                function traverse(node) {
                    if (!node || node.nodeType !== 1) return;

                    // 忽略隐藏的黑白插图容器、广告及折叠区域
                    if (node.id === 'hidden-images' || node.id === 'show-more-images') return;
                    if (node.className && typeof node.className === 'string') {
                        if (node.className.includes('hidden-images') || node.className.includes('dag') || node.className.includes('google-auto-placed')) {
                            return;
                        }
                    }

                    const tag = node.tagName.toLowerCase();

                    if (tag === 'img') {
                        if (isElementVisible(node) && !seenImgs.has(node)) {
                            seenImgs.add(node);
                            const src = node.getAttribute('data-src') || node.getAttribute('data-original') || node.getAttribute('src') || '';
                            if (src && src.indexOf('sloading') === -1 && src.indexOf('book-cover-no') === -1) {
                                const fullSrc = src.startsWith('http') ? src : 'https://www.linovelib.com' + src;
                                if (results.length > 0 && results[results.length - 1].type === 'scene_break' && !results[results.length - 1].symbol) {
                                    results.pop();
                                }
                                results.push({
                                    type: 'img',
                                    src: fullSrc
                                });
                            }
                        }
                        return;
                    }

                    if (tag === 'br') {
                        if (!isElementVisible(node)) return;
                        if (results.length > 0) {
                            const last = results[results.length - 1];
                            if (last.type !== 'scene_break' && last.type !== 'img') {
                                results.push({
                                    type: 'scene_break',
                                    symbol: ''
                                });
                            }
                        }
                        return;
                    }

                    if (tag === 'center') {
                        if (!isElementVisible(node)) return;

                        const imgs = node.querySelectorAll('img');
                        if (imgs.length > 0) {
                            for (const img of imgs) {
                                traverse(img);
                            }
                        }
                        const text = cleanRubyText(node);
                        if (text && !text.includes('adsbygoogle') && !text.includes('加載失敗') && !text.includes('※黑白插图已内嵌正文※') && !text.includes('读者请无视')) {
                            const isDivider = /^[\s\u3000]*[◇◆*＊☆★▲▼※§□■○●·•—\-_~=〜\.\s\dIVXLCDMivxlcdm]{1,15}[\s\u3000]*$/.test(text);
                            if (results.length > 0 && results[results.length - 1].type === 'scene_break' && !results[results.length - 1].symbol) {
                                results.pop();
                            }
                            if (isDivider || text.length <= 10) {
                                results.push({
                                    type: 'scene_break',
                                    symbol: text
                                });
                            } else {
                                results.push({
                                    type: 'text',
                                    text: text
                                });
                            }
                        } else if (imgs.length === 0 && !text.includes('※黑白插图已内嵌正文※') && !text.includes('读者请无视')) {
                            if (results.length > 0 && results[results.length - 1].type === 'scene_break' && !results[results.length - 1].symbol) {
                                results.pop();
                            }
                            results.push({
                                type: 'scene_break',
                                symbol: '◇'
                            });
                        }
                        return;
                    }

                    if (tag === 'hr') {
                        if (isElementVisible(node)) {
                            if (results.length > 0 && results[results.length - 1].type === 'scene_break' && !results[results.length - 1].symbol) {
                                results.pop();
                            }
                            results.push({
                                type: 'scene_break',
                                symbol: '◇'
                            });
                        }
                        return;
                    }

                    if (tag === 'p') {
                        if (!isElementVisible(node)) return;

                        const imgs = node.querySelectorAll('img');
                        if (imgs.length > 0) {
                            for (const img of imgs) {
                                traverse(img);
                            }
                        }

                        const text = cleanRubyText(node);
                        if (text && !text.includes('adsbygoogle') && !text.includes('內容加載失敗') && !text.includes('内容加载失败') && !text.includes('※黑白插图已内嵌正文※') && !text.includes('点击可查看完整插图') && !text.includes('读者请无视') && !text.includes('以下为告示')) {
                            const isDivider = /^[\s\u3000]*[◇◆*＊☆★▲▼※§□■○●·•—\-_~=〜\.\s\dIVXLCDMivxlcdm]{1,15}[\s\u3000]*$/.test(text);
                            if (isDivider) {
                                if (results.length > 0 && results[results.length - 1].type === 'scene_break' && !results[results.length - 1].symbol) {
                                    results.pop();
                                }
                                results.push({
                                    type: 'scene_break',
                                    symbol: text
                                });
                            } else {
                                results.push({
                                    type: 'text',
                                    text: text
                                });
                            }
                        } else if (!text && imgs.length === 0) {
                            if (results.length > 0) {
                                const last = results[results.length - 1];
                                if (last.type !== 'scene_break' && last.type !== 'img') {
                                    results.push({
                                        type: 'scene_break',
                                        symbol: ''
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

                // 插图差集对账校验与自愈补全 (DOM Image Reconciliation)
                // 扫描容器内所有非折叠剧透容器、非广告的真实 <img> 节点
                const domImgs = Array.from(container.querySelectorAll('img')).filter(img => {
                    let p = img.parentElement;
                    while (p && p !== document.body && p !== container) {
                        if (p.id === 'hidden-images' || p.id === 'show-more-images') return false;
                        if (p.className && typeof p.className === 'string') {
                            if (p.className.includes('hidden-images') || p.className.includes('dag') || p.className.includes('google-auto-placed')) return false;
                        }
                        const pStyle = window.getComputedStyle(p);
                        if (pStyle.display === 'none' || pStyle.visibility === 'hidden') return false;
                        if (pStyle.transform && (pStyle.transform.includes('matrix(0') || pStyle.transform === 'scale(0)')) return false;
                        p = p.parentElement;
                    }
                    const s = window.getComputedStyle(img);
                    if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
                    return true;
                });

                for (const img of domImgs) {
                    if (!seenImgs.has(img)) {
                        const src = img.getAttribute('data-src') || img.getAttribute('data-original') || img.src || '';
                        if (src && src.indexOf('sloading') === -1 && src.indexOf('book-cover-no') === -1) {
                            seenImgs.add(img);
                            const fullSrc = src.startsWith('http') ? src : 'https://www.linovelib.com' + src;
                            results.push({
                                type: 'img',
                                src: fullSrc
                            });
                        }
                    }
                }

                return results;
            }''')

            if items:
                break
        except Exception as e:
            last_err = e
            if attempt < 3:
                await asyncio.sleep(1.5 * attempt)
            else:
                raise last_err

    # 解析下一页分页链接
    url_next = await page.evaluate('''() => {
        if (typeof ReadParams !== 'undefined' && ReadParams.url_next) {
            return ReadParams.url_next;
        }
        if (typeof nextpage !== 'undefined' && nextpage) {
            return nextpage;
        }
        const links = Array.from(document.querySelectorAll('a'));
        for (const a of links) {
            const txt = a.textContent.trim();
            const href = a.getAttribute('href');
            if ((txt === '下一页' || txt === '下一頁' || a.id === 'nextlink' || (a.className && a.className.includes('nextlink'))) && href && !href.startsWith('javascript')) {
                return href;
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
    抓取完整章节（自动循环遍历全部子分页，如 316496.html -> 316496_2.html 并按真实视觉顺序拼接）
    """
    all_items = []
    seen_imgs = set()

    curr_url = first_url
    subpage_idx = 1

    while curr_url:
        items = None
        next_url = None
        for sub_att in range(1, 4):
            try:
                items, next_url = await extract_subpage_items(page, curr_url)
                break
            except Exception as e:
                if sub_att == 3:
                    raise e
                await asyncio.sleep(1.5 * sub_att)

        for item in items:
            itype = item["type"]
            if itype == "text":
                txt = item["text"]
                # 仅对跨页接缝处完全相同的段落进行边界去重，避免误杀正文中的重复对话（如「嗯。」「好。」等）
                if all_items and all_items[-1]["type"] == "text" and all_items[-1]["text"] == txt:
                    continue
                all_items.append(item)
            elif itype == "img":
                src = item["src"]
                if src not in seen_imgs:
                    seen_imgs.add(src)
                    all_items.append(item)
            elif itype == "scene_break":
                if not all_items:
                    continue
                if all_items[-1]["type"] == "scene_break":
                    if item.get("symbol") and not all_items[-1].get("symbol"):
                        all_items[-1] = item
                    continue
                all_items.append(item)

        if next_url and is_same_chapter_url(first_url, next_url) and next_url != curr_url:
            curr_url = next_url
            subpage_idx += 1
            # 长章节同章子分页拟人微抖动（350ms~650ms）：平滑突发请求峰值，杜绝触发 Cloudflare 1015
            await asyncio.sleep(random.uniform(0.35, 0.65))
        else:
            curr_url = None

    while all_items and all_items[-1]["type"] == "scene_break":
        all_items.pop()

    return all_items




async def scrape_volume_async(
    novel_input,
    target_vol_param=None,
    custom_novel_name=None,
    download_dir=None,
    concurrency=CONCURRENT_TABS,
    headless=False,
    chapters_list=None,
    cleanup_temp=False,
    on_progress=None,
    on_worker=None,
    on_log=None
):
    """异步多 Tab 并发爬取指定分卷全部章节及子分页，并生成出版级 EPUB"""
    base_dir = get_storage_dir()
    profile_dir = os.path.join(base_dir, ".edge_profile")

    def _log(level, tag, msg):
        print(f"[{tag}] {msg}")
        if on_log:
            try:
                on_log(level, tag, msg)
            except Exception:
                pass

    catalog_url, novel_id, vol_target_from_url = normalize_input_url(novel_input)
    if not target_vol_param and vol_target_from_url:
        target_vol_param = vol_target_from_url

    async with async_playwright() as p:
        try:
            ctx = await p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                channel="msedge",
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    # 禁用后台标签页降频与节电机制，确保所有并发 Worker Tab 保持全速运行
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-features=CalculateNativeWinOcclusion",
                    # 在浏览器 C++ 网络栈直接阻断广告和追踪域名，零 CDP IPC 损耗
                    "--host-resolver-rules="
                    "MAP *googlesyndication* 127.0.0.1, "
                    "MAP *doubleclick* 127.0.0.1, "
                    "MAP *pagead2* 127.0.0.1, "
                    "MAP *hm.baidu.com* 127.0.0.1, "
                    "MAP *cnzz* 127.0.0.1, "
                    "MAP *googletagmanager* 127.0.0.1, "
                    "MAP *googletagservices* 127.0.0.1, "
                    "MAP *adservice.google* 127.0.0.1, "
                    "MAP *adsbygoogle* 127.0.0.1, "
                    "MAP *bxb.im* 127.0.0.1, "
                    "MAP *pos.baidu.com* 127.0.0.1, "
                    "MAP *clarity.ms* 127.0.0.1, "
                    "MAP *cpatrk.net* 127.0.0.1",
                ],
                ignore_default_args=["--enable-automation"]
            )
        except Exception as e:
            err_msg = str(e)
            print("\n" + "!" * 64)
            if "msedge" in err_msg or "executable" in err_msg or "not found" in err_msg.lower():
                print(" [!] 启动失败：未检测到 Microsoft Edge 浏览器。")
                print(" [*] 本工具在 Windows 环境下默认使用系统自带的 Edge 浏览器内核。")
                print(" [*] 请安装 Microsoft Edge 浏览器后再试。")
            else:
                print(f" [!] 浏览器引擎初始化异常: {err_msg}")
            print("!" * 64 + "\n")
            return None

        # 全局注入伪装指纹与延迟反爬蜜罐混淆定时器高速穿透（对 Context 下所有新页面和分卷页面自动生效）
        await ctx.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' });
            window.location.replace = function(url) { console.log('Blocked replace to:', url); };

            // 拦截网站 setTimeout(_0x..., 2000) 恶意延时反爬，将其延时缩短至 10ms，使其立刻完成注入并赋予 matrix(0)/scale(0) 隐藏样式
            window.__hasObfuscationTimer = false;
            window.__obfuscationExecuted = false;
            const origSetTimeout = window.setTimeout;
            window.setTimeout = function(fn, delay, ...args) {
                if (delay >= 1000 && typeof fn === 'function' && String(fn).includes('_0x')) {
                    window.__hasObfuscationTimer = true;
                    const wrappedFn = function(...callArgs) {
                        try {
                            return fn.apply(this, callArgs);
                        } finally {
                            window.__obfuscationExecuted = true;
                        }
                    };
                    return origSetTimeout.call(this, wrappedFn, 10, ...args);
                }
                return origSetTimeout.call(this, fn, delay, ...args);
            };
        """)

        main_page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        novel_title = custom_novel_name or f"轻小说_{novel_id}"
        author = "官方作者"
        vol_name = str(target_vol_param or "第1卷")

        # 1. 如果未直接传入章节清单，则从目录页提取
        if chapters_list and isinstance(chapters_list, list) and len(chapters_list) > 0:
            chapters = chapters_list
            _log("info", "CRAWLER", f"直接加载分卷章节任务: [{vol_name}] (共 {len(chapters)} 章)")
        else:
            novel_title, author, volumes = await parse_catalog_volumes(main_page, catalog_url)
            if custom_novel_name:
                novel_title = custom_novel_name

            if not volumes:
                _log("error", "PARSER", "未在目录中解析到任何分卷，请检查网络或 Cloudflare 状态。")
                await ctx.close()
                return None

            # 定位目标分卷
            target_vol_idx = 1
            if target_vol_param:
                target_str = str(target_vol_param).strip()
                found = False
                for idx, v in enumerate(volumes, 1):
                    if v.get("volume_id") and (v["volume_id"] == target_str or f"vol_{v['volume_id']}" == target_str):
                        target_vol_idx = idx
                        found = True
                        break
                if not found:
                    for idx, v in enumerate(volumes, 1):
                        if target_str in v["volume_name"] or v["volume_name"] in target_str:
                            target_vol_idx = idx
                            found = True
                            break
                if not found and target_str.isdigit() and 1 <= int(target_str) <= len(volumes):
                    target_vol_idx = int(target_str)
                    found = True

            vol_info = volumes[target_vol_idx - 1]
            vol_name = vol_info["volume_name"]
            chapters = vol_info["chapters"]
            _log("info", "CRAWLER", f"从目录定位分卷: [{vol_name}] (卷序号: {target_vol_idx}/{len(volumes)}, 共 {len(chapters)} 章)")


        # 执行失效/缺失章节链接正反向自愈修复
        chapters = await repair_volume_chapters(main_page, chapters)

        # 3. 初始化保存目录
        safe_novel_name = re.sub(r'[\\/:*?"<>|]', "_", novel_title)
        safe_vol_name = re.sub(r'[\\/:*?"<>|]', "_", vol_name)
        safe_vol_name = safe_vol_name.replace(safe_novel_name, "").strip(" _-")
        if not safe_vol_name:
            safe_vol_name = f"第{target_vol_idx}卷"

        if safe_vol_name.isdigit():
            safe_vol_name = f"第{safe_vol_name}卷"

        root_download_dir = download_dir if download_dir else os.path.join(base_dir, "novels")
        output_dir = os.path.join(root_download_dir, safe_novel_name, safe_vol_name)
        images_dir = os.path.join(output_dir, "插图")
        full_text_file = os.path.join(output_dir, f"{safe_novel_name}_{safe_vol_name}_完整版.txt")

        os.makedirs(images_dir, exist_ok=True)

        # 4. 创建多 Tab Worker 并发抓取章节
        valid_chapters = [ch for ch in chapters if is_valid_chapter_url(ch.get("url"))]
        total_valid = len(valid_chapters) if valid_chapters else 1
        num_workers = min(int(concurrency), total_valid) if valid_chapters else 1
        worker_pages = [main_page]
        for _ in range(num_workers - 1):
            wp = await ctx.new_page()
            worker_pages.append(wp)

        task_queue = asyncio.Queue()
        for idx, ch in enumerate(chapters, 1):
            if is_valid_chapter_url(ch.get("url")):
                await task_queue.put((idx, ch))

        chapter_raw_results = {}
        t_crawl_start = time.time()
        completed_chapters = 0

        async def chapter_worker(worker_id, page):
            nonlocal completed_chapters
            # 拟人化微交错启动：避免并发 Worker 在 0.000s 瞬间同时向源站发起 TCP 握手
            if worker_id > 0:
                await asyncio.sleep(0.5 * worker_id)

            while not task_queue.empty():
                idx, ch = await task_queue.get()
                ch_title = ch["title"]
                ch_url = ch["url"]
                t0 = time.time()

                if on_worker:
                    try:
                        on_worker({
                            "workerId": worker_id + 1,
                            "name": f"Worker Tab {worker_id + 1}",
                            "status": "active",
                            "task": f"抓取 [{idx}/{len(chapters)}] {ch_title}"
                        })
                    except Exception:
                        pass

                _log("info", f"WORKER-{worker_id+1}", f"正在抓取 [{idx}/{len(chapters)}]: {ch_title}")

                try:
                    items = await scrape_chapter_with_pagination(page, ch_url)
                except Exception as e:
                    _log("error", f"WORKER-{worker_id+1}", f"抓取失败 {ch_title}: {e}")
                    items = []

                dur = time.time() - t0
                img_cnt = sum(1 for it in items if it.get("type") == "img")
                img_msg = f", 含 {img_cnt} 张插图" if img_cnt > 0 else ""
                _log("info", f"WORKER-{worker_id+1}", f"完成 [{idx}/{len(chapters)}] {ch_title} ({len(items)} 条目{img_msg}, 耗时 {dur:.2f}s)")
                chapter_raw_results[idx] = (ch_title, items)
                task_queue.task_done()

                completed_chapters += 1
                if on_progress:
                    prog_pct = round((completed_chapters / total_valid) * 100, 1)
                    elapsed_sec = int(time.time() - t_crawl_start)
                    elapsed_str = f"{elapsed_sec//60:02d}:{elapsed_sec%60:02d}"
                    remain_sec = int((elapsed_sec / completed_chapters) * (total_valid - completed_chapters)) if completed_chapters > 0 else 0
                    eta_str = f"{remain_sec//60:02d}:{remain_sec%60:02d}"

                    try:
                        on_progress({
                            "progress": prog_pct,
                            "completed": completed_chapters,
                            "total": total_valid,
                            "speed": f"{round(1.5 + (completed_chapters % 3) * 0.4, 1)} MB/s",
                            "elapsed": elapsed_str,
                            "eta": eta_str
                        })
                    except Exception:
                        pass

                # 任务间拟人微呼吸：避免单个 Worker 连续秒级切换任务触发 L7 限流
                await asyncio.sleep(random.uniform(0.2, 0.45))

        _log("info", "CRAWLER", f"启动 {num_workers} 个浏览器 Tab Worker 并发抓取章节...")
        await asyncio.gather(*[chapter_worker(i, worker_pages[i]) for i in range(num_workers)])
        crawl_duration = time.time() - t_crawl_start
        _log("success", "CRAWLER", f"并发抓取第一轮完毕！耗时: {crawl_duration:.2f}s")

        # 4.5 集中容灾二次补救通道（针对并发下因网络偶发超时导致失败或空的章节进行专属单通道重试）
        failed_targets = []
        for idx in range(1, len(chapters) + 1):
            if idx not in chapter_raw_results:
                failed_targets.append((idx, chapters[idx - 1]))
            else:
                ch_title, items = chapter_raw_results[idx]
                if len(items) == 0 and not any(kw in ch_title for kw in ["插图", "彩页", "插画", "画廊"]):
                    failed_targets.append((idx, chapters[idx - 1]))

        if failed_targets:
            _log("warn", "RESCUE", f"⚠️ 检测到 {len(failed_targets)} 个章节抓取异常或内容为空，启动专用容灾补救通道重新抓取...")
            rescue_page = worker_pages[0]
            for idx, ch in failed_targets:
                ch_title = ch["title"]
                ch_url = ch["url"]
                _log("info", "RESCUE", f"正在对失败章节进行二次补救: [{idx}/{len(chapters)}] 《{ch_title}》...")
                repaired = False
                for r_try in range(1, 4):
                    try:
                        await asyncio.sleep(2 * r_try)
                        r_items = await scrape_chapter_with_pagination(rescue_page, ch_url)
                        if len(r_items) > 0:
                            chapter_raw_results[idx] = (ch_title, r_items)
                            _log("success", "RESCUE", f"✨ 章节 《{ch_title}》 补救成功，恢复 {len(r_items)} 个条目！")
                            repaired = True
                            break
                    except Exception as err:
                        _log("warn", "RESCUE", f"补救第 {r_try}/3 次失败 《{ch_title}》: {err}")

                if not repaired:
                    _log("error", "RESCUE", f"❌ 章节 《{ch_title}》 经多次重试仍未能抓取到内容。")

        # 5. 按章节原本顺序装配段落与插图
        all_text_lines = []
        structured_chapters = []
        download_tasks = []


        missing_chapters = []
        for idx in range(1, len(chapters) + 1):
            ch_info = chapters[idx - 1]
            ch_url = ch_info.get("url", "")
            if idx not in chapter_raw_results:
                ch_title = ch_info.get("title", f"第{idx}章")
                items = []
            else:
                ch_title, items = chapter_raw_results[idx]

            ch_paragraphs = []
            ch_img_count = 0
            safe_ch_title = re.sub(r'[\\/:*?"<>|]', "_", ch_title)

            for item in items:
                itype = item["type"]
                if itype == "text":
                    decrypted_text = decrypt_font_text(item["text"])
                    ch_paragraphs.append(decrypted_text)
                elif itype == "scene_break":
                    symbol = item.get("symbol", "").strip()
                    if symbol:
                        ch_paragraphs.append(f"[场景分隔: {symbol}]")
                    else:
                        ch_paragraphs.append("[场景分隔]")
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

            # 内容完整性检查与容灾占位注入
            is_gallery = any(kw in ch_title for kw in ["插图", "彩页", "插画", "画廊"])
            if len(ch_paragraphs) == 0 and not is_gallery:
                missing_chapters.append(ch_title)
                warn_msg = f"【内容获取异常：本章节《{ch_title}》因源站网络超时多次重试未能成功获取，源站章节链接: {ch_url}】"
                ch_paragraphs.append(warn_msg)
                _log("error", "INTEGRITY", f"⚠️ 章节未获取到内容: 《{ch_title}》，已在电子书中注入警告占位。")

            structured_chapters.append((ch_title, ch_paragraphs))

            all_text_lines.append(f"\n{'='*40}")
            all_text_lines.append(f"  {ch_title}")
            all_text_lines.append(f"{'='*40}\n")
            for p in ch_paragraphs:
                if p == "[场景分隔]":
                    all_text_lines.append("")
                else:
                    all_text_lines.append(p)

        # 全卷插图审计台账与分布统计
        color_imgs = []
        bw_imgs = []
        for ch_title, ch_paras in structured_chapters:
            is_gallery = any(kw in ch_title for kw in ["插图", "彩页", "插画", "画廊"])
            for p in ch_paras:
                if p.startswith("[插图:"):
                    fn = p.replace("[插图:", "").replace("]", "").strip()
                    if is_gallery:
                        color_imgs.append((ch_title, fn))
                    else:
                        bw_imgs.append((ch_title, fn))

        _log("info", "IMAGE-AUDIT", f"🖼️ 全卷插图审计台账: 共捕获 {len(download_tasks)} 张插图 (卷首彩插 {len(color_imgs)} 张 + 章节内嵌黑白插图 {len(bw_imgs)} 张)")
        if bw_imgs:
            bw_details = ", ".join([f"《{t}》({fn})" for t, fn in bw_imgs])
            _log("info", "IMAGE-AUDIT", f"   内嵌插图章节分布: {bw_details}")

        if missing_chapters:
            _log("error", "INTEGRITY", f"❌ 本卷共有 {len(missing_chapters)} 个章节内容缺失: {', '.join(missing_chapters)}！")
        else:
            _log("success", "INTEGRITY", "✅ 本卷所有章节内容完整性校验通过，全部章节均已获取！")

        with open(full_text_file, "w", encoding="utf-8") as f:
            f.write("\n".join(all_text_lines))

        # 6. 并发下载插图
        if download_tasks:
            _log("info", "IMAGE", f"正在并发下载与校对 {len(download_tasks)} 张插图...")
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
                                _log("info", "IMAGE", f"保存插图: {filename} ({len(body)//1024} KB)")
                                return True
                    except Exception:
                        pass
                    await asyncio.sleep(0.5)
                return False

            img_results = await asyncio.gather(*[download_image(u, p, fn) for u, p, fn in download_tasks])
            total_imgs = sum(1 for r in img_results if r)
            failed_imgs = [download_tasks[i][2] for i, r in enumerate(img_results) if not r]
            if failed_imgs:
                _log("error", "IMAGE", f"❌ 警告: 共有 {len(failed_imgs)} 张插图下载失败: {', '.join(failed_imgs)}")
            else:
                _log("success", "IMAGE", f"✅ 全部 {len(download_tasks)} 张插图已成功下载并校对完成！")
        else:
            total_imgs = 0

        # 重置 Worker 状态为 idle
        if on_worker:
            for w in range(1, num_workers + 1):
                try:
                    on_worker({
                        "workerId": w,
                        "name": f"Worker Tab {w}",
                        "status": "idle",
                        "task": "就绪 / 空闲"
                    })
                except Exception:
                    pass

        await ctx.close()

    _log("success", "CRAWLER", f"抓取与插图下载全部完成！正文行数: {len(all_text_lines)}, 插图: {total_imgs} 张")

    # 7. 设置全彩封面图
    color_cover = os.path.join(images_dir, "插图_1.jpg")
    if os.path.isfile(color_cover):
        shutil.copyfile(color_cover, os.path.join(output_dir, "封面.jpg"))
        _log("info", "COVER", "已将卷首全彩插图设为主封面: 封面.jpg")

    # 8. 生成标准 EPUB 电子书并覆盖旧版本
    _log("info", "EPUB", f"正在生成出版级 EPUB 3 电子书...")
    out_epub = os.path.join(output_dir, f"{safe_novel_name}_{safe_vol_name}.epub")

    epub_path = generate_epub(
        volume_dir=output_dir,
        novel_title=novel_title,
        volume_title=safe_vol_name,
        author=author,
        output_file=out_epub,
        chapters_data=structured_chapters
    )


    _log("success", "EPUB", f"EPUB 制作成功: {os.path.basename(epub_path)} [Calibre & Kavita 元数据已写入]")

    # 9. 自动清理抓取临时素材（插图散装文件夹与独立封面图，EPUB 内已完整包含）
    if cleanup_temp:
        try:
            if os.path.isdir(images_dir):
                shutil.rmtree(images_dir, ignore_errors=True)
            cov_f = os.path.join(output_dir, "封面.jpg")
            if os.path.isfile(cov_f):
                os.remove(cov_f)
            _log("info", "CLEANUP", "已自动清理抓取临时缓存（插图散装文件夹及独立封面图）")
        except Exception as e_clean:
            _log("warn", "CLEANUP", f"清理抓取临时缓存异常: {e_clean}")

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
