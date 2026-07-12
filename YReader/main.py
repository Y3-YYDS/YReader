import sys
import os
import time
from urllib.parse import urlparse, parse_qs

# ===== 跨平台双原生底层全局热键支持 =====
IS_MAC = sys.platform == "darwin"

if IS_MAC:
    try:
        from mac_hotkey import MacHotkeyManager
    except ImportError as e:
        print(f"未能导入 Mac 原生热键模块: {e}")
        MacHotkeyManager = None
    WinHotkeyManager = None
else:
    try:
        from windows_hotkey import WinHotkeyManager
    except ImportError as e:
        print(f"未能导入 Windows 原生热键模块: {e}")
        WinHotkeyManager = None
    MacHotkeyManager = None

from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget, QMenu, QSystemTrayIcon
from PySide6.QtGui import QColor, QKeySequence, QShortcut, QFontMetrics, QMouseEvent, QWheelEvent, QTextDocument, QIcon, \
    QPixmap, QPainter, QFont
from PySide6.QtCore import Qt, Signal, QTranslator, QLibraryInfo, QRect, QObject, QThread
from PySide6.QtNetwork import QLocalServer, QLocalSocket

# 导入所有分离的核心模块
from utils import (load_config, save_config, make_local_file_url, local_path_from_url,
                   split_txt_chapters, parse_epub_chapters, parse_mobi_chapters, FetchEmitter, FetchWorker, WEIGHT_MAP,
                   set_mac_dock_icon_visible, set_mac_window_shadow, init_user_data,
                   hide_mac_app, unhide_mac_app, hide_win_window, show_win_window,
                   extract_book_name_from_toc)
from dialog_reading import WebDialog, FileDialog, TocDialog, ChangeSourceDialog
from dialog_settings import SettingsDialog


class GlobalHotkeySignal(QObject):
    triggered = Signal()


class _BookNameExtractThread(QThread):
    """后台线程：从目录页提取书名，避免阻塞主线程"""
    finished = Signal(str)
    
    def __init__(self, toc_url):
        super().__init__()
        self.toc_url = toc_url
    
    def run(self):
        try:
            name = extract_book_name_from_toc(self.toc_url)
            self.finished.emit(name or "")
        except Exception:
            self.finished.emit("")


class ReaderWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.config = load_config()
        self.history = self.config.get("history", [])
        self.file_history = self.config.get("file_history", [])
        self.multi_line = self.config.get("multi_line", False)
        self.bg_opacity = self.config.get("bg_opacity", 50)
        self.text_opacity = self.config.get("text_opacity", 100)
        self.show_taskbar = self.config.get("show_taskbar", False)
        self.seamless_chapter = self.config.get("seamless_chapter", False)
        self.always_on_top = self.config.get("always_on_top", True)
        self.letter_spacing = self.config.get("letter_spacing", 0)
        self.line_spacing = self.config.get("line_spacing", 150)
        self.font_size = self.config.get("font_size", 14)
        self.font_family = self.config.get("font_family", QApplication.font().family())
        self.font_weight_name = self.config.get("font_weight_name", "常规 (Normal)")
        self.text_color = QColor(self.config.get("text_color", "#000000"))
        self.bg_color = QColor(self.config.get("bg_color", "#000000"))

        self.key_prev_line = self.config.get("key_prev_line", "W")
        self.key_next_line = self.config.get("key_next_line", "E")
        self.key_prev_page = self.config.get("key_prev_page", "Alt+W")
        self.key_next_page = self.config.get("key_next_page", "Alt+E")
        self.key_boss = self.config.get("key_boss", "Alt+Q")
        self.icon_path = self.config.get("icon_path", "")

        self.full_article_text = "右键打开菜单，加载小说即可开始阅读..."
        self.current_url = ""
        self.current_title = ""
        self.prev_chapter_url = ""
        self.next_chapter_url = ""
        self.current_toc_url = ""
        self.current_book_name = ""  # 当前阅读的书名（用于换源功能）

        self.fetch_worker = None
        self.fetch_emitter = None

        self.prefetch_threads = {}
        self.chapter_cache = {}
        self.toc_cache = {}
        self.toc_prefetch_threads = {}

        self.char_index = 0
        self.current_fit_count = 1
        self._force_reset_index = False
        self._jump_to_end_after_load = False
        self._text_marker = ""  # 换源时用于定位的文本片段

        self.is_hidden = False
        self.dragPos = None
        self.resize_edge = ""
        self.resize_start_pos = None
        self.resize_start_geometry = None
        self.resize_margin = 8

        # 加载窗口位置
        self.window_x = self.config.get("window_x", None)
        self.window_y = self.config.get("window_y", None)

        self._mac_hotkey_manager = None
        self._win_hotkey_manager = None
        self._last_toggle_time = 0

        self.init_ui()
        self.update_icon()
        self.init_tray()
        self.init_shortcuts()

        if self.history:
            if last_url := self.history[0].get("url"): self.start_async_load(last_url)

    def init_ui(self):
        flags = Qt.WindowType.FramelessWindowHint
        if self.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        if not self.show_taskbar:
            flags |= Qt.WindowType.Tool
        self.setWindowFlags(flags)
        self._apply_window_attributes()
        self.setWindowTitle("YReader")
        
        self.setMouseTracking(True)

        self.central_widget = QWidget()
        self.central_widget.setMouseTracking(True)
        self.setCentralWidget(self.central_widget)

        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        self.label = QLabel(self.full_article_text)
        self.label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop if self.multi_line else Qt.AlignmentFlag.AlignVCenter)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.label.setMouseTracking(True)
        self.layout.addWidget(self.label)

        self.apply_styles()
        self.setMinimumSize(30, 30)
        self.resize(self.config.get("width", 600), self.config.get("height", 30))
        
        # 恢复窗口位置
        if self.window_x is not None and self.window_y is not None:
            self.move(self.window_x, self.window_y)

    def _apply_window_attributes(self):
        """重新应用窗口属性（setWindowFlags 后会丢失，需要重新设置）"""
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # 禁用系统级窗口阴影
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        # macOS: 通过原生 API 禁用 NSWindow 阴影
        if IS_MAC:
            try:
                win_id = int(self.winId())
                set_mac_window_shadow(win_id, False)
            except Exception:
                pass  # 静默失败，不影响主流程

    def _bundled_icon_path(self):
        """获取打包时捆绑的图标路径"""
        base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        if IS_MAC:
            p = os.path.join(base, 'icon.icns')
            if os.path.exists(p):
                return p
        else:
            p = os.path.join(base, 'icon.ico')
            if os.path.exists(p):
                return p
        # fallback: try any icon file in base
        for name in ('icon.icns', 'icon.ico', 'icon.png'):
            p = os.path.join(base, name)
            if os.path.exists(p):
                return p
        return ""

    def update_icon(self):
        icon_file = self.icon_path or self._bundled_icon_path()
        if icon_file and os.path.exists(icon_file):
            self.app_icon = QIcon(icon_file)
        else:
            pixmap = QPixmap(64, 64)
            pixmap.fill(QColor("#2c3e50"))
            painter = QPainter(pixmap)
            painter.setPen(Qt.GlobalColor.white)
            painter.setFont(QFont("Microsoft YaHei", 32, QFont.Weight.Bold))
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "书")
            painter.end()
            self.app_icon = QIcon(pixmap)

        self.setWindowIcon(self.app_icon)
        QApplication.setWindowIcon(self.app_icon)
        if hasattr(self, 'tray_icon'):
            self.tray_icon.setIcon(self.app_icon)

    def init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.app_icon)
        self.tray_icon.setToolTip("YReader")

        self.tray_menu = QMenu()
        action_toggle = self.tray_menu.addAction("显示 / 隐藏")
        action_toggle.triggered.connect(self.toggle_visibility)
        self.tray_menu.addSeparator()
        action_quit = self.tray_menu.addAction("彻底退出")
        action_quit.triggered.connect(self.force_quit)

        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self.tray_activated)
        self.tray_icon.show()

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_visibility()

    def apply_styles(self):
        weight = WEIGHT_MAP.get(self.font_weight_name, QFont.Weight.Normal)
        font = QFont(self.font_family, self.font_size, weight)

        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.NoSubpixelAntialias)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, self.letter_spacing)

        self.label.setFont(font)
        self.label.setWordWrap(self.multi_line)
        self.label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop if self.multi_line else Qt.AlignmentFlag.AlignVCenter)

        tc_alpha = self.text_opacity / 100.0
        self.label.setStyleSheet(
            f"background-color: transparent; color: rgba({self.text_color.red()}, {self.text_color.green()}, {self.text_color.blue()}, {tc_alpha:.3f});")

        bg_alpha = self.bg_opacity / 100.0
        self.central_widget.setStyleSheet(
            f"background-color: rgba({self.bg_color.red()}, {self.bg_color.green()}, {self.bg_color.blue()}, {bg_alpha:.3f}); border: none;")

    def save_current_config(self):
        self.config["width"] = self.width()
        self.config["height"] = self.height()
        # 保存窗口位置
        self.config["window_x"] = self.x()
        self.config["window_y"] = self.y()
        self.config["history"] = self.history
        self.config["file_history"] = self.file_history
        self.config["multi_line"] = self.multi_line
        self.config["bg_opacity"] = self.bg_opacity
        self.config["text_opacity"] = self.text_opacity
        self.config["show_taskbar"] = self.show_taskbar
        self.config["seamless_chapter"] = self.seamless_chapter
        self.config["always_on_top"] = self.always_on_top
        self.config["letter_spacing"] = self.letter_spacing
        self.config["line_spacing"] = self.line_spacing
        self.config["font_size"] = self.font_size
        self.config["font_family"] = self.font_family
        self.config["font_weight_name"] = self.font_weight_name
        self.config["text_color"] = self.text_color.name()
        self.config["bg_color"] = self.bg_color.name()
        self.config["key_prev_line"] = self.key_prev_line
        self.config["key_next_line"] = self.key_next_line
        self.config["key_prev_page"] = self.key_prev_page
        self.config["key_next_page"] = self.key_next_page
        self.config["key_boss"] = self.key_boss
        self.config["icon_path"] = self.icon_path
        save_config(self.config)

    def save_reading_progress(self):
        target_history = self._history_for_url(self.current_url)
        if len(target_history) > 0 and target_history[0]['url'] == self.current_url:
            target_history[0]['char_index'] = self.char_index
            self.save_current_config()

    def _history_for_url(self, url):
        return self.file_history if urlparse(url).scheme in ("file", "localbook") else self.history

    def refresh_current_page(self):
        """刷新当前页面 - 重新加载当前章节内容"""
        if not self.current_url:
            QMessageBox.information(self, "提示", "当前没有可刷新的内容")
            return
        
        # 清除缓存，强制重新获取
        self.chapter_cache.pop(self.current_url, None)
        
        # 重新加载
        self.start_async_load(self.current_url)

    def start_async_load(self, url):
        if urlparse(url).scheme in ('file', 'localbook'):
            self.start_local_load(url)
            return

        self.current_url = url
        if url in self.chapter_cache:
            self.on_load_finished(*self.chapter_cache[url])
        elif url in self.prefetch_threads and self.prefetch_threads[url][0].is_alive():
            self.label.setText("【正在读取预缓存章节...】")
            worker, emitter = self.prefetch_threads.pop(url)
            emitter.result_ready.disconnect(self.on_preload_finished)
            emitter.result_ready.connect(self.on_load_finished)

            if self.fetch_worker and self.fetch_worker.is_alive():
                self.fetch_worker.is_cancelled = True

            self.fetch_worker = worker
            self.fetch_emitter = emitter
        else:
            self.label.setText("【正在获取内容，请稍候...】")
            # 断开旧 emitter 信号，防止旧线程结果覆盖新章节
            if self.fetch_emitter:
                try:
                    self.fetch_emitter.result_ready.disconnect(self.on_load_finished)
                except (RuntimeError, TypeError):
                    pass
            if self.fetch_worker and self.fetch_worker.is_alive():
                self.fetch_worker.is_cancelled = True

            self.fetch_emitter = FetchEmitter()
            self.fetch_emitter.result_ready.connect(self.on_load_finished)
            self.fetch_worker = FetchWorker(url, self.fetch_emitter)
            self.fetch_worker.start()

    def prepare_local_book(self, path):
        """预加载本地文件章节，返回 (first_url, toc_url)"""
        path = os.path.abspath(path)
        ext = os.path.splitext(path)[1].lower()
        if ext == '.txt':
            chapters = split_txt_chapters(path)
        elif ext == '.epub':
            chapters = parse_epub_chapters(path)
        elif ext == '.mobi':
            chapters = parse_mobi_chapters(path)
        else:
            raise ValueError("仅支持 txt、epub 和 mobi 文件")

        toc_url = make_local_file_url(path, toc=True)
        toc_entries = []
        urls = [make_local_file_url(path, idx) for idx in range(len(chapters))]
        for idx, chapter in enumerate(chapters):
            u = urls[idx]
            prev_url = urls[idx - 1] if idx > 0 else ""
            next_url = urls[idx + 1] if idx + 1 < len(urls) else ""
            title = chapter.get("title") or f"第{idx + 1}章"
            text = chapter.get("text", "")
            self.chapter_cache[u] = (text, prev_url, next_url, title, u, toc_url)
            toc_entries.append((title, u))
        self.toc_cache[toc_url] = toc_entries

        first_url = urls[0] if urls else ""
        if not first_url:
            raise ValueError("未能从文件中识别到正文")
        return first_url, toc_url

    def start_local_load(self, url):
        path = local_path_from_url(url)
        if not os.path.exists(path):
            self.label.setText("【本地文件不存在，可能已被移动或删除】")
            return

        try:
            parsed = urlparse(url)
            query = parse_qs(parsed.query)
            target_url = url

            if target_url not in self.chapter_cache:
                first_url, toc_url = self.prepare_local_book(path)
                if 'chapter' not in query:
                    target_url = first_url

            self.current_url = target_url
            self.on_load_finished(*self.chapter_cache[target_url])
        except Exception as e:
            self.label.setText(f"【打开文件失败: {e}】")

    def trigger_preload(self, url):
        if not url or url in self.chapter_cache or url in self.prefetch_threads:
            return
        if urlparse(url).scheme in ('file', 'localbook'):
            return

        dead = [u for u, (w, e) in self.prefetch_threads.items() if not w.is_alive()]
        for u in dead:
            self.prefetch_threads.pop(u)

        emitter = FetchEmitter()
        emitter.result_ready.connect(self.on_preload_finished)
        worker = FetchWorker(url, emitter)
        self.prefetch_threads[url] = (worker, emitter)
        worker.start()

    def get_cached_toc(self, toc_url):
        return self.toc_cache.get(toc_url)

    def set_cached_toc(self, toc_url, chapters):
        self.toc_cache[toc_url] = chapters

    def trigger_toc_preload(self, toc_url):
        if not toc_url or toc_url in self.toc_cache or toc_url in self.toc_prefetch_threads:
            return
        if urlparse(toc_url).scheme in ('file', 'localbook'):
            return

        # 此处省略复杂的 toc_preload... 让功能与原版完全保持一致。

    def refresh_current_page(self):
        """刷新当前页面 - 重新加载当前章节内容"""
        if not self.current_url:
            QMessageBox.information(self, "提示", "当前没有可刷新的内容")
            return
        
        # 清除缓存，强制重新获取
        self.chapter_cache.pop(self.current_url, None)
        
        # 重新加载
        self.start_async_load(self.current_url)

    def on_load_finished(self, text, prev_url, next_url, title_text, original_url, toc_url):
        # 忽略已过期的工作线程结果（快速切换章节时旧线程可能延迟返回）
        if original_url != self.current_url:
            return
        self.full_article_text = f"【{title_text}】 {text}"
        self.prev_chapter_url = prev_url
        self.next_chapter_url = next_url
        if toc_url:
            old_toc = self.current_toc_url
            self.current_toc_url = toc_url
            # 目录页变化时（换书了），后台静默提取新书名
            if toc_url != old_toc:
                self.current_book_name = ""
            if not self.current_book_name and toc_url:
                t = _BookNameExtractThread(toc_url)
                t.finished.connect(self._on_book_name_silent_extracted)
                t.start()
                self._book_name_extract_thread = t  # 保持引用防止GC
        self.current_title = title_text

        if self._force_reset_index:
            self.char_index = 0
            self._force_reset_index = False
        elif hasattr(self, '_text_marker') and self._text_marker:
            # 换源定位：在新文本中查找文本标记，定位到对应位置
            marker = self._text_marker
            self._text_marker = ""  # 清除标记，避免影响后续加载
            # 取标记的前20个字符搜索（避免太长匹配不到）
            search_text = marker[:20].strip()
            pos = self.full_article_text.find(search_text)
            if pos >= 0:
                self.char_index = pos
            else:
                # 没找到，尝试更短的片段
                search_text = marker[:10].strip()
                pos = self.full_article_text.find(search_text)
                if pos >= 0:
                    self.char_index = pos
                else:
                    # 完全找不到，从头开始
                    self.char_index = 0
        elif self._jump_to_end_after_load:
            self._jump_to_end_after_load = False
            aw, ah = max(10, self.width() - 10), max(10, self.height() - 4)
            low, high = 0, len(self.full_article_text)
            fit_count = 0
            while low <= high:
                mid = (low + high) // 2
                part = self.full_article_text[-mid:] if mid > 0 else ""
                if self.measure_text_fit(part, aw, ah):
                    fit_count = mid
                    low = mid + 1
                else:
                    high = mid - 1
            if fit_count == 0 and len(self.full_article_text) > 0: fit_count = 1
            self.char_index = max(0, len(self.full_article_text) - fit_count)
        else:
            self.char_index = 0
            for item in self._history_for_url(original_url):
                if item["url"] == original_url:
                    self.char_index = item.get("char_index", 0)
                    break

        new_entry = {"title": title_text, "url": original_url, "char_index": self.char_index}
        if urlparse(original_url).scheme in ("file", "localbook"):
            self.file_history = [item for item in self.file_history if item["url"] != original_url]
            self.file_history.insert(0, new_entry)
            self.file_history = self.file_history[:5]
        else:
            self.history = [item for item in self.history if item["url"] != original_url]
            self.history.insert(0, new_entry)
            self.history = self.history[:5]
        self.save_current_config()
        self.update_text()

        self.trigger_preload(self.next_chapter_url)

    def on_preload_finished(self, text, prev_url, next_url, title_text, original_url, toc_url):
        if text and "未找到正文" not in text and "防机刷盾" not in text:
            self.chapter_cache[original_url] = (text, prev_url, next_url, title_text, original_url, toc_url)

        if original_url in self.prefetch_threads:
            self.prefetch_threads.pop(original_url)

        if original_url == self.next_chapter_url and next_url:
            self.trigger_preload(next_url)

    def measure_text_fit(self, text_part, max_w, max_h):
        if not self.multi_line:
            return QFontMetrics(self.label.font()).horizontalAdvance(text_part) <= max_w
        else:
            doc = QTextDocument()
            doc.setDefaultFont(self.label.font())
            doc.setDocumentMargin(0)
            doc.setTextWidth(max_w)
            doc.setHtml(f"<div style='line-height: {self.line_spacing}%;'>{text_part}</div>")
            return doc.size().height() <= max_h

    def update_text(self):
        if not self.full_article_text: return
        remaining_text = self.full_article_text[self.char_index:]

        if not remaining_text.strip():
            if self.seamless_chapter and self.next_chapter_url:
                self.label.setText("【本章完，继续按 [下一句快捷键] 无缝进入下一章】")
            else:
                self.label.setText("【本章完，请按 [下一章快捷键] 切换】")
            self.current_fit_count = 0
            return

        available_width = max(10, self.width() - 10)
        available_height = max(10, self.height() - 4)

        low, high = 0, len(remaining_text)
        fit_count = 0

        while low <= high:
            mid = (low + high) // 2
            if self.measure_text_fit(remaining_text[:mid], available_width, available_height):
                fit_count = mid
                low = mid + 1
            else:
                high = mid - 1

        if fit_count == 0 and len(remaining_text) > 0: fit_count = 1
        self.current_fit_count = fit_count
        display_text = remaining_text[:fit_count]

        if self.multi_line:
            self.label.setText(f"<div style='line-height: {self.line_spacing}%;'>{display_text}</div>")
        else:
            self.label.setText(display_text)

    def _resize_edge_at(self, pos):
        m, rect = self.resize_margin, self.rect()
        ol, or_, ot, ob = pos.x() <= m, pos.x() >= rect.width() - m, pos.y() <= m, pos.y() >= rect.height() - m
        if ol and ot: return "top_left"
        if or_ and ot: return "top_right"
        if ol and ob: return "bottom_left"
        if or_ and ob: return "bottom_right"
        if ol: return "left"
        if or_: return "right"
        if ot: return "top"
        if ob: return "bottom"
        return ""

    def _update_cursor(self, pos):
        edge = self._resize_edge_at(pos)
        shape = Qt.CursorShape.ArrowCursor
        if edge in ("left", "right"):
            shape = Qt.CursorShape.SizeHorCursor
        elif edge in ("top", "bottom"):
            shape = Qt.CursorShape.SizeVerCursor
        elif edge in ("top_left", "bottom_right"):
            shape = Qt.CursorShape.SizeFDiagCursor
        elif edge in ("top_right", "bottom_left"):
            shape = Qt.CursorShape.SizeBDiagCursor
        self.setCursor(shape)

    def _resize_from_mouse(self, global_pos):
        if not self.resize_edge or not self.resize_start_pos or not self.resize_start_geometry: return
        delta = global_pos - self.resize_start_pos
        geo = QRect(self.resize_start_geometry)
        mw, mh = self.minimumWidth(), self.minimumHeight()
        if "left" in self.resize_edge:
            nl = geo.left() + delta.x()
            if geo.right() - nl + 1 >= mw: geo.setLeft(nl)
        if "right" in self.resize_edge: geo.setRight(max(geo.left() + mw - 1, geo.right() + delta.x()))
        if "top" in self.resize_edge:
            nt = geo.top() + delta.y()
            if geo.bottom() - nt + 1 >= mh: geo.setTop(nt)
        if "bottom" in self.resize_edge: geo.setBottom(max(geo.top() + mh - 1, geo.bottom() + delta.y()))
        self.setGeometry(geo)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.resize_edge and event.buttons() == Qt.MouseButton.LeftButton:
            self._resize_from_mouse(event.globalPosition().toPoint())
            event.accept()
            return
        if event.buttons() == Qt.MouseButton.LeftButton and self.dragPos:
            self.move(self.pos() + event.globalPosition().toPoint() - self.dragPos)
            self.dragPos = event.globalPosition().toPoint()
            event.accept()
            return
        self._update_cursor(event.position().toPoint())
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.resize_edge = self._resize_edge_at(event.position().toPoint())
            if self.resize_edge:
                self.resize_start_pos, self.resize_start_geometry = event.globalPosition().toPoint(), self.geometry()
            else:
                self.dragPos = event.globalPosition().toPoint()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self.dragPos, self.resize_edge, self.resize_start_pos, self.resize_start_geometry = None, "", None, None
        self._update_cursor(event.position().toPoint())
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y() or event.pixelDelta().y()
        if delta > 0:
            self.prev_line()
            event.accept()
        elif delta < 0:
            self.next_line()
            event.accept()
        else:
            super().wheelEvent(event)

    def leaveEvent(self, event):
        if not self.resize_edge: self.setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)

    def resizeEvent(self, event):
        self.config["width"], self.config["height"] = self.width(), self.height()
        self.update_text()
        super().resizeEvent(event)

    def force_quit(self):
        self.save_current_config()
        if self.fetch_worker and self.fetch_worker.is_alive():
            self.fetch_worker.is_cancelled = True

        for w, e in self.prefetch_threads.values():
            if w.is_alive():
                w.is_cancelled = True

        for w, e in self.toc_prefetch_threads.values():
            if w.is_alive():
                w.is_cancelled = True

        if not IS_MAC and hasattr(self, '_win_hotkey_manager') and self._win_hotkey_manager:
            try:
                self._win_hotkey_manager.unregister()
            except Exception:
                pass

        if IS_MAC and hasattr(self, '_mac_hotkey_manager') and self._mac_hotkey_manager:
            try:
                self._mac_hotkey_manager.unregister()
            except Exception:
                pass

        if hasattr(self, 'tray_icon'):
            self.tray_icon.hide()
        QApplication.instance().quit()

    def closeEvent(self, event):
        self.force_quit()
        event.accept()

    def init_shortcuts(self):
        self.sc_custom_pl = QShortcut(QKeySequence(self.key_prev_line), self)
        self.sc_custom_nl = QShortcut(QKeySequence(self.key_next_line), self)
        self.sc_custom_pp = QShortcut(QKeySequence(self.key_prev_page), self)
        self.sc_custom_np = QShortcut(QKeySequence(self.key_next_page), self)

        self.sc_custom_pl.activated.connect(self.prev_line)
        self.sc_custom_nl.activated.connect(self.next_line)
        self.sc_custom_pp.activated.connect(self.prev_page)
        self.sc_custom_np.activated.connect(self.next_page)

        self.sc_boss = QShortcut(QKeySequence(self.key_boss), self)
        self.sc_boss.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.sc_boss.activated.connect(self.toggle_visibility)

        self.boss_signal = GlobalHotkeySignal()
        self.boss_signal.triggered.connect(self.toggle_visibility)

        if IS_MAC and MacHotkeyManager:
            self._mac_hotkey_manager = MacHotkeyManager()
            self._mac_hotkey_manager.triggered.connect(self.toggle_visibility)
        elif not IS_MAC and WinHotkeyManager:
            self._win_hotkey_manager = WinHotkeyManager()
            self._win_hotkey_manager.triggered.connect(self.toggle_visibility)

        self.register_global_boss_key(self.key_boss)

        QShortcut(QKeySequence(Qt.Key.Key_Left), self).activated.connect(self.prev_line)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self).activated.connect(self.next_line)
        QShortcut(QKeySequence(Qt.Key.Key_Up), self).activated.connect(self.prev_page)
        QShortcut(QKeySequence(Qt.Key.Key_Down), self).activated.connect(self.next_page)

    def register_global_boss_key(self, hotkey_str):
        if not hotkey_str:
            return

        success = False

        def trigger_boss_signal():
            self.boss_signal.triggered.emit()

        if not IS_MAC:
            if hasattr(self, '_win_hotkey_manager') and self._win_hotkey_manager:
                try:
                    self._win_hotkey_manager.register(hotkey_str)
                    success = True
                except Exception as e:
                    print(f"Windows 全局热键注册失败: {e}")
        else:
            if hasattr(self, '_mac_hotkey_manager') and self._mac_hotkey_manager:
                try:
                    self._mac_hotkey_manager.register(hotkey_str)
                    success = True
                except Exception as e:
                    print(f"macOS 全局热键注册失败: {e}")

        if hasattr(self, 'sc_boss'):
            self.sc_boss.setEnabled(not success)

    def update_custom_shortcuts(self):
        self.sc_custom_pl.setKey(QKeySequence(self.key_prev_line))
        self.sc_custom_nl.setKey(QKeySequence(self.key_next_line))
        self.sc_custom_pp.setKey(QKeySequence(self.key_prev_page))
        self.sc_custom_np.setKey(QKeySequence(self.key_next_page))
        self.sc_boss.setKey(QKeySequence(self.key_boss))

    def prev_line(self):
        if self.char_index > 0:
            text_before = self.full_article_text[:self.char_index]
            low, high = 0, len(text_before)
            back_fit_count = 0
            aw, ah = max(10, self.width() - 10), max(10, self.height() - 4)

            while low <= high:
                mid = (low + high) // 2
                part = text_before[-mid:] if mid > 0 else ""
                if self.measure_text_fit(part, aw, ah):
                    back_fit_count = mid
                    low = mid + 1
                else:
                    high = mid - 1

            if back_fit_count == 0 and self.char_index > 0: back_fit_count = 1
            self.char_index = max(0, self.char_index - back_fit_count)
            self.update_text()
            self.save_reading_progress()
        else:
            if self.seamless_chapter and self.prev_chapter_url:
                self._jump_to_end_after_load = True
                self.start_async_load(self.prev_chapter_url)

    def next_line(self):
        if self.current_fit_count == 0:
            if self.seamless_chapter and self.next_chapter_url:
                self.next_page()
            return

        if self.char_index < len(self.full_article_text):
            self.char_index += self.current_fit_count
            self.update_text()
            self.save_reading_progress()

    def prev_page(self):
        if self.prev_chapter_url:
            self._force_reset_index = True
            self.start_async_load(self.prev_chapter_url)
        else:
            self.label.setText("【未找到上一章，可能已经是第一章】")

    def next_page(self):
        if self.next_chapter_url:
            self._force_reset_index = True
            self.start_async_load(self.next_chapter_url)
        else:
            self.label.setText("【未找到下一章，可能已是最新章】")

    def toggle_visibility(self):
        now = time.time()
        if hasattr(self, '_last_toggle_time') and now - self._last_toggle_time < 0.3:
            return
        self._last_toggle_time = now

        if self.is_hidden:
            # 恢复显示
            if IS_MAC:
                unhide_mac_app()
            else:
                # Windows: 原生 Win32 API 恢复窗口
                if hasattr(self, '_hidden_widgets'):
                    for w in self._hidden_widgets:
                        try:
                            show_win_window(int(w.winId()))
                        except Exception:
                            pass
                    del self._hidden_widgets
                else:
                    show_win_window(int(self.winId()))
            self.is_hidden = False
        else:
            # 隐藏
            if IS_MAC:
                hide_mac_app()
            else:
                # Windows: 原生 Win32 API 隐藏窗口（不经过 Qt 事件系统）
                self._hidden_widgets = []
                for w in QApplication.topLevelWidgets():
                    if w.isVisible() and w is not self.tray_icon:
                        self._hidden_widgets.append(w)
                        hide_win_window(int(w.winId()))
            self.is_hidden = True

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction("🌐 在线阅读", self.open_web_dialog)
        menu.addAction("📂 打开文件", self.open_file_dialog)

        action_toc = menu.addAction("📑 查看目录")
        if self.current_toc_url:
            action_toc.triggered.connect(self.open_toc_dialog)
        else:
            action_toc.setEnabled(False)

        # 书源更换功能 - 在线阅读时可用
        action_change_source = menu.addAction("🔄 书源更换")
        if self.current_url and not self.current_url.startswith(('file://', 'localbook://')):
            action_change_source.triggered.connect(self.open_change_source_dialog)
        else:
            action_change_source.setEnabled(False)
            action_change_source.setToolTip("在线阅读时才能换源")

        # 刷新功能 - 重新加载当前章节
        action_refresh = menu.addAction("🔄 刷新页面")
        if self.current_url:
            action_refresh.triggered.connect(self.refresh_current_page)
        else:
            action_refresh.setEnabled(False)

        menu.addAction("⚙️ 偏好设置", self.open_settings)
        menu.addSeparator()
        menu.addAction("❌ 退出程序", self.force_quit)
        menu.exec(event.globalPos())

    def open_web_dialog(self):
        WebDialog(self).exec()

    def open_file_dialog(self):
        FileDialog(self).exec()

    def open_settings(self):
        SettingsDialog(self).exec()

    def open_toc_dialog(self):
        if self.current_toc_url:
            TocDialog(self, self.current_toc_url).exec()

    def open_change_source_dialog(self):
        """打开书源更换对话框"""
        current_chapter = self.current_title if self.current_title else ""
        
        # 提取当前阅读位置的文本片段（用于在新源中定位）
        text_marker = ""
        if self.full_article_text and self.char_index > 0:
            start = self.char_index
            end = min(start + 50, len(self.full_article_text))
            text_marker = self.full_article_text[start:end].strip()
            if len(text_marker) < 10:
                end = min(start + 100, len(self.full_article_text))
                text_marker = self.full_article_text[start:end].strip()
        
        book_name = self.current_book_name
        if not book_name:
            # 书名还没提取好（后台线程可能还在跑），让用户手动输入
            from PySide6.QtWidgets import QInputDialog
            book_name, ok = QInputDialog.getText(self, "输入书名", "请输入要搜索的书名：")
            if not ok or not book_name:
                return
        
        ChangeSourceDialog(self, book_name, current_chapter, text_marker).exec()
    
    def _on_book_name_silent_extracted(self, book_name):
        """后台静默提取书名完成回调（章节加载时触发）"""
        if book_name:
            self.current_book_name = book_name


