"""
Legado (阅读) 书源规则引擎适配器
将 Legado 的规则语法翻译成 Python + BeautifulSoup 可执行逻辑
"""
import re
import os
import sys
import json
import cloudscraper
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote, urlparse


# ===================== 选择器解析工具 =====================

def parse_simple_selector(sel):
    """将 Legado 单条选择器转为 (bs4_method, kwargs) 元组
    支持简单的后代选择器：'dd h3 a' → [('dd', {}), ('h3', {}), ('a', {})]
    支持 class/id: 'class.bookbox' → [('', {'class_': 'bookbox'})]
    """
    sel = sel.strip()
    if not sel:
        return None

    # 检查是否是后代选择器（包含空格）
    if ' ' in sel and not sel.startswith('['):
        # 后代选择器：如 'dd h3 a'
        parts = sel.split()
        result = []
        for part in parts:
            sub_sel = parse_simple_selector(part)
            if sub_sel:
                result.append(sub_sel)
        return result if result else None

    if sel.startswith('class.'):
        return ('find_all', {'class_': sel[6:].strip()})

    if sel.startswith('#'):
        return ('find', {'id': sel[1:].strip()})

    if sel.startswith('[') and sel.endswith(']'):
        inner = sel[1:-1]
        if '=' in inner:
            attr, val = inner.split('=', 1)
            return ('find_all', {'attrs': {attr.strip(): val.strip().strip('"').strip("'")}})

    if '.' in sel and not sel.startswith('.'):
        parts = sel.split('.', 1)
        return ('find_all', {'name': parts[0], 'class_': parts[1]})

    return ('find_all', {'name': sel})


def _call_selector(soup_or_elem, method, kwargs):
    """在 BeautifulSoup 元素上执行选择器调用"""
    if soup_or_elem is None:
        return []
    fn = getattr(soup_or_elem, method, None)
    if fn is None:
        return []
    result = fn(**kwargs)
    if result is None:
        return []
    if not isinstance(result, list):
        return [result]
    return result


def _apply_descendant_selector(element, selector_chain):
    """应用后代选择器链：依次在每个结果上找下一个选择器
    selector_chain: [(method, kwargs), ...]
    """
    if not selector_chain:
        return [element] if element else []
    
    current_results = [element]
    for method, kwargs in selector_chain:
        next_results = []
        for elem in current_results:
            found = _call_selector(elem, method, kwargs)
            next_results.extend(found)
        current_results = next_results
        if not current_results:
            break
    return current_results


def _split_at_signs(line):
    """将一行 Legado 规则按 @ 分隔符拆分为多个步骤（不拆分 [...] 内的 @）
    第一个片段保持原样（选择器），后续片段加 @ 前缀（属性/子元素步骤）
    """
    parts = []
    current = ''
    depth = 0
    for ch in line:
        if ch == '[':
            depth += 1
            current += ch
        elif ch == ']':
            depth -= 1
            current += ch
        elif ch == '@' and depth == 0:
            if current:
                parts.append(current)
            current = '@'  # 下一个片段以 @ 开头
        else:
            current += ch
    if current and current != '@':
        parts.append(current)
    return parts


def _parse_selector_with_index(sel_str):
    """解析选择器，提取可能的 .N 索引后缀
    例如 'class.author.0' → ('class.author', 0)
         'class.bookname' → ('class.bookname', None)
    """
    m = re.match(r'^(.+)\.(\d+)$', sel_str)
    if m:
        return m.group(1), int(m.group(2))
    return sel_str, None


