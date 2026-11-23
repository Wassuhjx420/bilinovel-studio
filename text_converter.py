"""
text_converter.py — 轻量级繁简转换引擎（专为轻小说排版与无损 EPUB 设计）
基于 OpenCC t2s 字符与短语映射，结合台版轻小说常见异体字规范化与上下文感知「著/着」处理，
严格保留原翻译用词、标点符号与文本结构（不做地区词汇改写）。

Disclaimer / 免责声明:
本项目仅供 Python 自动化技术交流与个人离线阅读研究使用。
小说内容及插图版权均归原作者及轻小说出版方所有。
严禁将本项目及衍生工具用于任何商业营利目的。
"""

import os
import re
import zipfile

_cc_instance = None
_opencc_warned = False

try:
    from opencc import OpenCC as _OpenCC
except ImportError:
    _OpenCC = None


# 台湾正体常见异体用字补全映射，并还原 OpenCC 对日文常见姓氏汉字「篠」的过转（篠 -> 筿）
EXTRA_CHAR_MAP = str.maketrans({
    "妳": "你",
    "牠": "它",
    "拚": "拼",
    "揹": "背",
    "摀": "捂",
    "瞇": "眯",
    "暱": "昵",
    "搧": "扇",
    "伕": "夫",
    "搆": "够",
    "砲": "炮",
    "珮": "佩",
    "簷": "檐",
    "痺": "痹",
    "睪": "睾",
    "傚": "效",
    "筿": "篠",
})

# 需保护的「著」(zhù) 规范词汇，避免被误转为「着」；同时避开「讨论著」「看著名牌」「刻著名字」「看著书桌」等动补/助词搭配
KEEP_ZHU_RE = re.compile(
    r"(?:显|名|原|巨|专|编|土|译|遗|撰|卓|昭|所)著"
    r"|(?<!讨)(?<!谈)(?<!议)(?<!争)(?<!辩)(?<!评)(?<!理)论著"
    r"|著(?:作|称|述|者|录|书立说)"
    r"|著名(?![字牌单片称号册额义声誉望气])"
)

# 保护 OpenCC TSPhrases 中容易将「覆盖」义误转为「复」的动词搭配
PROTECT_BEFORE_RE = re.compile(r"覆上|覆住")

# 检测是否包含汉字，避免对纯 ASCII/符号/URL 进行无意义处理
HAS_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# 用于无损 EPUB XML 文本节点切分的正则（严格保留所有标签、属性与实体）
XML_TOKEN_RE = re.compile(r"(<[^>]+>|&[^;\s]+;)")


def is_converter_available() -> bool:
    """检查 OpenCC 繁简转换引擎是否可用"""
    return _OpenCC is not None


def _get_opencc():
    """延迟加载 OpenCC t2s 单例，避免未开启功能时产生字典加载开销"""
    global _cc_instance, _opencc_warned
    if _cc_instance is not None:
        return _cc_instance
    if _OpenCC is None:
        if not _opencc_warned:
            _opencc_warned = True
            print("[WARN] 未检测到 opencc-python-reimplemented，繁简转换已自动跳过。请执行: pip install -r requirements.txt")
        return None
    _cc_instance = _OpenCC("t2s")
    return _cc_instance


