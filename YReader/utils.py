import sys
import os
import json
import re
import time
import threading
import zipfile
import xml.etree.ElementTree as ET
import cloudscraper
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, quote, unquote, parse_qs

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QFont
from legado_adapter import LegadoEngine, get_legado_source_for_url

IS_MAC = sys.platform == "darwin"


def get_data_dir():
    """获取用户数据目录（配置文件、书源等存储位置）
    - 打包后: macOS → ~/Library/Application Support/YReader/
              Windows → %APPDATA%/YReader/
    - 开发时: 优先使用程序所在目录（方便调试）
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后：使用用户数据目录
        if IS_MAC:
            base = os.path.expanduser('~/Library/Application Support')
        else:
            base = os.environ.get('APPDATA', os.path.expanduser('~'))
        data_dir = os.path.join(base, 'YReader')
    else:
        # 开发时：使用程序所在目录
        data_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


DATA_DIR = get_data_dir()
CONFIG_FILE = os.path.join(DATA_DIR, "reader_config.json")
SITES_FILE = os.path.join(DATA_DIR, "sites.json")
LEGADO_SOURCES_FILE = os.path.join(DATA_DIR, "legado_sources.json")


def init_user_data():
    """首次启动时，将打包内置的模板文件复制到用户数据目录"""
    if not getattr(sys, 'frozen', False):
        return  # 开发时不需要
    bundle_dir = sys._MEIPASS
    templates = ['sites.json', 'legado_sources.json']
    for fname in templates:
        src = os.path.join(bundle_dir, fname)
        dst = os.path.join(DATA_DIR, fname)
        if os.path.exists(src) and not os.path.exists(dst):
            import shutil
            shutil.copy2(src, dst)


# ===== macOS Dock 图标控制（通过 Objective-C 运行时） =====
if IS_MAC:
    import ctypes, ctypes.util
    # 先加载 AppKit 框架，确保 NSApplication 类可用
    ctypes.cdll.LoadLibrary(ctypes.util.find_library('AppKit') or '/System/Library/Frameworks/AppKit.framework/AppKit')
    _objc_lib = ctypes.cdll.LoadLibrary(ctypes.util.find_library('objc') or 'libobjc.dylib')
    _objc_lib.objc_getClass.restype = ctypes.c_void_p
    _objc_lib.objc_getClass.argtypes = [ctypes.c_char_p]
    _objc_lib.sel_registerName.restype = ctypes.c_void_p
    _objc_lib.sel_registerName.argtypes = [ctypes.c_char_p]
    _objc_lib.objc_msgSend.restype = ctypes.c_void_p
    _objc_lib.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    # 支持带 BOOL 参数的消息发送
    _objc_lib.objc_msgSend_bool = _objc_lib.objc_msgSend
    _objc_lib.objc_msgSend_bool.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]

def set_mac_dock_icon_visible(visible: bool):
    """控制 macOS Dock 图标显示/隐藏（运行时即时生效）"""
    if not IS_MAC:
        return
    NSApplication = _objc_lib.objc_getClass(b'NSApplication')
    sel_shared = _objc_lib.sel_registerName(b'sharedApplication')
    sel_policy = _objc_lib.sel_registerName(b'setActivationPolicy:')
    ns_app = _objc_lib.objc_msgSend(NSApplication, sel_shared, None)
    # NSApplicationActivationPolicyRegular = 0, Accessory = 1
    policy = ctypes.c_void_p(0 if visible else 1)
    _objc_lib.objc_msgSend(ns_app, sel_policy, policy)

def extract_book_name_from_toc(toc_url):
    """从目录页提取书名（用于换源功能）"""
    if not toc_url:
        return ""
    try:
        # 检查是否是 Legado 源
        legado_src = get_legado_source_for_url(toc_url)
        if legado_src:
            engine = LegadoEngine(legado_src)
            # 获取书籍详情来提取书名
            info = engine.get_book_info(toc_url)
            if info and info.get('name'):
                return info['name']
        
        # 普通网页：从页面标题提取
        scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
        response = scraper.get(toc_url, timeout=10)
        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 尝试从 meta 标签获取
        og_title = soup.find('meta', property='og:novel:book_name') or soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return og_title['content'].strip()
        
        # 尝试从页面标题提取（去掉"目录"、"最新章节"等后缀）
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.get_text(strip=True)
            # 清理常见后缀
            for suffix in ['目录', '最新章节', '全文阅读', '免费阅读', '第一章']:
                title = title.split(suffix)[0]
            title = title.strip(' _-')
            if title:
                return title
        
        # 尝试从 h1/h2 标签获取
        for tag in ['h1', 'h2']:
            heading = soup.find(tag)
            if heading:
                text = heading.get_text(strip=True)
                # 清理常见后缀
                for suffix in ['目录', '最新章节', '全文阅读']:
                    text = text.split(suffix)[0]
                text = text.strip()
                if text and len(text) < 50:  # 书名通常不会太长
                    return text
    except Exception:
        pass
    return ""

def set_mac_window_shadow(window_ptr: int, enabled: bool):
    """控制 macOS 窗口阴影显示/隐藏（需要 Qt 窗口指针）"""
    if not IS_MAC:
        return
    try:
        # 获取 NSWindow 实例（从 Qt 窗口句柄转换）
        NSView = _objc_lib.objc_getClass(b'NSView')
        sel_window = _objc_lib.sel_registerName(b'window')
        ns_window = _objc_lib.objc_msgSend(window_ptr, sel_window, None)
        
        if ns_window:
            # NSWindow.setHasShadow:
            sel_has_shadow = _objc_lib.sel_registerName(b'setHasShadow:')
            _objc_lib.objc_msgSend_bool(ns_window, sel_has_shadow, enabled)
    except Exception:
        pass  # 静默失败，不影响主流程

def hide_mac_app():
    """macOS 应用级隐藏（等同于 Cmd+H），保留所有窗口状态"""
    if not IS_MAC:
        return
    try:
        NSApplication = _objc_lib.objc_getClass(b'NSApplication')
        sel_shared = _objc_lib.sel_registerName(b'sharedApplication')
        ns_app = _objc_lib.objc_msgSend(NSApplication, sel_shared, None)
        sel_hide = _objc_lib.sel_registerName(b'hide:')
        _objc_lib.objc_msgSend(ns_app, sel_hide, ctypes.c_void_p(0))
    except Exception:
        pass

def unhide_mac_app():
    """macOS 应用级恢复显示（等同于 Cmd+H 后再点击 Dock）"""
    if not IS_MAC:
        return
    try:
        NSApplication = _objc_lib.objc_getClass(b'NSApplication')
        sel_shared = _objc_lib.sel_registerName(b'sharedApplication')
        ns_app = _objc_lib.objc_msgSend(NSApplication, sel_shared, None)
        sel_unhide = _objc_lib.sel_registerName(b'unhideAllApplications:')
        _objc_lib.objc_msgSend(ns_app, sel_unhide, ctypes.c_void_p(0))
        # 同时激活应用，确保窗口前置
        sel_activate = _objc_lib.sel_registerName(b'activateIgnoringOtherApps:')
        _objc_lib.objc_msgSend_bool(ns_app, sel_activate, True)
    except Exception:
        pass

# ===== Windows 原生窗口隐藏（Win32 API） =====
_win32_user32 = None
def _get_win32_user32():
    global _win32_user32
    if _win32_user32 is None:
        import ctypes
        _win32_user32 = ctypes.windll.user32
    return _win32_user32

def hide_win_window(win_id: int):
    """Windows 原生隐藏窗口（Win32 ShowWindow SW_HIDE）"""
    if IS_MAC:
        return
    try:
        user32 = _get_win32_user32()
        user32.ShowWindow(win_id, 0)  # SW_HIDE = 0
    except Exception:
        pass

def show_win_window(win_id: int):
    """Windows 原生恢复窗口（Win32 ShowWindow SW_SHOW）"""
    if IS_MAC:
        return
    try:
        user32 = _get_win32_user32()
        user32.ShowWindow(win_id, 5)  # SW_SHOW = 5
    except Exception:
        pass

# ================= 核心修改：动态书源配置系统 =================
def load_sites_config():
    """加载书源配置（从 sites.json 文件读取）"""
    if not os.path.exists(SITES_FILE):
        return []
    try:
        with open(SITES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def save_sites_config(sites_data):
    try:
        with open(SITES_FILE, 'w', encoding='utf-8') as f:
            json.dump(sites_data, f, ensure_ascii=False, indent=4)
    except Exception:
        pass


# ===================== Legado 书源配置 =====================
def load_legado_sources():
    if not os.path.exists(LEGADO_SOURCES_FILE):
        return []
    try:
        with open(LEGADO_SOURCES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def save_legado_sources(sources_data):
    try:
        with open(LEGADO_SOURCES_FILE, 'w', encoding='utf-8') as f:
            json.dump(sources_data, f, ensure_ascii=False, indent=4)
    except Exception:
        pass

SUPPORTED_SITES_DATA = load_sites_config()
# 兼容旧代码变量
SUPPORTED_SITES = [(s["name"], s["base_url"]) for s in SUPPORTED_SITES_DATA]
# =========================================================

WEIGHT_MAP = {
    "极细 (Thin)": QFont.Weight.Thin,
    "细体 (Light)": QFont.Weight.Light,
    "常规 (Normal)": QFont.Weight.Normal,
    "中等 (Medium)": QFont.Weight.Medium,
    "半粗 (DemiBold)": QFont.Weight.DemiBold,
    "加粗 (Bold)": QFont.Weight.Bold,
    "极粗 (Black)": QFont.Weight.Black
}

CHAPTER_PATTERN = re.compile(r'(第.*?[章节回折卷篇])|(楔子|番外|大?结局|引子|序[章言]|终章|完本感言?|尾声)', re.IGNORECASE)
TITLE_CHAPTER_PATTERN = re.compile(
    r'(第\s*[0-9０-９零〇一二两三四五六七八九十百千万]+\s*[章节回折卷篇]\s*[^_\-|—–]*)'
    r'|(楔子|番外|大?结局|引子|序[章言]|终章|完本感言?|尾声)\s*[^_\-|—–]*',
    re.IGNORECASE
)
GARBAGE_TOC_TEXT_PATTERN = re.compile(
    r'首页|下载|排行|玄幻|武侠|都市|科幻|言情|历史|网游|书架|加入书架|推荐本书|返回|投月票|报错', re.IGNORECASE)

def looks_like_toc_page(soup):
    for container in soup.find_all(['ul', 'ol', 'dl', 'table', 'tbody', 'div']):
        links = container.find_all('a')
        if len(links) < 5:
            continue
        chapter_links = sum(1 for a in links if a.get('href') and not is_ignored_href(a.get('href', '')) and CHAPTER_PATTERN.search(a.get_text(strip=True)))
        if chapter_links >= 5 and chapter_links / len(links) >= 0.35:
            return True
    return False

def is_ignored_href(href):
    if not href: return True
    href = href.strip()
    return href == '#' or href.lower().startswith(('javascript:', 'javascript：'))

def infer_toc_url_from_chapter_url(url):
    parsed = urlparse(url)
    if "yc0033.com" not in parsed.netloc: return ""
    if re.fullmatch(r'/lwxs/\d+/\d+/\d+\.html', parsed.path): return urljoin(url, './')
    return ""

def clean_title_text(raw_title, soup=None, fallback_url=""):
    candidates = []
    if soup:
        for selector in [('h1', None), ('h2', None)]:
            if tag := soup.find(selector[0]): candidates.append(tag.get_text(strip=True))
        for attrs in [{'property': 'og:novel:latest_chapter_name'}, {'property': 'og:novel:chapter_name'}, {'name': 'chapter_name'}]:
            tag = soup.find('meta', attrs=attrs)
            if content := tag.get('content', '').strip() if tag else '': candidates.append(content)
    if raw_title: candidates.append(raw_title)

    for candidate in candidates:
        text = re.sub(r'\s+', ' ', candidate.replace("Just a moment...", "")).strip()
        if match := TITLE_CHAPTER_PATTERN.search(text): return match.group(0).strip()

    fallback = (raw_title or fallback_url).replace("Just a moment...", "")
    for sep in ['|', '_', '—', '–', '-']:
        parts = [part.strip() for part in fallback.split(sep) if part.strip()]
        if chapter_part := next((part for part in parts if TITLE_CHAPTER_PATTERN.search(part)), ""):
            return TITLE_CHAPTER_PATTERN.search(chapter_part).group(0).strip()
        if parts: fallback = parts[0]
    return fallback.strip() or fallback_url

def _strip_ad_text(text):
    """文本层面清理广告内容：去除常见广告句子"""
    if not text:
        return text
    # 常见广告句子的正则模式（匹配后整句删除）
    ad_patterns = [
        r'一秒记住[^\s。]{0,80}(?:最快更新|无广告|无弹窗)[！!]?',
        r'天才一秒记住本站地址[：:].*(?:最快更新|无广告)[！!]?',
        r'最快更新[！!]?无广告[！!]?',
        r'最新网址[：:]\s*\S+',
        r'最新章节[：:]\s*\S+',
        r'https?://\S+?(?:最快更新|无广告|最新|阅读|小说)[^\s。]*',
        r'(?:请记住|请收藏|收藏本站|记住网址|加入收藏)[^\s。]{0,50}(?:网址|地址|域名)[^\s。]*',
        r'章节错误[，,]?点此报送[^\s。]*[。！!]?',
        r'报送后维护人员会在[^\s。]*校正[^\s。]*[。！!]?',
        r'(?:手机版|电脑版)阅读网址[：:]\s*\S+',
        r'www\.[a-zA-Z0-9]+\.[a-z]{2,4}(?:/\S*)?',
    ]
    for pat in ad_patterns:
        text = re.sub(pat, '', text, flags=re.IGNORECASE)
    # 清理多余空白
    text = re.sub(r'\s{2,}', ' ', text).strip()
    return text


def make_local_file_url(path, chapter_index=None, toc=False):
    url = "localbook://reader?path=" + quote(os.path.abspath(path), safe='')
    if toc: return url + "&toc=1"
    if chapter_index is not None: return url + f"&chapter={chapter_index}"
    return url

def local_path_from_url(url):
    parsed = urlparse(url)
    if parsed.scheme == 'localbook': return parse_qs(parsed.query).get('path', [''])[0]
    path = unquote(parsed.path)
    if sys.platform.startswith('win') and re.match(r'^/[A-Za-z]:/', path): path = path[1:]
    return path

def read_text_file(path):
    with open(path, 'rb') as f:
        data = f.read()
    for encoding in ['utf-8-sig', 'utf-8', 'gb18030', 'big5']:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode('utf-8', errors='replace')

def normalize_plain_text(text):
    return re.sub(r'\s+', ' ', text.replace('\u3000', ' ')).strip()

def clean_garbled_text(text):
    """通用清理：去除重复的问号、省略号等乱码字符"""
    # 混合重复问号（半角?和全角？混合出现2个及以上 -> 全部删除）
    text = re.sub(r'[\?？]{2,}', '', text)
    # 重复省略号（6个点及以上 -> 标准省略号）
    text = re.sub(r'\.{6,}', '……', text)
    text = re.sub(r'。{3,}', '……', text)
    # 重复感叹号（3个及以上 -> 1个）
    text = re.sub(r'!{3,}', '！', text)
    text = re.sub(r'！{3,}', '！', text)
    return text

def split_txt_chapters(path):
    text = read_text_file(path).replace('\r\n', '\n').replace('\r', '\n')
    chapter_line_pattern = re.compile(
        r'^\s*((第\s*[0-9０-９零〇一二两三四五六七八九十百千万]+\s*[章节回折卷篇].*)|(楔子|番外|大?结局|引子|序[章言]|终章|完本感言?|尾声).*)\s*$',
        re.IGNORECASE | re.MULTILINE
    )
    matches = list(chapter_line_pattern.finditer(text))

    if not matches:
        return [{"title": os.path.splitext(os.path.basename(path))[0], "text": normalize_plain_text(text)}]

    chapters = []
    intro = text[:matches[0].start()].strip()
    if intro:
        intro_title = os.path.splitext(os.path.basename(path))[0]
        if title_match := re.search(r'《([^》]+)》', intro): intro_title = title_match.group(1)
        chapters.append({"title": intro_title, "text": normalize_plain_text(intro)})

    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        title = re.sub(r'\s+', ' ', match.group(1)).strip()
        if body := text[start:end].strip(): chapters.append({"title": title, "text": normalize_plain_text(body)})
    return chapters

def _xml_local_name(tag):
    return tag.rsplit('}', 1)[-1]

def _epub_join(base_dir, href):
    href = unquote(href.split('#', 1)[0])
    return os.path.normpath(os.path.join(base_dir, href)).replace('\\', '/')

def parse_epub_chapters(path):
    chapters = []
    with zipfile.ZipFile(path) as zf:
        container = ET.fromstring(zf.read('META-INF/container.xml'))
        rootfile = next((elem.get('full-path') for elem in container.iter() if _xml_local_name(elem.tag) == 'rootfile' and elem.get('full-path')), None)
        if not rootfile: raise ValueError("未找到 EPUB 主目录文件")

        opf_dir = os.path.dirname(rootfile)
        opf = ET.fromstring(zf.read(rootfile))

        # 完整解析 manifest（保存 href、media-type、properties）
        manifest = {}
        for elem in opf.iter():
            if _xml_local_name(elem.tag) == 'item' and elem.get('id') and elem.get('href'):
                manifest[elem.get('id')] = {
                    'href': elem.get('href'),
                    'media-type': elem.get('media-type', ''),
                    'properties': elem.get('properties', ''),
                }
        spine_ids = [elem.get('idref') for elem in opf.iter() if _xml_local_name(elem.tag) == 'itemref' and elem.get('idref')]

        for idref in spine_ids:
            item_info = manifest.get(idref)
            if not item_info: continue

            # 跳过非 XHTML 内容（图片、CSS、JS 等）
            media_type = item_info['media-type']
            if media_type and 'xhtml' not in media_type and 'html' not in media_type:
                continue

            # 跳过 nav/toc 页面
            props = item_info['properties']
            if 'nav' in props or 'toc' in props:
                continue

            item_path = _epub_join(opf_dir, item_info['href'])
            if item_path not in zf.namelist(): continue

            soup = BeautifulSoup(zf.read(item_path), 'html.parser')
            for unwanted in soup.find_all(['script', 'style', 'nav']): unwanted.decompose()

            # 提取标题
            title_tag = soup.find(['h1', 'h2', 'h3']) or soup.find('title')
            raw_title = title_tag.get_text(" ", strip=True) if title_tag else os.path.splitext(os.path.basename(item_path))[0]
            title = clean_title_text(raw_title) if TITLE_CHAPTER_PATTERN.search(raw_title) else re.sub(r'\s+', ' ', raw_title).strip()

            # 跳过目录页、封面页（标题含特定关键词）
            title_lower = title.lower()
            if any(kw in title_lower for kw in ['目录', 'content', 'table of contents', 'toc', '封面', 'cover']):
                continue

            # 提取正文：先移除标题标签，避免标题在正文中重复出现
            body_soup = soup.body or soup
            for t_tag in body_soup.find_all(['h1', 'h2', 'h3']):
                t_tag.decompose()

            if text := re.sub(r'\s+', ' ', body_soup.get_text(" ", strip=True)).strip():
                # 跳过内容过少的页面（可能是空白页或版权页）
                if len(text) < 20:
                    continue
                chapters.append({"title": title or f"第{len(chapters) + 1}章", "text": text})

    if not chapters: raise ValueError("未能从 EPUB 读取到正文")
    return chapters


def parse_mobi_chapters(path):
    """解析 MOBI 文件章节（通过 mobi 库转换为 EPUB/HTML 后解析）"""
    import shutil
    import tempfile
    try:
        import mobi
    except ImportError:
        raise ValueError("需要安装 mobi 库：pip install mobi")

    tempdir = None
    try:
        tempdir, extracted_path = mobi.extract(path)
        ext = os.path.splitext(extracted_path)[1].lower()

        if ext == '.epub':
            # MOBI8 格式，直接复用 EPUB 解析
            return parse_epub_chapters(extracted_path)
        elif ext in ('.html', '.htm'):
            # MOBI7 格式，解析单个 HTML 文件
            return _parse_mobi_html(extracted_path)
        else:
            raise ValueError(f"不支持的 MOBI 提取格式: {ext}")
    finally:
        # 清理临时目录
        if tempdir and os.path.exists(tempdir):
            shutil.rmtree(tempdir, ignore_errors=True)


def _parse_mobi_html(html_path):
    """解析 MOBI7 提取出的 HTML 文件"""
    with open(html_path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()

    soup = BeautifulSoup(content, 'html.parser')
    for unwanted in soup.find_all(['script', 'style', 'nav']):
        unwanted.decompose()

    # 尝试按章节标题拆分
    chapter_pattern = re.compile(
        r'(第\s*[0-9０-９零〇一二两三四五六七八九十百千万]+\s*[章节回折卷篇].*)',
        re.IGNORECASE
    )

    # 找到所有章节标题元素
    chapter_headers = []
    for tag in soup.find_all(['h1', 'h2', 'h3', 'h4', 'b']):
        text = tag.get_text(strip=True)
        if chapter_pattern.match(text):
            chapter_headers.append(tag)

    if chapter_headers:
        chapters = []
        for idx, header in enumerate(chapter_headers):
            title = re.sub(r'\s+', ' ', header.get_text(strip=True))
            # 收集标题后到下一个标题前的所有文本
            text_parts = []
            for sibling in header.next_siblings:
                if hasattr(sibling, 'name') and sibling in chapter_headers[idx + 1:idx + 2]:
                    break
                if hasattr(sibling, 'name') and sibling.name in ['h1', 'h2', 'h3', 'h4'] and sibling != header:
                    if chapter_pattern.match(sibling.get_text(strip=True)):
                        break
                if hasattr(sibling, 'get_text'):
                    text_parts.append(sibling.get_text(strip=True))
                elif isinstance(sibling, str):
                    text_parts.append(sibling.strip())

            text = re.sub(r'\s+', ' ', ' '.join(text_parts)).strip()
            if text and len(text) > 10:
                chapters.append({"title": title, "text": text})

        if chapters:
            return chapters

    # 无法按章节拆分，作为整本返回
    text = re.sub(r'\s+', ' ', soup.get_text(" ", strip=True)).strip()
    if not text:
        raise ValueError("未能从 MOBI 读取到正文")
    title = os.path.splitext(os.path.basename(html_path))[0]
    return [{"title": title, "text": text}]

def load_config():
    default_config = {
        "history": [], "file_history": [],
        "width": 379, "height": 30, "multi_line": False,
        "bg_opacity": 1, "text_opacity": 100, "show_taskbar": True, "seamless_chapter": True,
        "letter_spacing": 0, "line_spacing": 100, "font_size": 14,
        "font_family": "PingFang SC" if IS_MAC else (QApplication.font().family() if QApplication.instance() else "Microsoft YaHei"),
        "font_weight_name": "常规 (Normal)",
        "text_color": "#000000", "bg_color": "#fcfbfb",
        "key_prev_line": "W", "key_next_line": "E", "key_prev_page": "Alt+W",
        "key_next_page": "Alt+E", "key_boss": "Alt+Q",
        "icon_path": "", "mac_font_fix": False,
        "interactive_bg": False, "show_grip": True,
        "window_x": None, "window_y": None,
        "always_on_top": True
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                def clean_history_items(items):
                    clean_items = []
                    for item in items:
                        if isinstance(item, str): clean_items.append({"title": item, "url": item, "char_index": 0})
                        elif isinstance(item, dict):
                            item.setdefault("char_index", 0)
                            clean_items.append(item)
                    return clean_items

                clean_history = []
                clean_file_history = clean_history_items(data.get("file_history", []))
                for item in clean_history_items(data.get("history", [])):
                    scheme = urlparse(item.get("url", "")).scheme
                    if scheme in ("file", "localbook"): clean_file_history.append(item)
                    else: clean_history.append(item)

                deduped_file_history = []
                seen_file_urls = set()
                for item in clean_file_history:
                    if item.get("url", "") in seen_file_urls: continue
                    seen_file_urls.add(item.get("url", ""))
                    deduped_file_history.append(item)

                data["history"] = clean_history
                data["file_history"] = deduped_file_history
                default_config.update(data)
        except Exception:
            pass
    return default_config

def save_config(config):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False)
    except Exception:
        pass

def apply_dialog_style(dialog, layout=None):
    dialog.setStyleSheet("""
        QDialog { background: #F8F9FA; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; font-size: 13px; }
        QLabel { color: #333333; }
        QPushButton { padding: 6px 16px; border: 1px solid #dcdfe6; border-radius: 4px; background: #ffffff; color: #333333; }
        QPushButton:hover { color: #409EFF; border-color: #c6e2ff; background-color: #ecf5ff; }
        QPushButton:pressed { border-color: #3a8ee6; }
        QPushButton#primaryButton { color: #FFF; background-color: #409EFF; border-color: #409EFF; font-weight: bold;}
        QPushButton#primaryButton:hover { background-color: #66b1ff; border-color: #66b1ff; }
        QPushButton#primaryButton:pressed { background-color: #3a8ee6; }
        QPushButton#secondaryButton { color: #606266; background: #f4f4f5; border-color: #d3d4d6; }
        QPushButton#secondaryButton:hover { color: #909399; background: #e9e9eb; border-color: #e9e9eb; }
    """)
    if layout: layout.setContentsMargins(20, 20, 20, 20); layout.setSpacing(14)

class PingEmitter(QObject):
    result_ready = Signal(int, float, bool)
    finished = Signal()

class PingWorker(threading.Thread):
    def __init__(self, idx, url, emitter):
        super().__init__()
        self.idx, self.url, self.emitter, self.daemon, self.is_cancelled = idx, url, emitter, True, False

    def run(self):
        if self.is_cancelled: return
        start = time.time()
        try:
            scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
            scraper.get(self.url, timeout=5)
            if not self.is_cancelled: self.emitter.result_ready.emit(self.idx, (time.time() - start) * 1000, True)
        except Exception:
            if not self.is_cancelled: self.emitter.result_ready.emit(self.idx, 0, False)
        finally:
            if not self.is_cancelled: self.emitter.finished.emit()

class FetchEmitter(QObject):
    result_ready = Signal(str, str, str, str, str, str)

class FetchWorker(threading.Thread):
    def __init__(self, url, emitter):
        super().__init__()
        self.url, self.emitter, self.daemon, self.is_cancelled = url, emitter, True, False

    def run(self):
        if self.is_cancelled: return

        # 检查是否属于 Legado 源
        legado_src = get_legado_source_for_url(self.url)
        if legado_src:
            self._run_legado(legado_src)
            return

        # 标准提取流程
        self._run_standard()

    def _run_legado(self, source_def):
        """通过 Legado 规则引擎提取章节内容"""
        try:
            engine = LegadoEngine(source_def)
            full_text = engine.get_content(self.url)
            # 统一转成纯文本：去除所有换行符和多余空白
            full_text = re.sub(r'\s+', ' ', full_text).strip()
            # 清理广告文本
            full_text = _strip_ad_text(full_text)
            # 清理乱码字符（重复问号等）
            full_text = clean_garbled_text(full_text)
            # 清理 HTML 实体残留（包括双重编码）
            full_text = full_text.replace('&larr;', '').replace('&rarr;', '')
            full_text = full_text.replace('&amp;larr;', '').replace('&amp;rarr;', '')
            full_text = full_text.replace('←', '').replace('→', '')
            
            # 提取标题和上下章节链接
            import cloudscraper as _cs
            from bs4 import BeautifulSoup as _BS4
            scraper = _cs.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
            resp = scraper.get(self.url, timeout=12)
            resp.encoding = resp.apparent_encoding
            soup = _BS4(resp.text, 'html.parser')
            
            raw_title = soup.find('title').get_text(strip=True) if soup.find('title') else self.url
            title_text = clean_title_text(raw_title, soup, self.url)
            # 清理标题中的分页标记
            title_text = re.sub(r'[（(]第\d*页[）)]', '', title_text).strip()
            title_text = re.sub(r'\(第/页\)', '', title_text).strip()
            
            # 优先使用最后一页的 soup 来提取上下章链接（因为"下一章"只在最后一页出现）
            nav_soup = getattr(engine, 'last_page_soup', None) or soup
            
            # 检测是否为 JavaScript 驱动的分页（如得奇小说）
            # 特征：按钮 href="javascript:void(0)" 且有 data-action 属性
            is_js_pagination = False
            for btn in nav_soup.find_all(['a', 'button'], attrs={'data-action': True}):
                href = btn.get('href', '')
                if 'javascript:' in href or href == 'javascript:void(0);':
                    is_js_pagination = True
                    break
                        
            # 从当前 URL 提取章节 ID，用于判断分页链接是否同章
            cur_aid, cur_cid = None, None
            cur_match = re.search(r'/(\d+)/(\d+)\.html', self.url)
            if cur_match:
                cur_aid, cur_cid = cur_match.group(1), cur_match.group(2)
            
            # 歪歪书库特殊处理：URL 格式为 /book_id/chapter_id/page_id.html 或 /book_id/chapter_id/page_id_N.html
            is_yysk = 'yysk.net' in self.url
            yysk_toc_url = None
            if is_yysk:
                # 直接从章节 URL 推断目录 URL：/book_id/chapter_id/xxx.html → /book_id/chapter_id/
                yysk_match = re.search(r'(https?://[^/]+/\d+/\d+)/', self.url)
                if yysk_match:
                    yysk_toc_url = yysk_match.group(1) + '/'
                        
            prev_url, next_url, toc_candidates = "", "", []
            # 如果不是 JS 分页 且 不是歪歪书库，从页面提取上下章链接
            # 歪歪书库的页面链接不可靠，始终从目录获取
            if not is_js_pagination and not is_yysk:
                for a_tag in nav_soup.find_all('a'):
                    text, href = a_tag.get_text(strip=True), a_tag.get('href')
                    if is_ignored_href(href): continue
                            
                    if "上一" in text:
                        tag_url = urljoin(self.url, href)
                        # 得奇：检查是否是同章分页（相同 aid/cid）
                        if cur_aid is not None:
                            tag_match = re.search(r'/(\d+)/(\d+)\.html', tag_url)
                            if tag_match and tag_match.group(1) == cur_aid and tag_match.group(2) == cur_cid:
                                continue
                        prev_url = tag_url
                    elif "下一" in text:
                        tag_url = urljoin(self.url, href)
                        # 得奇：检查是否是同章分页
                        if cur_aid is not None:
                            tag_match = re.search(r'/(\d+)/(\d+)\.html', tag_url)
                            if tag_match and tag_match.group(1) == cur_aid and tag_match.group(2) == cur_cid:
                                continue
                        next_url = tag_url
                    elif ("目录" in text or "章节" in text) and "最新" not in text:
                        temp_url = urljoin(self.url, href)
                        if temp_url != self.url: toc_candidates.append(temp_url)
            else:
                # JS 分页：从面包屑或目录按钮提取 TOC URL
                for a_tag in nav_soup.find_all('a'):
                    text, href = a_tag.get_text(strip=True), a_tag.get('href')
                    if "目录" in text or "章节" in text:
                        if href and not is_ignored_href(href):
                            temp_url = urljoin(self.url, href)
                            if temp_url != self.url: toc_candidates.append(temp_url)
                # 也从面包屑提取 TOC URL
                breadcrumb = nav_soup.find('ol', class_='breadcrumb')
                if breadcrumb:
                    for li in breadcrumb.find_all('li'):
                        if not li.get('class') or 'active' not in li.get('class', []):
                            a_tag = li.find('a')
                            if a_tag:
                                href = a_tag.get('href', '')
                                if href and '/books/' in href:
                                    toc_url_candidate = urljoin(self.url, href)
                                    if toc_url_candidate not in toc_candidates:
                                        toc_candidates.append(toc_url_candidate)
                        
            inferred_toc_url = infer_toc_url_from_chapter_url(self.url)
            if is_yysk and yysk_toc_url:
                toc_url = yysk_toc_url
            else:
                toc_url = inferred_toc_url if inferred_toc_url else self.url if looks_like_toc_page(soup) else toc_candidates[0] if toc_candidates else urljoin(self.url, './')
                        
            # 歪歪书库或 JS 分页：从目录中查找上下章（页面链接不可靠）
            need_toc_fallback = (is_js_pagination or is_yysk) and (not prev_url or not next_url)
            
            if need_toc_fallback:
                try:
                    toc_chapters = engine.get_toc(toc_url)
                    if toc_chapters:
                        # 在目录中查找当前章节
                        current_url_clean = self.url.split('?')[0]
                        if is_yysk:
                            # 歪歪书库：用 /book_id/chapter_id/page_id 前缀匹配（去掉 .html 和 _N.html 后缀）
                            # URL 格式: https://www.yysk.net/book_id/chapter_id/page_id.html
                            yysk_full_match = re.search(r'(/\d+/\d+/\d+)', current_url_clean)
                            current_chapter_prefix = yysk_full_match.group(1) if yysk_full_match else current_url_clean
                        else:
                            current_chapter_prefix = current_url_clean
                        
                        chapter_idx = -1
                        for i, (name, url) in enumerate(toc_chapters):
                            url_clean = url.split('?')[0]
                            if is_yysk:
                                if current_chapter_prefix in url_clean:
                                    chapter_idx = i
                                    break
                            else:
                                if url_clean == current_chapter_prefix or url == self.url:
                                    chapter_idx = i
                                    break
                        
                        if chapter_idx >= 0:
                            if not prev_url and chapter_idx > 0:
                                prev_url = toc_chapters[chapter_idx - 1][1]
                            if not next_url and chapter_idx < len(toc_chapters) - 1:
                                next_url = toc_chapters[chapter_idx + 1][1]
                except Exception:
                    pass  # 目录加载失败，使用已有的 prev_url/next_url

            if not self.is_cancelled:
                self.emitter.result_ready.emit(full_text, prev_url, next_url, title_text, self.url, toc_url)
        except Exception as e:
            if not self.is_cancelled:
                self.emitter.result_ready.emit(f"Legado 抓取失败: {e}", "", "", "加载失败", self.url, "")

    def _run_standard_with_text(self, override_text):
        """使用已提取的正文，但通过标准流程提取上下章/目录"""
        try:
            scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
            response = scraper.get(self.url, timeout=12)
            response.encoding = response.apparent_encoding
            soup = BeautifulSoup(response.text, 'html.parser')

            raw_title = soup.find('title').get_text(strip=True) if soup.find('title') else self.url
            title_text = clean_title_text(raw_title, soup, self.url)

            prev_url, next_url, toc_candidates = "", "", []
            for a_tag in soup.find_all('a'):
                text, href = a_tag.get_text(strip=True), a_tag.get('href')
                if is_ignored_href(href): continue
                if "上一" in text: prev_url = urljoin(self.url, href)
                elif "下一" in text: next_url = urljoin(self.url, href)
                elif ("目录" in text or "章节" in text) and "最新" not in text:
                    temp_url = urljoin(self.url, href)
                    if temp_url != self.url: toc_candidates.append(temp_url)

            inferred_toc_url = infer_toc_url_from_chapter_url(self.url)
            toc_url = inferred_toc_url if inferred_toc_url else self.url if looks_like_toc_page(soup) else toc_candidates[0] if toc_candidates else urljoin(self.url, './')

            if not self.is_cancelled:
                self.emitter.result_ready.emit(override_text, prev_url, next_url, title_text, self.url, toc_url)
        except Exception as e:
            if not self.is_cancelled:
                self.emitter.result_ready.emit(override_text, "", "", "章节内容", self.url, "")

    def _run_standard(self):
        if self.is_cancelled: return
        try:
            scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
            response = scraper.get(self.url, timeout=12)
            response.encoding = response.apparent_encoding
            soup = BeautifulSoup(response.text, 'html.parser')

            raw_title = soup.find('title').get_text(strip=True) if soup.find('title') else self.url
            title_text = clean_title_text(raw_title, soup, self.url)

            if "Just a moment" in response.text or "Cloudflare" in response.text:
                if not self.is_cancelled: self.emitter.result_ready.emit("【访问被拦截，请稍后重试】", "", "", "访问被拦截", self.url, "")
                return

            article = (soup.find('article', id='article') or soup.find('div', id='htmlContent') or soup.find('div', id='chaptercontent') or
                       soup.find('div', id='chapter_content') or soup.find('div', id='text') or soup.find('div', id='chapter') or
                       soup.find('div', id='content') or soup.find('div', id='txt') or  # 笔趣阁等站点的 div#txt
                       soup.find('div', class_='chaptercontent') or soup.find('div', class_='chapter_content') or
                       soup.find('div', class_='Readarea') or soup.find('div', class_='readarea') or soup.find('div', class_='content') or
                       soup.find('div', class_='article-content') or soup.find('div', class_='txtnav') or soup.find('div', class_='txt') or
                       soup.find('div', class_='text'))  # owllook 正文内容

            full_text = "未找到正文内容，请检查网址是否正确或暂不支持该网站排版。"
            if article:
                # 移除已知的广告元素（按 ID / class）
                for ad_el in article.find_all(id=re.compile(r'conter_tip|tipscent|tipsfoot|ad_content|booksource|bookmark', re.I)):
                    ad_el.decompose()
                for ad_el in article.find_all(class_=re.compile(r'conter_tip|ad-content|booksource|bookmark|read_share|link|bottom|ads?', re.I)):
                    ad_el.decompose()
                # 移除脚本、样式、链接等无关元素
                for unwanted in article.find_all(['script', 'style', 'a', 'center', 'div', 'p'], class_=re.compile(r'read_share|link|bottom')):
                    if unwanted.name in ['script', 'style', 'a', 'center'] or 'share' in unwanted.get('class', []) or unwanted.get('id') in ['tipscent', 'tipsfoot']:
                        unwanted.decompose()
                # 移除包含广告特征的 <a> 和 <div>
                for a_tag in article.find_all('a'):
                    a_text = a_tag.get_text(strip=True)
                    if any(kw in a_text for kw in ['报错', '报送', '最新网址', '收藏本站', '记住网址', '最快更新']):
                        a_tag.decompose()
                for div_tag in article.find_all('div'):
                    div_text = div_tag.get_text(strip=True)
                    if any(kw in div_text for kw in ['最新网址', '收藏本站', '天才一秒', '最快更新', '无广告']):
                        if len(div_text) < 200:
                            div_tag.decompose()
                for br in article.find_all('br'): br.replace_with('  ')
                full_text = re.sub(r'\s+', ' ', article.get_text(separator=' ')).strip()
                # 文本层面二次清理：去除残留的广告句子
                full_text = _strip_ad_text(full_text)
                # 清理乱码字符（重复问号等）
                full_text = clean_garbled_text(full_text)

            prev_url, next_url, toc_candidates = "", "", []
            for a_tag in soup.find_all('a'):
                text, href = a_tag.get_text(strip=True), a_tag.get('href')
                if is_ignored_href(href): continue
                if "上一" in text: prev_url = urljoin(self.url, href)
                elif "下一" in text: next_url = urljoin(self.url, href)
                elif ("目录" in text or "章节" in text) and "最新" not in text:
                    temp_url = urljoin(self.url, href)
                    if temp_url != self.url: toc_candidates.append(temp_url)

            inferred_toc_url = infer_toc_url_from_chapter_url(self.url)
            toc_url = inferred_toc_url if inferred_toc_url else self.url if looks_like_toc_page(soup) else toc_candidates[0] if toc_candidates else urljoin(self.url, './')

            if not self.is_cancelled: self.emitter.result_ready.emit(full_text, prev_url, next_url, title_text, self.url, toc_url)
        except Exception as e:
            if not self.is_cancelled: self.emitter.result_ready.emit(f"抓取失败: {e}", "", "", "加载失败", self.url, "")


class TocFetchEmitter(QObject):
    result_ready = Signal(object, str)

class TocFetchWorker(threading.Thread):
    def __init__(self, toc_url, emitter):
        super().__init__()
        self.toc_url, self.emitter, self.daemon, self.is_cancelled = toc_url, emitter, True, False

    def run(self):
        if self.is_cancelled: return

        # 检查是否属于 Legado 源
        legado_src = get_legado_source_for_url(self.toc_url)
        if legado_src:
            try:
                engine = LegadoEngine(legado_src)
                chapters = engine.get_toc(self.toc_url)
                if not self.is_cancelled:
                    self.emitter.result_ready.emit(chapters, "")
                return
            except Exception as e:
                if not self.is_cancelled:
                    self.emitter.result_ready.emit([], f"Legado 目录提取失败: {e}")
                return

        # ====== owllook 特殊处理 ======
        if 'owlook.com.cn' in self.toc_url and '/chapter?' in self.toc_url:
            try:
                scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
                response = scraper.get(self.toc_url, timeout=15)
                response.encoding = response.apparent_encoding
                soup = BeautifulSoup(response.text, 'html.parser')

                # 从隐藏字段获取参数
                content_url_input = soup.find('input', id='content_url')
                url_input = soup.find('input', id='url')
                novels_name_input = soup.find('input', id='novels_name')

                base_owlook = 'https://www.owlook.com.cn'
                source_base = content_url_input.get('value', '') if content_url_input else ''
                source_book_url = url_input.get('value', '') if url_input else ''
                novels_name = novels_name_input.get('value', '未知') if novels_name_input else '未知'

                # 提取所有章节链接
                chapters = []
                for li in soup.find_all('li'):
                    a_tag = li.find('a')
                    if not a_tag:
                        continue
                    chapter_title = a_tag.get_text(strip=True)
                    chapter_href = a_tag.get('href', '')
                    if not chapter_title or not chapter_href:
                        continue

                    # 构建 owllook 内容页 URL
                    # 格式: /owllook_content?url=源站章节URL&name=章节名&chapter_url=源站目录&novels_name=书名
                    source_chapter_url = urljoin(source_base, chapter_href)
                    import urllib.parse
                    content_page_url = f"{base_owlook}/owllook_content?url={urllib.parse.quote(source_chapter_url, safe='')}&name={urllib.parse.quote(chapter_title, safe='')}&chapter_url={urllib.parse.quote(source_book_url, safe='')}&novels_name={urllib.parse.quote(novels_name, safe='')}"

                    chapters.append((chapter_title, content_page_url))

                if not self.is_cancelled:
                    self.emitter.result_ready.emit(chapters, "")
                return
            except Exception as e:
                if not self.is_cancelled:
                    self.emitter.result_ready.emit([], f"owllook 目录提取失败: {e}")
                return

        # 标准流程
        if self.is_cancelled: return
        try:
            scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
            response = scraper.get(self.toc_url, timeout=15)
            response.encoding = response.apparent_encoding
            soup = BeautifulSoup(response.text, 'html.parser')

            best_container, max_score = None, 0
            for container in soup.find_all(['ul', 'ol', 'dl', 'table', 'tbody', 'div']):
                a_tags = container.find_all('a')
                if len(a_tags) < 5: continue
                chapter_links = sum(1 for a in a_tags if CHAPTER_PATTERN.search(a.get_text(strip=True)))
                if chapter_links == 0: continue

                score = chapter_links * (chapter_links / len(a_tags))
                c_class = " ".join(container.get('class', [])).lower() if isinstance(container.get('class', []), list) else ""
                if re.search(r'list|chapter|dir|mulu|zj|content', c_class + " " + container.get('id', '').lower()): score *= 1.5

                if score > max_score:
                    max_score, best_container = score, container

            seen_urls, unique_chapters = set(), []
            a_tags_to_process = best_container.find_all('a') if best_container else soup.find_all('a')

            for a in reversed(list(a_tags_to_process)):
                text, href = a.get_text(strip=True), a.get('href')
                if is_ignored_href(href) or GARBAGE_TOC_TEXT_PATTERN.search(text) or (not best_container and not CHAPTER_PATTERN.search(text) and "章" not in text): continue

                url = urljoin(self.toc_url, href)
                if url not in seen_urls and text:
                    seen_urls.add(url); unique_chapters.append((text, url))

            unique_chapters.reverse()
            if not self.is_cancelled: self.emitter.result_ready.emit(unique_chapters, "")
        except Exception as e:
            if not self.is_cancelled: self.emitter.result_ready.emit([], str(e))