def apply_selector_chain(element, rule_str):
    """
    执行 Legado 的多行选择器链：
      class.bookbox         → find_all(class_='bookbox')
      class.bookname@a@href → find(class_='bookname') → find('a') → 取 href
      text                  → 取文本
      @js: ...              → JS（跳过）
      ##regex##replacement  → 正则替换
    """
    if not rule_str:
        return ""

    raw_lines = [l.strip() for l in rule_str.strip().split('\n') if l.strip()]
    if not raw_lines:
        return ""

    # 展开：将单行中的 @ 分隔符拆成多个步骤
    lines = []
    for line in raw_lines:
        if line.startswith('@js:') or line.startswith('##'):
            lines.append(line)
        elif line.startswith('@'):
            lines.append(line)
        elif line.startswith('text') or line == 'text':
            lines.append(line)
        elif '@' in line:
            # 单行包含 @ 分隔符 → 拆分为多步
            parts = _split_at_signs(line)
            lines.extend(parts)
        else:
            lines.append(line)

    # 第二遍：拆分 ## 正则部分（附着在任何步骤上的都要拆，包括 @ 开头的行）
    final_lines = []
    for line in lines:
        if line.startswith('@js:'):
            final_lines.append(line)
        elif '##' in line:
            # 循环拆分所有 ## 分隔符（包括 @text##regex 这种情况）
            remaining = line
            while '##' in remaining:
                idx = remaining.index('##')
                if idx > 0:
                    final_lines.append(remaining[:idx])
                remaining = remaining[idx:]
                # 检查是否还有下一个 ##
                next_idx = remaining.find('##', 2)
                if next_idx == -1:
                    # 没有更多 ## 了，剩余部分作为最后一个正则
                    final_lines.append(remaining)
                    break
                else:
                    # 还有更多 ##，继续拆分
                    final_lines.append(remaining[:next_idx])
                    remaining = remaining[next_idx:]
        else:
            final_lines.append(line)
    lines = final_lines

    current = element
    text_result = ""

    for line in lines:
        # @js: 跳过（Python 侧不执行 JS）
        if line.startswith('@js:'):
            continue

        # ##regex##replacement
        if line.startswith('##'):
            parts = line[2:].split('##', 1)
            regex_pat = parts[0]
            replacement = parts[1] if len(parts) > 1 else ''
            text_result = _regex_replace(text_result, regex_pat, replacement)
            continue

        # text 或 text.子选择器
        if line == 'text' or line.startswith('text.'):
            if line.startswith('text.'):
                sub = line[5:].strip()
                if sub:
                    sel = parse_simple_selector(sub)
                    if sel:
                        found = _call_selector(current, sel[0], sel[1])
                        current = found[0] if found else current
            text_result = _get_text(current)
            continue

        # @attr 或 @child_selector 取属性/找子元素
        if line.startswith('@') and not line.startswith('@js:'):
            attr_or_child = line[1:].strip()
            # @text 特殊处理：取文本内容
            if attr_or_child == 'text':
                text_result = _get_text(current)
                continue
            # 先尝试作为子元素选择器查找（支持 .N 索引）
            base_sel, idx = _parse_selector_with_index(attr_or_child)
            child_sel = parse_simple_selector(base_sel)
            if child_sel:
                found = _call_selector(current, child_sel[0], child_sel[1])
                if found:
                    if idx is not None and idx < len(found):
                        current = found[idx]
                    else:
                        current = found[0] if len(found) == 1 else found
                    text_result = ""  # 重置，等后续步骤提取
                    continue
            # 如果没找到子元素，尝试作为属性提取
            if hasattr(current, 'get'):
                text_result = current.get(attr_or_child, '')
            continue

        # 普通选择器 → 在当前元素上继续查找（支持 .N 索引和后代选择器）
        base_sel, idx = _parse_selector_with_index(line)
        sel = parse_simple_selector(base_sel)
        if sel:
            # 检查是否是后代选择器链
            if isinstance(sel, list):
                found = _apply_descendant_selector(current, sel)
            else:
                found = _call_selector(current, sel[0], sel[1])
            if found:
                if idx is not None and idx < len(found):
                    current = found[idx]
                elif len(found) == 1:
                    current = found[0]
                else:
                    current = found
            elif not isinstance(sel, list) and sel[0] == 'find_all' and sel[1].get('name') and not sel[1].get('class_') and not sel[1].get('attrs'):
                # 没找到标签 → 尝试作为属性提取（如 href, src 等）
                attr_name = sel[1]['name']
                if hasattr(current, 'get') and current.get(attr_name):
                    text_result = current.get(attr_name, '')

    return text_result or (_get_text(current) if hasattr(current, 'get_text') else str(current) if current else "")


def apply_selector_list(parent_element, rule_str):
    """返回匹配选择器链的所有元素列表（用于 bookList / chapterList）
    支持后代选择器：'dd h3 a' → 先找 dd，再在每个 dd 中找 h3，再在每个 h3 中找 a
    支持 @ 分隔符链：'#list-chapterAll@dd@a' → 先找 #list-chapterAll，再在其中找 dd，再在 dd 中找 a
    """
    if not rule_str:
        return []

    lines = [l.strip() for l in rule_str.strip().split('\n') if l.strip()]
    if not lines:
        return []

    first_line = lines[0]
    if first_line.startswith('@js:') or first_line.startswith('##') or first_line.startswith('text'):
        return []

    # 检查是否包含 @ 分隔符（链式选择器）
    if '@' in first_line:
        parts = _split_at_signs(first_line)
        # 第一个部分是初始选择器
        first_sel = parse_simple_selector(parts[0])
        if not first_sel:
            return []
        if isinstance(first_sel, list):
            current_elements = _apply_descendant_selector(parent_element, first_sel)
        else:
            current_elements = _call_selector(parent_element, first_sel[0], first_sel[1])
        # 后续 @ 部分依次缩小范围
        for part in parts[1:]:
            if part.startswith('@'):
                part = part[1:]
            if not part or part.startswith('js:'):
                continue
            sel = parse_simple_selector(part)
            if not sel:
                continue
            next_elements = []
            for elem in current_elements:
                if isinstance(sel, list):
                    found = _apply_descendant_selector(elem, sel)
                else:
                    found = _call_selector(elem, sel[0], sel[1])
                next_elements.extend(found)
            current_elements = next_elements
            if not current_elements:
                break
        return current_elements

    sel = parse_simple_selector(first_line)
    if not sel:
        return []

    # 检查是否是后代选择器链
    if isinstance(sel, list):
        return _apply_descendant_selector(parent_element, sel)
    else:
        return _call_selector(parent_element, sel[0], sel[1])


def _get_text(elem):
    if elem is None:
        return ""
    if isinstance(elem, str):
        return elem
    if hasattr(elem, 'get_text'):
        return elem.get_text(strip=True)
    return str(elem)


def _regex_replace(text, pattern, replacement):
    if not text:
        return text
    try:
        if '$1' in replacement:
            m = re.search(pattern, text)
            return m.group(1) if m else text
        return re.sub(pattern, replacement, text)
    except Exception:
        return text