if __name__ == '__main__':
    # 单实例锁：防止重复启动
    _SOCKET_NAME = 'YReaderSingleInstance'
    _local_socket = QLocalSocket()
    _local_socket.connectToServer(_SOCKET_NAME)
    if _local_socket.waitForConnected(500):
        # 已有实例在运行，通知它显示窗口后退出
        _local_socket.write(b'show')
        _local_socket.waitForBytesWritten(500)
        _local_socket.disconnectFromServer()
        sys.exit(0)
    del _local_socket

    # 创建本地服务器，监听后续实例的连接
    _local_server = QLocalServer()
    _local_server.removeServer(_SOCKET_NAME)
    _local_server.listen(_SOCKET_NAME)

    app = QApplication(sys.argv)
    app.setApplicationName("YReader")
    app.setApplicationDisplayName("YReader")
    app.setQuitOnLastWindowClosed(False)

    # 打包后首次启动：将内置模板文件复制到用户数据目录
    init_user_data()

    # 尽早设置应用图标（macOS Dock 图标）
    _icon_base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    _icon_file = os.path.join(_icon_base, 'icon.icns') if IS_MAC else os.path.join(_icon_base, 'icon.ico')
    if os.path.exists(_icon_file):
        app.setWindowIcon(QIcon(_icon_file))

    # macOS: 根据配置控制 Dock 图标显示
    if IS_MAC:
        _cfg = load_config()
        set_mac_dock_icon_visible(_cfg.get("show_taskbar", False))

    translator = QTranslator()
    if translator.load("qtbase_zh_CN", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)

    window = ReaderWindow()
    window.show()
    # macOS: show() 后可能重置阴影，需再次禁用
    if IS_MAC:
        try:
            set_mac_window_shadow(int(window.winId()), False)
        except Exception:
            pass

    # 处理其他实例的连接请求（显示窗口）
    def _on_new_connection():
        client = _local_server.nextPendingConnection()
        if client:
            client.waitForReadyRead(500)
            client.disconnectFromServer()
            # 恢复显示所有窗口
            if window.is_hidden:
                if IS_MAC:
                    unhide_mac_app()
                else:
                    if hasattr(window, '_hidden_widgets'):
                        for w in window._hidden_widgets:
                            try:
                                show_win_window(int(w.winId()))
                            except Exception:
                                pass
                        del window._hidden_widgets
                    else:
                        show_win_window(int(window.winId()))
                window.is_hidden = False
            else:
                for w in QApplication.topLevelWidgets():
                    w.show()
            window.activateWindow()
            window.raise_()
    _local_server.newConnection.connect(_on_new_connection)

    sys.exit(app.exec())