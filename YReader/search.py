import threading
import json
import cloudscraper
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote
import re
from PySide6.QtCore import QObject, Signal
from utils import load_sites_config, load_legado_sources
from legado_adapter import LegadoEngine, register_legado_url


class SearchEmitter(QObject):
    result_ready = Signal(str, list, str)
    finished = Signal()


class SearchWorker(threading.Thread):
    def __init__(self, keyword, emitter):
        super().__init__()
        self.keyword = keyword
        self.emitter = emitter
        self.is_cancelled = False
        self.sites = load_sites_config()
        self.legado_sources = load_legado_sources()

    def run(self):
        threads = []

        def fetch_site(site_info):
            if self.is_cancelled: return
            site_name = site_info.get("name", "未知")
            base_url = site_info.get("base_url", "")
            search_url_template = site_info.get("search_url", "")
            site_type = site_info.get("type", "manual")

            try:
                # ====== Legado 书源：使用规则引擎搜索 ======
                if site_type == "legado":
                    source_data = site_info.get("source_data")
                    if not source_data:
                        # 尝试从文件加载
                        source_file = site_info.get("source_file", "")
                        if source_file:
                            try:
                                with open(source_file, 'r', encoding='utf-8') as f:
                                    source_data = json.load(f)
                            except Exception:
                                pass
                    if not source_data:
                        self.emitter.result_ready.emit(site_name, [{
                            "title": "⚠️ Legado 书源数据缺失，请在书源管理中重新导入",
                            "url": f"SYSTEM_BROWSER:{base_url}",
                            "author": "-", "site": site_name
                        }], "")
                        return

                    engine = LegadoEngine(source_data)
                    results = engine.search(self.keyword)
                    if self.is_cancelled:
                        return
                    if results:
                        # 注册所有结果 URL 到 Legado 注册表
                        for r in results:
                            register_legado_url(r['url'], source_data)
                        self.emitter.result_ready.emit(site_name, results, "")
                    else:
                        self.emitter.result_ready.emit(site_name, [{
                            "title": "⚠️ 未抓取到结果，双击在浏览器中去该站手动搜索",
                            "url": f"SYSTEM_BROWSER:{base_url}",
                            "author": "-", "site": site_name
                        }], "")
                    return

                # 动态加密站，直接交由外部浏览器处理，彻底放弃在后台发请求
                if site_type == "manual":
                    if not self.is_cancelled:
                        self.emitter.result_ready.emit(site_name, [{
                            "title": f"🌐 防爬加密站，双击前往该站主页手动搜索",
                            "url": f"SYSTEM_BROWSER:{base_url}",
                            "author": "-",
                            "site": site_name
                        }], "")
                    return

                # 静态网站，发起真实搜索请求提取详情页
                scraper = cloudscraper.create_scraper(
                    browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
                search_url = search_url_template.replace("{key}", quote(self.keyword))
                res = scraper.get(search_url, timeout=10)
                res.encoding = res.apparent_encoding
                soup = BeautifulSoup(res.text, 'html.parser')
                results = []

                # ====== 通用结构化提取 (优先卡片式) ======
                for card in soup.find_all('div', class_='card'):
                    a_tag = card.find('a')
                    if not a_tag: continue

                    # 匹配用户提供的HTML结构，尝试从 title 属性获取书名
                    title = a_tag.get('title', '').strip()
                    href = a_tag.get('href', '')
                    if not title or not href: continue

                    author = "未知"
                    if author_div := card.find('div', class_='author'):
                        author = author_div.get_text(strip=True)

                    results.append({
                        "title": title,
                        "url": urljoin(search_url, href),
                        "author": author,
                        "site": site_name
                    })

                # ====== 爱曲小说等站点的 ul>li 列表结构 ======
                if not results:
                    for li in soup.find_all('li'):
                        # 检查是否有 s2（书名）和 s4（作者）这两个关键 span
                        s2_span = li.find('span', class_='s2')
                        s4_span = li.find('span', class_='s4')
                        if not s2_span or not s4_span:
                            continue

                        # 提取书名
                        title_a = s2_span.find('a')
                        if not title_a:
                            continue
                        title = title_a.get_text(strip=True)
                        title_href = title_a.get('href', '')
                        if not title or not title_href:
                            continue

                        # 提取作者
                        author = "未知"
                        author_a = s4_span.find('a')
                        if author_a:
                            author = author_a.get_text(strip=True)

                        results.append({
                            "title": title,
                            "url": urljoin(search_url, title_href),
                            "author": author,
                            "site": site_name
                        })

                # ====== owllook 聚合搜索站点特殊处理 ======
                if not results and 'owlook' in base_url.lower():
                    for item_div in soup.find_all('div', class_='result_item'):
                        a_tag = item_div.find('a')
                        if not a_tag:
                            continue

                        # 提取链接文本，格式为："站点名--书名--作者"
                        link_text = a_tag.get_text(strip=True)
                        href = a_tag.get('href', '')
                        if not link_text or not href:
                            continue

                        # 解析 "站点名--书名--作者" 格式
                        parts = link_text.split('--')
                        if len(parts) >= 2:
                            # 最后一个部分是作者，中间是书名，第一个是站点名
                            if len(parts) == 3:
                                site_source = parts[0].strip()
                                title = parts[1].strip()
                                author = parts[2].strip()
                            elif len(parts) == 2:
                                title = parts[0].strip()
                                author = parts[1].strip()
                                site_source = "未知源"
                            else:
                                # 多于3个部分，取最后两个作为书名和作者
                                author = parts[-1].strip()
                                title = parts[-2].strip()
                                site_source = '--'.join(parts[:-2]).strip() or "未知源"
                        else:
                            # 只有一个部分，直接用作文本
                            title = link_text
                            author = "未知"
                            site_source = "未知源"

                        # 构建完整的目录 URL（owllook 的 /chapter?url=xxx&novels_name=xxx）
                        chapter_url = urljoin(base_url, href)

                        results.append({
                            "title": f"{title} ({site_source})",
                            "url": chapter_url,
                            "author": author,
                            "site": site_name
                        })

                # ====== 兜底提取：如果没有明显卡片，抓包含关键字的超链接 ======
                if not results:
                    seen = set()
                    for a in soup.find_all('a'):
                        text = a.get_text(strip=True)
                        href = a.get('href')
                        if not href or href.startswith('javascript'): continue

                        if self.keyword in text or text in self.keyword:
                            full_url = urljoin(search_url, href)
                            if full_url in seen: continue
                            seen.add(full_url)

                            author = "未知"
                            if parent := a.find_parent(['tr', 'li', 'div', 'dd']):
                                p_text = parent.get_text(separator=' ', strip=True)
                                if m := re.search(r'(?:作者|作\s*者)[：:\s]*([^<>\s]+)', p_text):
                                    author = m.group(1).strip()

                            results.append({
                                "title": text,
                                "url": full_url,
                                "author": author,
                                "site": site_name
                            })

                if not self.is_cancelled:
                    if results:
                        self.emitter.result_ready.emit(site_name, results, "")
                    else:
                        # 静态也没抓到？丢给浏览器兜底
                        self.emitter.result_ready.emit(site_name, [{
                            "title": f"⚠️ 未抓取到结果，双击在浏览器中去该站手动搜索",
                            "url": f"SYSTEM_BROWSER:{base_url}",
                            "author": "-",
                            "site": site_name
                        }], "")

            except Exception as e:
                if not self.is_cancelled:
                    self.emitter.result_ready.emit(site_name, [{
                        "title": f"🔗 节点响应超时或异常，双击尝试在浏览器里打开",
                        "url": f"SYSTEM_BROWSER:{base_url}",
                        "author": "-",
                        "site": site_name
                    }], "")

        # 并发启动所有站点抓取
        # 合并普通站点和 Legado 站点
        all_sites = list(self.sites)
        for ls in self.legado_sources:
            # 如果已经在 sites 中（通过管理UI添加的），跳过重复
            if not any(s.get('name') == ls.get('name') for s in all_sites):
                all_sites.append(ls)

        for site in all_sites:
            t = threading.Thread(target=fetch_site, args=(site,))
            t.daemon = True
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        if not self.is_cancelled:
            self.emitter.finished.emit()