def make_absolute(url, base_url):
    if not url:
        return ""
    if url.startswith('http://') or url.startswith('https://'):
        return url
    return urljoin(base_url, url)


# ===================== Legado 引擎主类 =====================

class LegadoEngine:
    """解析并执行 Legado (阅读) 书源 JSON 规则"""

    def __init__(self, source_def):
        if isinstance(source_def, list):
            source_def = source_def[0] if source_def else {}
        self.source = source_def
        self.base_url = source_def.get('bookSourceUrl', '').rstrip('/')
        self.name = source_def.get('bookSourceName', '').replace('🌙 ', '')
        self.last_page_soup = None  # 保存最后一页的 soup，用于提取上下章链接
        self._default_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        try:
            h = json.loads(source_def.get('header', '{}'))
            if isinstance(h, dict):
                self._default_headers.update(h)
        except Exception:
            pass

    # ---------- HTTP ----------

    def _get_scraper(self):
        return cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
        )

    def _http_get(self, url, timeout=12, charset=None):
        s = self._get_scraper()
        s.headers.update(self._default_headers)
        resp = s.get(url, timeout=timeout)
        return self._decode_response(resp, charset)

    # ---------- 搜索 ----------

    @staticmethod
    def _looks_garbled(text):
        """检测文本是否包含编码乱码特征"""
        if not text:
            return True
        # 统计替换字符和常见乱码模式
        replacement_count = text.count('\ufffd')
        if replacement_count > 3:
            return True
        # 如果几乎找不到中文字符（而期望有），也可能是乱码
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        total_chars = len(text.strip())
        if total_chars > 100 and chinese_chars < 5:
            return True
        return False

    def _decode_response(self, resp, declared_charset):
        """智能解码：先尝试声明编码，再尝试 GBK/UTF-8 交叉，最后用 apparent_encoding"""
        raw = resp.content
        # 收集要尝试的编码列表
        tried = set()
        candidates = []
        if declared_charset:
            candidates.append(declared_charset)
        # 加入常见的中文编码
        for enc in ('utf-8', 'gbk', 'gb2312', 'gb18030'):
            if enc not in tried:
                candidates.append(enc)
        if resp.apparent_encoding:
            candidates.append(resp.apparent_encoding)

        for enc in candidates:
            enc_lower = enc.lower().replace('-', '')
            if enc_lower in tried:
                continue
            tried.add(enc_lower)
            try:
                text = raw.decode(enc)
                if not self._looks_garbled(text):
                    return text
            except (UnicodeDecodeError, LookupError):
                continue
        # 全部失败，用 apparent_encoding 强制解码
        return raw.decode(resp.apparent_encoding or 'utf-8', errors='replace')

    def search(self, keyword):
        rule = self.source.get('ruleSearch', {})
        search_url_conf = self.source.get('searchUrl', '')
        if not search_url_conf or not rule:
            return []

        url_part = search_url_conf.split(',')[0].strip()
        search_url = url_part.replace('{{key}}', quote(keyword))
        # 如果是相对路径，拼接 base_url
        if not search_url.startswith('http://') and not search_url.startswith('https://'):
            search_url = make_absolute(search_url, self.base_url)

        charset = 'utf-8'
        method = 'GET'
        body_template = ''

        if ',' in search_url_conf:
            try:
                opts = json.loads(search_url_conf.split(',', 1)[1])
                charset = opts.get('charset', charset)
                method = opts.get('method', 'GET').upper()
                body_template = opts.get('body', '')
            except Exception:
                pass

        s = self._get_scraper()
        s.headers.update(self._default_headers)

        # 尝试多种编码发送 POST body，选择返回内容最合理的
        best_html = None
        encodings_to_try = list(dict.fromkeys([charset, 'utf-8', 'gbk']))  # 去重保序

        for enc in encodings_to_try:
            try:
                if method == 'POST':
                    body = body_template.replace('{{key}}', keyword)
                    resp = s.post(search_url, data=body.encode(enc),
                                  headers={'Content-Type': f'application/x-www-form-urlencoded; charset={enc}'},
                                  timeout=15)
                else:
                    resp = s.get(search_url, timeout=15)

                html = self._decode_response(resp, enc)
                # 快速检查：HTML 中是否能找到 bookList 对应的元素
                soup_check = BeautifulSoup(html, 'html.parser')
                book_list_check = apply_selector_list(soup_check, rule.get('bookList', ''))
                if book_list_check:
                    best_html = html
                    break
                elif best_html is None:
                    best_html = html
            except Exception:
                continue

        if not best_html:
            return []

        soup = BeautifulSoup(best_html, 'html.parser')

        book_list = apply_selector_list(soup, rule.get('bookList', ''))
        if not book_list:
            # 可能是精确匹配，服务器重定向到了书籍详情页
            detail_result = self._extract_single_from_detail(soup, keyword)
            if detail_result:
                return [detail_result]
            return []

        results = []
        for book_el in book_list:
            item = {'site': self.name}
            for field in ('name', 'author', 'bookUrl', 'coverUrl', 'intro', 'kind', 'lastChapter', 'wordCount'):
                item[field] = apply_selector_chain(book_el, rule.get(field, ''))

            book_url = item.get('bookUrl', '')
            if book_url and not book_url.startswith('http'):
                book_url = make_absolute(book_url, self.base_url)
            item['bookUrl'] = book_url

            cover = item.get('coverUrl', '')
            if cover and not cover.startswith('http'):
                cover = make_absolute(cover, self.base_url)
            item['coverUrl'] = cover

            # 跳过无效结果
            if not item.get('name') or not item.get('bookUrl'):
                continue

            results.append({
                'title': item['name'],
                'url': item['bookUrl'],
                'author': item.get('author', ''),
                'site': self.name,
                'cover': item.get('coverUrl', ''),
                'intro': item.get('intro', ''),
                'kind': item.get('kind', ''),
                'lastChapter': item.get('lastChapter', ''),
            })
        # 关键字匹配验证：过滤不相关的结果
        results = self._filter_by_keyword(results, keyword)
        return results

    def _extract_single_from_detail(self, soup, keyword):
        """当搜索精确匹配到一本书时，从详情页提取书籍信息"""
        # 优先从 og: meta tags 直接提取（最可靠）
        meta_name = soup.find('meta', property='og:novel:book_name')
        name = meta_name.get('content', '').strip() if meta_name else ''

        if not name:
            # fallback: 尝试 ruleBookInfo 选择器
            rule = self.source.get('ruleBookInfo', {})
            if rule:
                name = apply_selector_chain(soup, rule.get('name', ''))
                # 过滤掉过长的结果（可能是整页文本而非书名）
                if name and len(name) > 50:
                    name = ''

        if not name:
            return None

        # 提取其他字段：优先 meta tags，其次选择器
        meta_author = soup.find('meta', property='og:novel:author')
        author = meta_author.get('content', '').strip() if meta_author else ''
        if not author:
            rule = self.source.get('ruleBookInfo', {})
            author = apply_selector_chain(soup, rule.get('author', '')) if rule else ''

        meta_cover = soup.find('meta', property='og:image')
        cover = meta_cover.get('content', '').strip() if meta_cover else ''
        if not cover:
            rule = self.source.get('ruleBookInfo', {})
            cover = apply_selector_chain(soup, rule.get('coverUrl', '')) if rule else ''

        meta_chapter = soup.find('meta', property='og:novel:latest_chapter_name')
        last_chapter = meta_chapter.get('content', '').strip() if meta_chapter else ''
        if not last_chapter:
            rule = self.source.get('ruleBookInfo', {})
            last_chapter = apply_selector_chain(soup, rule.get('lastChapter', '')) if rule else ''

        # 简介：从 bookintro 段落提取
        intro = ''
        intro_el = soup.find('p', class_='bookintro')
        if intro_el:
            intro = intro_el.get_text(strip=True)
        if not intro:
            meta_desc = soup.find('meta', property='og:description')
            if meta_desc:
                intro = meta_desc.get('content', '').strip()

        kind = ''

        if cover and not cover.startswith('http'):
            cover = make_absolute(cover, self.base_url)

        # 从 og:url 或 canonical 获取书籍 URL
        book_url = ''
        meta_url = soup.find('meta', property='og:url')
        if meta_url:
            book_url = meta_url.get('content', '')
        if not book_url:
            canonical = soup.find('link', rel='canonical')
            if canonical:
                book_url = canonical.get('href', '')

        return {
            'title': name,
            'url': book_url or '',
            'author': author,
            'site': self.name,
            'cover': cover,
            'intro': intro,
            'kind': kind,
            'lastChapter': last_chapter,
        }

    def _filter_by_keyword(self, results, keyword):
        """过滤搜索结果，只保留标题包含关键字的"""
        if not keyword or not results:
            return results

        kw = keyword.strip()
        if not kw:
            return results

        filtered = []
        for r in results:
            title = r.get('title', '')
            # 直接包含匹配
            if kw in title:
                filtered.append(r)
                continue
            # 逐字匹配：关键字的每个字符都在标题中出现
            if len(kw) >= 2 and all(c in title for c in kw if c.strip()):
                filtered.append(r)

        # 如果全过滤掉了，返回原始结果（保守策略）
        return filtered if filtered else results

    # ---------- 书籍详情 ----------

    def get_book_info(self, book_url):
        """提取书籍详情信息，优先使用 og: meta tags，其次使用规则选择器"""
        rule = self.source.get('ruleBookInfo', {})
        if not rule:
            return None
        html = self._http_get(book_url)
        soup = BeautifulSoup(html, 'html.parser')
        info = {}
        
        # 优先从 og: meta tags 提取（最可靠）
        meta_name = soup.find('meta', property='og:novel:book_name')
        info['name'] = meta_name.get('content', '').strip() if meta_name else ''
        
        meta_author = soup.find('meta', property='og:novel:author')
        info['author'] = meta_author.get('content', '').strip() if meta_author else ''
        
        meta_cover = soup.find('meta', property='og:image')
        info['coverUrl'] = meta_cover.get('content', '').strip() if meta_cover else ''
        
        meta_desc = soup.find('meta', property='og:description')
        info['intro'] = meta_desc.get('content', '').strip() if meta_desc else ''
        
        meta_chapter = soup.find('meta', property='og:novel:latest_chapter_name')
        info['lastChapter'] = meta_chapter.get('content', '').strip() if meta_chapter else ''
        
        # 更新时间
        meta_update = soup.find('meta', property='og:novel:update_time')
        info['updateTime'] = meta_update.get('content', '').strip() if meta_update else ''
        
        # 如果 meta tags 中没有，再尝试用规则选择器
        if not info['name']:
            info['name'] = apply_selector_chain(soup, rule.get('name', ''))
        if not info['author']:
            info['author'] = apply_selector_chain(soup, rule.get('author', ''))
        if not info['coverUrl']:
            info['coverUrl'] = apply_selector_chain(soup, rule.get('coverUrl', ''))
        if not info['intro']:
            # 特殊处理 intro：尝试 p.bookintro
            intro_p = soup.find('p', class_='bookintro')
            if intro_p:
                info['intro'] = intro_p.get_text(strip=True)
            else:
                info['intro'] = apply_selector_chain(soup, rule.get('intro', ''))
        if not info['lastChapter']:
            info['lastChapter'] = apply_selector_chain(soup, rule.get('lastChapter', ''))
        
        # 更新时间回退：从 .uptime 或 .info 区域提取
        if not info.get('updateTime'):
            uptime_el = soup.find(class_='uptime')
            if uptime_el:
                time_el = uptime_el.find('time')
                if time_el:
                    info['updateTime'] = time_el.get_text(strip=True)
                else:
                    t = uptime_el.get_text(strip=True)
                    t = re.sub(r'^更新时间[：:\s]*', '', t).strip()
                    if t:
                        info['updateTime'] = t
        
        # 验证 og:image URL 有效性（某些站点会双重拼接导致 URL 无效）
        if info.get('coverUrl'):
            url_val = info['coverUrl']
            if url_val.count('https://') > 1 or url_val.count('http://') > 1:
                info['coverUrl'] = ''  # URL 无效，清空让回退逻辑生效
        
        # 封面回退：从 .cover img 等常见位置提取
        if not info.get('coverUrl'):
            cover_img = soup.select_one('.cover img') or soup.select_one('.pic img') or soup.select_one('.bookimg img')
            if cover_img:
                src = cover_img.get('src', '') or cover_img.get('data-src', '')
                if src:
                    info['coverUrl'] = make_absolute(src, self.base_url)
        
        info['kind'] = apply_selector_chain(soup, rule.get('kind', ''))
        info['wordCount'] = apply_selector_chain(soup, rule.get('wordCount', ''))
        
        # 清理作者名（去掉多余的元信息拼接）
        if info.get('author'):
            for sep in ['状态', '更新', '最新', '字数', '分类', '连载', '完结']:
                idx = info['author'].find(sep)
                if idx > 0:
                    info['author'] = info['author'][:idx].strip(' ,，.。')
            if len(info['author']) > 20:
                info['author'] = ''
        
        # 清理过长的字段（可能是错误提取）
        if info.get('intro') and len(info['intro']) > 1000:
            info['intro'] = info['intro'][:500] + '...'
        
        if info.get('coverUrl') and not info['coverUrl'].startswith('http'):
            info['coverUrl'] = make_absolute(info['coverUrl'], self.base_url)
        
        return info

    # ---------- 目录 ----------

    def get_toc(self, toc_url):
        rule = self.source.get('ruleToc', {})
        if not rule:
            return []
        html = self._http_get(toc_url, timeout=20)
        soup = BeautifulSoup(html, 'html.parser')

        chapter_els = apply_selector_list(soup, rule.get('chapterList', ''))
        chapters = []
        for el in chapter_els:
            name = apply_selector_chain(el, rule.get('chapterName', ''))
            href = apply_selector_chain(el, rule.get('chapterUrl', ''))
            if name and href:
                chapters.append((name, make_absolute(href, toc_url)))

        # 分页目录
        next_rule = rule.get('nextTocUrl', '')
        if next_rule and self._is_js_rule(next_rule):
            extra_urls = self._extract_js_page_urls(next_rule, toc_url, html)
            for page_url in extra_urls:
                try:
                    page_html = self._http_get(page_url, timeout=20)
                    page_soup = BeautifulSoup(page_html, 'html.parser')
                    page_els = apply_selector_list(page_soup, rule.get('chapterList', ''))
                    for el in page_els:
                        name = apply_selector_chain(el, rule.get('chapterName', ''))
                        href = apply_selector_chain(el, rule.get('chapterUrl', ''))
                        if name and href:
                            full_url = make_absolute(href, page_url)
                            if full_url not in [c[1] for c in chapters]:
                                chapters.append((name, full_url))
                except Exception:
                    pass

        return chapters

    def _is_js_rule(self, rule_str):
        rule_str = rule_str.strip()
        return rule_str.startswith('<js>') or rule_str.startswith('@js:') or rule_str.startswith('@js\n')

    def _extract_js_page_urls(self, js_rule, base_url, html):
        """从 <js>...</js> 规则中提取分页 URL 列表"""
        soup = BeautifulSoup(html, 'html.parser')
        pagestats = soup.find(id='pagestats')
        pagestats_text = pagestats.get_text(strip=True) if pagestats else ''

        max_page = 0
        m = re.search(r'/(\d+)', pagestats_text)
        if m:
            max_page = int(m.group(1))

        id_match = re.search(r'/(?:index|books)/(\d+)', base_url)
        book_id = id_match.group(1) if id_match else ''

        urls = []
        if book_id and max_page > 1:
            for i in range(2, max_page + 1):
                urls.append(f"{self.base_url}/index/{book_id}/{i}")
        return urls

    # ---------- 章节正文 ----------

    def get_content(self, chapter_url):
        self.last_page_soup = None  # 重置
        rule_content = self.source.get('ruleContent', {})
        charset = None
        try:
            h = json.loads(self.source.get('header', '{}'))
            charset = h.get('charset')
        except Exception:
            pass

        s = self._get_scraper()
        s.headers.update(self._default_headers)
        resp = s.get(chapter_url, timeout=15)
        html = self._decode_response(resp, charset)
        soup = BeautifulSoup(html, 'html.parser')

        content_rule = rule_content.get('content', '')

        # 歪歪书库专用处理（多页合并）
        if 'yysk.net' in chapter_url:
            content = self._yysk_content(chapter_url, html, soup, rule_content)
            if content and '未找到' not in content:
                return content

        # JS 规则 → 走特殊提取路径
        if content_rule and self._is_js_rule(content_rule):
            content = self._deqi_js_content(chapter_url, html, soup, rule_content)
            if content and '未找到' not in content:
                return content
            # 回退：尝试 fallback 元素
            fallback = soup.find(id='rtext')
            if fallback:
                for tag in fallback.find_all(['script', 'style']):
                    tag.decompose()
                text = fallback.get_text(separator='\n', strip=True)
                if text and len(text) > 50:
                    return self._apply_replace_rule(text, rule_content.get('replaceRegex', ''))
            return content or '章节内容获取失败'

        # 纯 CSS 规则
        if content_rule:
            content = apply_selector_chain(soup, content_rule)
            if content:
                # 如果是 HTML 内容（通过 @html 规则获取），清理标签
                if '<' in content and '>' in content:
                    content = re.sub(r'<br\s*/?>', '\n', content, flags=re.IGNORECASE)
                    content = re.sub(r'<[^>]+>', '', content)
                return self._apply_replace_rule(content, rule_content.get('replaceRegex', ''))

        return '未找到正文内容'

    def _deqi_js_content(self, chapter_url, html, soup, rule_content):
        """得奇专用：从 JS 中提取 token，AJAX 拉取正文，支持多页合并"""
        try:
            import cloudscraper
            s = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
            )
            s.headers.update(self._default_headers)

            # 递归获取所有分页内容
            all_parts = []
            current_url = chapter_url
            current_soup = soup
            visited = set()
            last_soup = None

            while current_url and current_url not in visited:
                visited.add(current_url)

                # 获取当前页的内容
                text, next_page_url, page_soup = self._deqi_fetch_page_content(s, current_url, current_soup)
                if not text:
                    break

                all_parts.append(text)
                last_soup = page_soup  # 记录当前页的 soup

                # 如果没有下一页，结束
                if not next_page_url:
                    break

                current_url = next_page_url
                current_soup = None  # 后续页面需要重新获取 soup

            # 保存最后一页的 soup，供 _run_legado 提取上下章链接
            self.last_page_soup = last_soup

            if all_parts:
                combined = '\n'.join(all_parts)
                # 清理多余空行
                combined = re.sub(r'\n+', '\n', combined).strip()
                return self._apply_replace_rule(combined, rule_content.get('replaceRegex', ''))

            return self._fallback_content(soup, rule_content)
        except Exception as e:
            return f"章节内容获取失败: {e}"

    def _deqi_fetch_page_content(self, scraper, page_url, page_soup):
        """获取得奇某一页的 AJAX 正文内容和下一页URL
        返回: (text_content, next_page_url, page_soup) 或 (None, None, None)
        """
        # 从 URL 中提取 aid 和 cid
        url_match = re.search(r'/(\d+)/(\d+)\.html', page_url)
        if not url_match:
            return None, None, None

        aid, cid = url_match.group(1), url_match.group(2)
        parsed = urlparse(page_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        # 获取 token / timestamp / nonce
        js_url = f"{origin}/scripts/chapter.js.php?aid={aid}&cid={cid}&referrer={page_url}"
        script_text = scraper.get(js_url, timeout=10).text

        token = re.search(r"chapterToken\s*=\s*['\"]([^'\"]+)['\"]", script_text)
        ts = re.search(r"timestamp\s*=\s*([\"']?)([^\"';\s]+)\1", script_text)
        nonce = re.search(r"nonce\s*=\s*['\"]([^'\"]+)['\"]", script_text)

        if not (token and ts and nonce):
            return None, None, None

        # AJAX 获取正文（得奇 JSON 响应为 GBK 编码）
        ajax_url = f"{origin}/modules/article/ajax2.php"
        params = {
            "aid": aid,
            "cid": cid,
            "token": token.group(1),
            "timestamp": ts.group(2),
            "nonce": nonce.group(1),
        }
        ajax_headers = {
            "Referer": page_url,
            "X-Requested-With": "XMLHttpRequest",
        }

        ajax_resp = scraper.get(ajax_url, params=params, headers=ajax_headers, timeout=15)
        # 得奇 ajax2.php 返回的 JSON 是 GBK 编码，必须强制 GBK
        ajax_resp.encoding = "gbk"
        data = json.loads(ajax_resp.text)

        if not (data.get('data') and data['data'].get('content')):
            return None, None, None

        content_html = data['data']['content']
        # <br> -> 换行，再去标签
        text = re.sub(r'<br\s*/?>', '\n', content_html, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\n+', '\n', text).strip()
        # 清理 HTML 实体残留（包括双重编码）
        text = text.replace('&larr;', '').replace('&rarr;', '')
        text = text.replace('&amp;larr;', '').replace('&amp;rarr;', '')
        text = text.replace('←', '').replace('→', '')

        # 查找"下一页"链接来确定是否还有更多页面
        next_url = None
        soup_to_use = page_soup
        if soup_to_use is None:
            try:
                resp = scraper.get(page_url, timeout=10)
                resp.encoding = resp.apparent_encoding
                soup_to_use = BeautifulSoup(resp.text, 'html.parser')
            except Exception:
                pass

        if soup_to_use is not None:
            next_link = soup_to_use.find('a', string='下一页')
            if not next_link:
                next_link = soup_to_use.find('a', string=re.compile(r'下一页'))
            if next_link:
                href = next_link.get('href')
                if href:
                    abs_url = urljoin(page_url, href)
                    # 验证是否同一章（相同 aid 和 cid）
                    next_match = re.search(r'/(\d+)/(\d+)\.html', abs_url)
                    if next_match and next_match.group(1) == aid and next_match.group(2) == cid:
                        next_url = abs_url

        return text, next_url, soup_to_use

    def _fallback_content(self, soup, rule_content):
        """回退：从 #rtext 元素取内容"""
        fallback = soup.find(id='rtext')
        if fallback:
            for tag in fallback.find_all(['script', 'style']):
                tag.decompose()
            text = fallback.get_text(separator='\n', strip=True)
            if text:
                return self._apply_replace_rule(text, rule_content.get('replaceRegex', ''))
        return '未找到正文内容（JS提取失败，请重试）'

    def _yysk_content(self, chapter_url, html, soup, rule_content):
        """歪歪书库专用：提取正文并支持多页合并"""
        try:
            import cloudscraper
            s = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
            )
            s.headers.update(self._default_headers)

            all_parts = []
            current_url = chapter_url
            current_soup = soup
            visited = set()
            last_soup = None

            while current_url and current_url not in visited:
                visited.add(current_url)

                # 提取当前页内容和下一页URL
                text, next_page_url, page_soup = self._yysk_fetch_page(s, current_url, current_soup)
                if not text:
                    break

                all_parts.append(text)
                last_soup = page_soup

                if not next_page_url:
                    break

                current_url = next_page_url
                current_soup = None

            # 保存最后一页的 soup，供导航链接提取
            self.last_page_soup = last_soup

            if all_parts:
                combined = '\n'.join(all_parts)
                # 清理多余空行
                combined = re.sub(r'\n+', '\n', combined).strip()
                # 清理页码标记 如 第(1/3)页
                combined = re.sub(r'第\(\d+/\d+\)页', '', combined)
                # 清理 &nbsp; 实体
                combined = combined.replace('&nbsp;', ' ').replace('\xa0', ' ')
                return self._apply_replace_rule(combined, rule_content.get('replaceRegex', ''))

            return '未找到正文内容'
        except Exception as e:
            return f"章节内容获取失败: {e}"

    def _yysk_fetch_page(self, scraper, page_url, page_soup):
        """获取歪歪书库某一页的内容和下一页URL
        返回: (text_content, next_page_url, page_soup)
        """
        # 获取页面 soup（如果未提供）
        soup_to_use = page_soup
        if soup_to_use is None:
            try:
                resp = scraper.get(page_url, timeout=10)
                resp.encoding = resp.apparent_encoding
                soup_to_use = BeautifulSoup(resp.text, 'html.parser')
            except Exception:
                return None, None, None

        if soup_to_use is None:
            return None, None, None

        # 提取正文内容（在 article.font_max 中）
        article = soup_to_use.find('article', class_='font_max')
        if not article:
            article = soup_to_use.find('article')
        if not article:
            return None, None, None

        # 获取文本内容
        text = article.get_text(separator='\n', strip=True)
        # 清理 &nbsp;
        text = text.replace('\xa0', ' ')
        text = re.sub(r' +', ' ', text).strip()

        # 查找“下一章”链接
        next_url = None
        next_link = soup_to_use.find('a', id='next1')
        if not next_link:
            next_link = soup_to_use.find('a', string=re.compile(r'下一章'))
        
        if next_link:
            href = next_link.get('href')
            if href:
                abs_url = urljoin(page_url, href)
                # 判断是否是同章分页（URL包含 _数字.html 模式）
                # 例如: 164138.html -> 164138_2.html -> 164138_3.html
                current_match = re.search(r'/(\d+)_(\d+)\.html', page_url)
                next_match = re.search(r'/(\d+)_(\d+)\.html', abs_url)
                
                # 如果当前页是第1页（无 _N 后缀），下一页是 _2.html
                current_base_match = re.search(r'/(\d+)\.html', page_url)
                next_page2_match = re.search(r'/(\d+)_2\.html', abs_url)
                
                # 判断是否为同章分页
                is_same_chapter = False
                if current_match and next_match:
                    # 当前页是 _N.html 格式，下一页也是 _M.html 格式
                    if current_match.group(1) == next_match.group(1):
                        is_same_chapter = True
                elif current_base_match and next_page2_match:
                    # 当前页是第1页，下一页是 _2.html
                    if current_base_match.group(1) == next_page2_match.group(1):
                        is_same_chapter = True
                
                if is_same_chapter:
                    next_url = abs_url

        return text, next_url, soup_to_use

    def _apply_replace_rule(self, text, replace_rule):
        """应用 replaceRegex 清理规则"""
        if not replace_rule or not text:
            return text
        if self._is_js_rule(replace_rule):
            # @js: 规则 → 尝试从 JS 中提取正则并应用
            return self._apply_js_replace(text, replace_rule)
        # 普通 ##regex##replacement
        return _regex_replace(text, replace_rule.lstrip('#'), '')

    def _apply_js_replace(self, text, js_rule):
        """
        尝试解析 @js: 中的 FILTER_RULES 正则数组并逐一替换
        仅支持简单的 result = result.replace(/regex/g, "") 形式
        """
        # 提取所有 /regex/flags 格式的正则
        patterns = re.findall(r"/([^/]+)/([gimsuy]*)", js_rule)
        for pat, flags in patterns:
            try:
                re_flags = 0
                if 'i' in flags:
                    re_flags |= re.IGNORECASE
                if 'm' in flags:
                    re_flags |= re.MULTILINE
                text = re.sub(pat, '', text, flags=re_flags)
            except Exception:
                pass
        # 处理 ^(?=...)(?=.*章).+\n 这种删除章节标题行的模式
        chapter_line_pattern = re.compile(r'^(?=.*[1-9])(?=.*章).+\n', re.MULTILINE)
        text = chapter_line_pattern.sub('', text)
        return text.strip()

    # ---------- 分类浏览 ----------

    def get_explore_categories(self):
        explore_str = self.source.get('exploreUrl', '')
        if not explore_str:
            return []
        try:
            items = json.loads(explore_str)
        except Exception:
            return []
        categories = []
        for item in items:
            title = item.get('title', '')
            url = item.get('url', '')
            if not title:
                continue
            if url.startswith('/'):
                url = self.base_url + url
            url = url.replace('{{page}}', '1')
            categories.append({'title': title, 'url': url})
        return categories

    def get_explore_results(self, explore_url, page=1):
        """浏览某个分类，返回书籍列表"""
        url = explore_url.replace('{{page}}', str(page))
        if not url.startswith('http'):
            url = self.base_url + url

        html = self._http_get(url, timeout=15)
        soup = BeautifulSoup(html, 'html.parser')

        # 复用 ruleExplore 规则
        rule = self.source.get('ruleExplore', self.source.get('ruleSearch', {}))
        if not rule:
            return []

        book_list = apply_selector_list(soup, rule.get('bookList', ''))
        results = []
        for book_el in book_list:
            item = {'site': self.name}
            for field in ('name', 'author', 'bookUrl', 'coverUrl', 'intro', 'kind', 'lastChapter', 'wordCount'):
                item[field] = apply_selector_chain(book_el, rule.get(field, ''))

            book_url = item.get('bookUrl', '')
            if book_url and not book_url.startswith('http'):
                book_url = make_absolute(book_url, self.base_url)
            item['bookUrl'] = book_url

            cover = item.get('coverUrl', '')
            if cover and not cover.startswith('http'):
                cover = make_absolute(cover, self.base_url)
            item['coverUrl'] = cover

            results.append({
                'title': item.get('name', ''),
                'url': item.get('bookUrl', ''),
                'author': item.get('author', ''),
                'site': self.name,
                'cover': item.get('coverUrl', ''),
                'intro': item.get('intro', ''),
                'kind': item.get('kind', ''),
                'lastChapter': item.get('lastChapter', ''),
            })
        return results


# ===================== 全局 Legado 源注册表 =====================
# 记录哪些 URL 来自哪个 Legado 源，供 FetchWorker/TocFetchWorker 使用

_legado_registry = {}


def _get_data_dir():
    """获取用户数据目录（与 utils.py 中 get_data_dir 保持一致）"""
    if getattr(sys, 'frozen', False):
        if sys.platform == "darwin":
            base = os.path.expanduser('~/Library/Application Support')
        else:
            base = os.environ.get('APPDATA', os.path.expanduser('~'))
        return os.path.join(base, 'YReader')
    else:
        return os.path.dirname(os.path.abspath(__file__))


def register_legado_url(url, source_def):
    """将某个 URL 注册为属于某个 Legado 源"""
    if url:
        _legado_registry[url] = source_def


def get_legado_source_for_url(url):
    """检查某个 URL 是否来自已注册的 Legado 源"""
    if url in _legado_registry:
        return _legado_registry[url]
    # 按域名模糊匹配（同一本书的不同页面）
    try:
        url_host = urlparse(url).netloc
        for reg_url, src in _legado_registry.items():
            if urlparse(reg_url).netloc == url_host:
                return src
    except Exception:
        pass
    # 按域名匹配已配置的 Legado 书源（支持直接粘贴 URL）
    try:
        url_host = urlparse(url).netloc
        sources_file = os.path.join(_get_data_dir(), 'legado_sources.json')
        if os.path.exists(sources_file):
            with open(sources_file, 'r', encoding='utf-8') as f:
                sources = json.load(f)
            for group in sources:
                base_url = group.get('base_url', '')
                if base_url and urlparse(base_url).netloc == url_host:
                    src_data = group.get('source_data', [{}])[0]
                    if src_data:
                        return src_data
    except Exception:
        pass
    return None


def clear_legado_registry():
    _legado_registry.clear()