def convert_to_simplified(text: str) -> str:
    """
    将繁体中文（含台湾正体轻小说常见异体字）无损转换为规范简体中文。
    对已为简体中文的文本完全幂等，不篡改地区词汇（如「文字」「视窗」「设定」），不改动标点符号。
    """
    if not text or not isinstance(text, str) or not HAS_CJK_RE.search(text):
        return text

    cc = _get_opencc()
    if cc is None:
        return text

    # 1. 保护 OpenCC 短语库会误转的动词「覆上 / 覆住」
    protected = []
    if "覆" in text:
        def _save_protected(match):
            idx = len(protected)
            protected.append(match.group(0))
            return f"\uE000{idx}\uE001"
        s = PROTECT_BEFORE_RE.sub(_save_protected, text)
    else:
        s = text

    # 2. 执行 OpenCC t2s 核心繁简转换（纯字形与通用短语，不做地区词汇替换）
    s = cc.convert(s)

    if protected:
        for idx, val in enumerate(protected):
            s = s.replace(f"\uE000{idx}\uE001", val)

    # 3. 台湾正体常见异体用字统一，并还原日文姓氏汉字「篠」
    s = s.translate(EXTRA_CHAR_MAP)

    # 4. 修正 OpenCC 字典边界瑕疵（如古地名「於潛」导致「對於潛入」残留「对於」，以及「藉著」未随「藉着」同步转换）
    if "对於" in s:
        s = s.replace("对於", "对于")
    if "藉著" in s:
        s = s.replace("藉著", "借着")
    if "藉着" in s:
        s = s.replace("藉着", "借着")

    # 5. 上下文感知「著 -> 着」转换，精确保留「著名 / 显著 / 著作 / 原著」等 zhù 义词汇
    if "著" in s:
        zhu_kept = []

        def _save_zhu(match):
            idx = len(zhu_kept)
            zhu_kept.append(match.group(0))
            return f"\uE002{idx}\uE003"

        s = KEEP_ZHU_RE.sub(_save_zhu, s)
        s = s.replace("著", "着")
        for idx, val in enumerate(zhu_kept):
            s = s.replace(f"\uE002{idx}\uE003", val)

    return s


def convert_xml_text_nodes(xml_str: str, is_opf: bool = False) -> str:
    """仅转换 XML/XHTML 中的文本节点与 OPF 系列元数据，字节级保留原有标签、属性与路径引用"""
    parts = XML_TOKEN_RE.split(xml_str)
    out = []
    for part in parts:
        if not part:
            continue
        if part.startswith("<"):
            if is_opf and 'name="calibre:series"' in part:
                part = re.sub(
                    r'(content=")([^"]*)(")',
                    lambda m: m.group(1) + convert_to_simplified(m.group(2)) + m.group(3),
                    part,
                )
            out.append(part)
        elif part.startswith("&") and part.endswith(";"):
            out.append(part)
        else:
            out.append(convert_to_simplified(part))
    return "".join(out)


def convert_epub_file(in_epub_path: str, out_epub_path: str = None) -> str:
    """
    对已生成的 EPUB 电子书执行无损繁转简：
    完整保留 ZIP 条目顺序、mimetype 无压缩首条、CSS、图片二进制及所有 XHTML/XML 结构与路径。
    """
    if not os.path.isfile(in_epub_path):
        raise FileNotFoundError(f"EPUB 文件不存在: {in_epub_path}")

    if not out_epub_path:
        base_dir = os.path.dirname(in_epub_path)
        stem, ext = os.path.splitext(os.path.basename(in_epub_path))
        new_stem = convert_to_simplified(stem)
        if new_stem == stem:
            new_stem = f"{stem}_简体"
        out_epub_path = os.path.join(base_dir, f"{new_stem}{ext}")

    tmp_path = out_epub_path + ".tmp"
    with zipfile.ZipFile(in_epub_path, "r") as zin, zipfile.ZipFile(tmp_path, "w") as zout:
        for info in zin.infolist():
            raw = zin.read(info.filename)
            if info.filename.endswith((".xhtml", ".html", ".ncx", ".opf")):
                text = raw.decode("utf-8")
                is_opf = info.filename.endswith(".opf")
                converted = convert_xml_text_nodes(text, is_opf=is_opf).encode("utf-8")
                zinfo = zipfile.ZipInfo(filename=info.filename, date_time=info.date_time)
                zinfo.compress_type = info.compress_type
                zinfo.external_attr = info.external_attr
                zout.writestr(zinfo, converted)
            else:
                zinfo = zipfile.ZipInfo(filename=info.filename, date_time=info.date_time)
                zinfo.compress_type = info.compress_type
                zinfo.external_attr = info.external_attr
                zout.writestr(zinfo, raw)

    os.replace(tmp_path, out_epub_path)
    return out_epub_path
