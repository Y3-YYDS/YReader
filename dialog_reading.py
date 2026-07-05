import os
import re
import json
import webbrowser
from urllib.parse import urlparse
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QFormLayout, QComboBox, QPushButton, QHBoxLayout, QFileDialog,
                               QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
                               QLineEdit, QScrollArea, QWidget, QGridLayout, QSizePolicy)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont

from utils import (apply_dialog_style, TocFetchEmitter, TocFetchWorker,
                   PingEmitter, PingWorker, SUPPORTED_SITES_DATA, local_path_from_url,
                   load_sites_config, save_sites_config,
                   load_legado_sources, save_legado_sources)
from search import SearchEmitter, SearchWorker
from legado_adapter import LegadoEngine, register_legado_url


# ================= 单个书源编辑对话框 =================
class SiteEditDialog(QDialog):
    def __init__(self, parent=None, site_data=None):
        super().__init__(parent)
        self.setWindowTitle("编辑书源" if site_data else "添加书源")
        # 增大对话框宽度，给输入框更多空间
        self.setMinimumWidth(650)
        self.site_data = site_data or {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        apply_dialog_style(self, layout)

        form = QFormLayout()
        form.setSpacing(14)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.edit_name = QLineEdit(self.site_data.get("name", ""))
        self.edit_name.setMinimumWidth(400)
        self.edit_name.setPlaceholderText("例如：得奇小说网")
        form.addRow("名称:", self.edit_name)

        self.edit_base = QLineEdit(self.site_data.get("base_url", ""))
        self.edit_base.setMinimumWidth(400)
        self.edit_base.setPlaceholderText("例如：https://www.deqixs.cc/")
        form.addRow("首页地址:", self.edit_base)

        self.edit_search = QLineEdit(self.site_data.get("search_url", ""))
        self.edit_search.setMinimumWidth(400)
        self.edit_search.setPlaceholderText("例如：https://www.deqixs.cc/search?keyword={key}")
        form.addRow("搜索地址:", self.edit_search)

        self.combo_type = QComboBox()
        # 使用中文显示类型选项
        self.combo_type.addItem("自动 (auto)", "auto")
        self.combo_type.addItem("手动 (manual)", "manual")
        # 根据当前值设置选中项
        current_type = self.site_data.get("type", "auto")
        index = self.combo_type.findData(current_type)
        if index >= 0:
            self.combo_type.setCurrentIndex(index)
        self.combo_type.setToolTip("自动 = 程序后台自动抓取搜索结果（推荐）\n手动 = 打开系统浏览器手动搜索")
        form.addRow("抓取类型:", self.combo_type)

        layout.addLayout(form)
        layout.addSpacing(10)

        hint = QLabel("<span style='color:#909399; font-size:12px;'>"
                      "💡 <b>自动 (auto)</b>: 程序后台自动抓取搜索结果（推荐）<br>"
                      "💡 <b>手动 (manual)</b>: 搜索时打开系统浏览器，手动找书后复制链接回来</span>")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("✅ 确定")
        btn_ok.setObjectName("primaryButton")
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("secondaryButton")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

    def get_data(self):
        return {
            "name": self.edit_name.text().strip(),
            "base_url": self.edit_base.text().strip(),
            "search_url": self.edit_search.text().strip(),
            # 获取 combo box 的 data 值（auto 或 manual）
            "type": self.combo_type.currentData(),
        }


# ================= 可视化书源管理对话框 =================
class SiteManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📚 管理书源")
        self.setMinimumSize(800, 560)
        self.sites_data = load_sites_config()
        self.legado_data = load_legado_sources()
        self.init_ui()
        self.refresh_table()

    def init_ui(self):
        layout = QVBoxLayout(self)
        apply_dialog_style(self, layout)

        # 顶部说明
        desc = QLabel("<b>📚 书源管理</b> — 在此直观地添加、编辑、删除或导入书源。"
                      "支持普通书源和 <span style='color:#7C3AED'>阅读APP</span> 书源。"
                      "修改后点击保存即可生效。")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["名称", "首页地址", "搜索地址", "类型"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(36)
        layout.addWidget(self.table, stretch=1)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        btn_add = QPushButton("➕ 添加书源")
        btn_add.setObjectName("secondaryButton")
        btn_add.clicked.connect(self.add_site)

        btn_edit = QPushButton("✏️ 编辑选中")
        btn_edit.setObjectName("secondaryButton")
        btn_edit.clicked.connect(self.edit_site)

        btn_del = QPushButton("🗑️ 删除选中")
        btn_del.setObjectName("secondaryButton")
        btn_del.clicked.connect(self.delete_site)

        btn_import = QPushButton("📥 导入 JSON 文件")
        btn_import.setObjectName("secondaryButton")
        btn_import.clicked.connect(self.import_json)

        btn_export = QPushButton("📤 导出全部")
        btn_export.setObjectName("secondaryButton")
        btn_export.clicked.connect(self.export_json)

        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_edit)
        btn_row.addWidget(btn_del)
        btn_row.addWidget(btn_import)
        btn_row.addWidget(btn_export)
        btn_row.addStretch()

        btn_save = QPushButton("💾 保存并应用")
        btn_save.setObjectName("primaryButton")
        btn_save.clicked.connect(self.save_data)
        btn_row.addWidget(btn_save)

        layout.addLayout(btn_row)

    def refresh_table(self):
        self.table.setRowCount(0)
        # 普通书源
        for site in self.sites_data:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(site.get("name", "")))
            self.table.setItem(row, 1, QTableWidgetItem(site.get("base_url", "")))
            self.table.setItem(row, 2, QTableWidgetItem(site.get("search_url", "")))
            type_text = site.get("type", "auto")
            # 将类型转换为中文显示
            if type_text == "manual":
                type_display = "手动"
            elif type_text == "auto":
                type_display = "自动"
            else:
                type_display = type_text
            type_item = QTableWidgetItem(type_display)
            if type_text == "manual":
                type_item.setForeground(QColor("#D97706"))  # 橙色
            else:
                type_item.setForeground(QColor("#059669"))  # 绿色
            self.table.setItem(row, 3, type_item)

        # Legado 书源
        for ls in self.legado_data:
            row = self.table.rowCount()
            self.table.insertRow(row)
            # Legado 书源标注为测试功能
            name_item = QTableWidgetItem("📖 " + ls.get("name", "") + " (测试)")
            name_item.setFont(QFont("PingFang SC", -1, QFont.Weight.Bold))
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(ls.get("base_url", "")))
            self.table.setItem(row, 2, QTableWidgetItem("legado_sources.json"))
            type_item = QTableWidgetItem(" 阅读APP书源(测试)")
            type_item.setForeground(QColor("#7C3AED"))
            type_item.setFont(QFont("PingFang SC", -1, QFont.Weight.Bold))
            self.table.setItem(row, 3, type_item)

    def add_site(self):
        dlg = SiteEditDialog(self)
        if dlg.exec():
            data = dlg.get_data()
            if data["name"] and data["base_url"]:
                self.sites_data.append(data)
                self.refresh_table()

    def edit_site(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "提示", "请先在表格中选中一行要编辑的书源。")
            return
        idx = rows[0].row()
        dlg = SiteEditDialog(self, self.sites_data[idx])
        if dlg.exec():
            data = dlg.get_data()
            if data["name"] and data["base_url"]:
                self.sites_data[idx] = data
                self.refresh_table()

    def delete_site(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "提示", "请先在表格中选中一行要删除的书源。")
            return
        idx = rows[0].row()
        name = self.sites_data[idx].get("name", "")
        if QMessageBox.question(self, "确认删除", f"确定要删除书源【{name}】吗？") == QMessageBox.StandardButton.Yes:
            self.sites_data.pop(idx)
            self.refresh_table()

    def import_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入书源 JSON 文件", "", "JSON 文件 (*.json);;所有文件 (*)")
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                imported = json.load(f)

            # 检测是否为 Legado 书源格式
            if self._is_legado_source(imported):
                self._import_legado_source(path, imported)
                return

            # 普通书源导入
            if isinstance(imported, dict):
                imported = [imported]
            if not isinstance(imported, list):
                raise ValueError("JSON 内容必须是列表 [...] 或单个书源对象 {...}")
            valid = []
            for item in imported:
                if isinstance(item, dict) and "name" in item and "base_url" in item:
                    valid.append({
                        "name": item.get("name", ""),
                        "base_url": item.get("base_url", ""),
                        "search_url": item.get("search_url", ""),
                        "type": item.get("type", "auto") if item.get("type") in ("auto", "manual") else "auto",
                    })
            if not valid:
                QMessageBox.warning(self, "导入失败", "未在 JSON 文件中找到有效的书源数据。\n\n"
                                    "普通书源需要 \"name\" + \"base_url\"；\n"
                                    "Legado 书源需要 \"bookSourceName\" + \"bookSourceUrl\"。")
                return
            existing_names = {s["name"] for s in self.sites_data}
            new_sites = [s for s in valid if s["name"] not in existing_names]
            if not new_sites:
                QMessageBox.information(self, "导入结果", "所有书源已存在，无需重复导入。")
                return
            self.sites_data.extend(new_sites)
            self.refresh_table()
            names = "、".join(s["name"] for s in new_sites)
            QMessageBox.information(self, "导入成功", f"成功导入 {len(new_sites)} 个新书源：\n{names}\n\n"
                                    f"点击「保存并应用」后生效。")
        except json.JSONDecodeError as e:
            QMessageBox.warning(self, "格式错误", f"无法解析 JSON 文件：\n{e}")
        except Exception as e:
            QMessageBox.warning(self, "导入失败", f"读取文件时出错：\n{e}")

    def _is_legado_source(self, data):
        """检测 JSON 数据是否为 Legado (阅读) 书源格式"""
        if isinstance(data, list):
            if not data:
                return False
            return self._is_legado_source(data[0])
        if isinstance(data, dict):
            return 'bookSourceName' in data and 'bookSourceUrl' in data
        return False

    def _import_legado_source(self, file_path, data):
        """导入 Legado 书源"""
        sources = data if isinstance(data, list) else [data]
        imported_count = 0
        for src in sources:
            src_name = src.get('bookSourceName', '').replace('🌙 ', '').strip()
            src_url = src.get('bookSourceUrl', '').rstrip('/')
            if not src_name or not src_url:
                continue

            # 去重
            existing = {ls.get('name', '') for ls in self.legado_data}
            if src_name in existing:
                continue

            entry = {
                'name': src_name,
                'base_url': src_url,
                'search_url': '',
                'type': 'legado',
                'source_data': [src],
            }
            self.legado_data.append(entry)
            imported_count += 1

        if imported_count == 0:
            QMessageBox.information(self, "导入结果", "所有 阅读APP书源 已存在，无需重复导入。")
            return

        self.refresh_table()
        names = "、".join(ls['name'] for ls in self.legado_data[-imported_count:])
        QMessageBox.information(
            self, "导入成功",
            f"成功导入 {imported_count} 个 阅读APP书源：\n{names}\n\n"
            f"📖 阅读APP书源功能强大，支持：\n"
            f"• 智能搜索小说\n"
            f"• 自动提取目录和章节\n"
            f"• 分类浏览（玄幻/都市/仙侠等）\n"
            f"• 排行榜查看\n\n"
            f"点击「保存并应用」后生效。"
        )

    def export_json(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出书源 JSON 文件", "sites_export.json", "JSON 文件 (*.json)")
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.sites_data, f, ensure_ascii=False, indent=4)
            QMessageBox.information(self, "导出成功", f"已将 {len(self.sites_data)} 个书源导出到：\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", f"写入文件时出错：\n{e}")

    def save_data(self):
        save_sites_config(self.sites_data)
        save_legado_sources(self.legado_data)
        QMessageBox.information(self, "成功", "书源保存成功！关闭当前搜索大厅重新打开即可生效。")
        self.accept()


# ======================================================

class TocDialog(QDialog):
    def __init__(self, parent, toc_url, dialog_chain=None):
        super().__init__(parent)
        self.setWindowTitle("本书目录")
        self.setMinimumSize(450, 600)
        self.parent, self.toc_url, self.fetch_worker, self.owns_fetch_worker = parent, toc_url, None, False
        self.dialog_chain = dialog_chain or []
        self.emitter = TocFetchEmitter()
        self.emitter.result_ready.connect(self.on_fetch_result)
        self.init_ui()
        if cached_chapters := self.parent.get_cached_toc(self.toc_url):
            self.on_fetch_result(cached_chapters, "")
        else:
            self.start_fetch()

    def init_ui(self):
        layout = QVBoxLayout(self)
        apply_dialog_style(self, layout)
        self.lbl_status = QLabel("正在为您全力嗅探智能目录，请稍候...")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setStyleSheet("padding: 30px; font-size: 15px; color: #6B7280;")
        layout.addWidget(self.lbl_status)
        self.list_widget = QListWidget()
        self.list_widget.hide()
        self.list_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        layout.addWidget(self.list_widget)

    def start_fetch(self):
        if active := self.parent.toc_prefetch_threads.get(self.toc_url):
            if active[0].is_alive():
                self.fetch_worker = active[0]
                active[1].result_ready.connect(self.on_fetch_result)
                return
        self.owns_fetch_worker = True
        self.fetch_worker = TocFetchWorker(self.toc_url, self.emitter)
        self.fetch_worker.start()

    def on_fetch_result(self, chapters, error_msg):
        if not error_msg: self.parent.set_cached_toc(self.toc_url, chapters)
        if error_msg:
            self.lbl_status.setText(f"❌ 目录获取失败: {error_msg}\n可能该网址不支持抓取，请尝试从浏览器中查找。")
            return
        if not chapters:
            self.lbl_status.setText("⚠️ 未能在该页面智能识别到有效的目录章节列表。")
            return

        self.lbl_status.hide()
        self.list_widget.show()
        for title, url in chapters:
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, url)
            self.list_widget.addItem(item)
            if url == self.parent.current_url:
                self.list_widget.setCurrentItem(item)
                self.list_widget.scrollToItem(item, QListWidget.ScrollHint.PositionAtCenter)

    def on_item_double_clicked(self, item):
        self.parent._force_reset_index = True
        self.parent.start_async_load(item.data(Qt.ItemDataRole.UserRole))
        # 关闭所有辅助窗口，让用户直接看到阅读界面
        for dlg in self.dialog_chain:
            try:
                dlg.accept()
            except Exception:
                pass
        self.accept()

    def closeEvent(self, event):
        if self.owns_fetch_worker and self.fetch_worker is not None and self.fetch_worker.is_alive():
            self.fetch_worker.is_cancelled = True
        event.accept()


# ===================== 书籍详情页对话框 =====================
class BookDetailDialog(QDialog):
    """显示小说详情（封面、作者、简介等），并提供查看目录入口"""

    def __init__(self, parent, book_url, site_name="", legado_source=None, caller_dialog=None, caller_chain=None):
        super().__init__(parent)
        self.setWindowTitle("书籍详情")
        self.setMinimumSize(480, 620)
        self.book_url = book_url
        self.site_name = site_name
        self.legado_source = legado_source
        self.caller_dialog = caller_dialog
        self.caller_chain = caller_chain or []  # 额外的调用者链（如 WebDialog）
        self.legado_engine = None
        if self.legado_source:
            from legado_adapter import LegadoEngine
            self.legado_engine = LegadoEngine(self.legado_source)

        self.init_ui()
        self.load_detail_async()

    def init_ui(self):
        layout = QVBoxLayout(self)
        apply_dialog_style(self, layout)

        self.lbl_status = QLabel("正在加载书籍详情...")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setStyleSheet("padding: 20px; color: #6B7280; font-size: 14px;")
        layout.addWidget(self.lbl_status)

        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setSpacing(14)
        self.content_widget.hide()
        layout.addWidget(self.content_widget, stretch=1)

        # 封面 + 信息区域（横向布局）
        info_row = QHBoxLayout()
        info_row.setSpacing(16)
        
        # 封面图片
        self.cover_label = QLabel()
        self.cover_label.setFixedSize(120, 160)
        self.cover_label.setStyleSheet("background-color: #F3F4F6; border-radius: 4px;")
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setText("无封面")
        info_row.addWidget(self.cover_label, 0)
        
        # 右侧信息
        right_layout = QVBoxLayout()
        right_layout.setSpacing(10)
        
        # 标题
        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #111827;")
        self.title_label.setWordWrap(True)
        right_layout.addWidget(self.title_label)

        # 作者、分类等元信息
        self.meta_label = QLabel()
        self.meta_label.setStyleSheet("color: #6B7280; font-size: 13px;")
        self.meta_label.setWordWrap(True)
        right_layout.addWidget(self.meta_label)
        
        right_layout.addStretch()
        info_row.addLayout(right_layout, 1)
        
        self.content_layout.addLayout(info_row)
        
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #E5E7EB; margin: 8px 0;")
        self.content_layout.addWidget(line)

        # 简介
        intro_title = QLabel("简介：")
        intro_title.setStyleSheet("font-weight: bold; color: #374151; font-size: 14px;")
        self.content_layout.addWidget(intro_title)
        
        self.intro_label = QLabel()
        self.intro_label.setStyleSheet("color: #374151; font-size: 13px; line-height: 1.6;")
        self.intro_label.setWordWrap(True)
        self.content_layout.addWidget(self.intro_label)

        self.content_layout.addStretch()

        # 按钮行
        btn_layout = QHBoxLayout()
        self.btn_toc = QPushButton("📑 查看目录 / 开始阅读")
        self.btn_toc.setObjectName("primaryButton")
        self.btn_toc.setEnabled(False)
        self.btn_toc.clicked.connect(self.open_toc)

        self.btn_browser = QPushButton("🌐 在浏览器中打开")
        self.btn_browser.setObjectName("secondaryButton")
        self.btn_browser.clicked.connect(self.open_in_browser)

        btn_layout.addWidget(self.btn_browser)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_toc)
        self.content_layout.addLayout(btn_layout)

    def load_detail_async(self):
        class DetailThread(QThread):
            detail_ready = Signal(dict)
            error = Signal(str)

            def __init__(self, engine, url, site_name, dialog_ref=None):
                super().__init__()
                self.engine = engine
                self.url = url
                self.site_name = site_name
                self.dialog_ref = dialog_ref
                self._stopped = False

            def stop(self):
                self._stopped = True

            def run(self):
                try:
                    if self.engine:
                        info = self.engine.get_book_info(self.url)
                        info = info or {}
                    else:
                        info = self._fetch_regular_info()
                    # 确保基础字段存在
                    info.setdefault('name', '')
                    info.setdefault('author', '')
                    info.setdefault('coverUrl', '')
                    info.setdefault('intro', '')
                    info.setdefault('kind', '')
                    info.setdefault('lastChapter', '')
                    info.setdefault('wordCount', '')
                    info.setdefault('updateTime', '')
                    info['site_name'] = self.site_name
                    info['book_url'] = self.url
                    
                    # 检查对话框是否仍然存活（防止关闭窗口后闪退）
                    if self._stopped or (self.dialog_ref and not self.dialog_ref.isVisible()):
                        return
                    self.detail_ready.emit(info)
                except Exception as e:
                    if self._stopped or (self.dialog_ref and not self.dialog_ref.isVisible()):
                        return
                    self.error.emit(str(e))

            def _fetch_regular_info(self):
                """普通书源：通过 og: meta 标签和常见模式提取书籍信息"""
                import cloudscraper
                from bs4 import BeautifulSoup
                from urllib.parse import urljoin
                scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
                resp = scraper.get(self.url, timeout=12)
                resp.encoding = resp.apparent_encoding
                soup = BeautifulSoup(resp.text, 'html.parser')
                info = {}

                # og: meta 标签提取（优先）
                og_map = {
                    'name': 'og:novel:book_name',
                    'author': 'og:novel:author',
                    'coverUrl': 'og:image',
                    'intro': 'og:description',
                    'lastChapter': 'og:novel:latest_chapter_name',
                    'kind': 'og:novel:category',
                }
                for key, prop in og_map.items():
                    tag = soup.find('meta', property=prop)
                    if tag and tag.get('content', '').strip():
                        info[key] = tag['content'].strip()

                # 也尝试从 name= 格式的 meta 标签提取（部分站点用 name 而非 property）
                if not info.get('author'):
                    for meta in soup.find_all('meta', attrs={'name': 'author'}):
                        c = meta.get('content', '').strip()
                        if c:
                            info['author'] = c
                            break

                # 回退：从 title 标签取书名
                if not info.get('name'):
                    title_tag = soup.find('title')
                    if title_tag:
                        raw = title_tag.get_text(strip=True)
                        for sep in ['_', '|', '—', '-', '–']:
                            parts = [p.strip() for p in raw.split(sep) if p.strip()]
                            if parts:
                                info['name'] = parts[0]
                                break
                        if not info.get('name'):
                            info['name'] = raw

                # 回退：从 h1/h2 或 .title 类取书名
                if not info.get('name'):
                    for sel in ['.title', 'h1', 'h2']:
                        elem = soup.select_one(sel) if sel.startswith('.') else soup.find(sel)
                        if elem and elem.get_text(strip=True):
                            info['name'] = elem.get_text(strip=True)
                            break

                # 回退：从页面中找作者
                if not info.get('author'):
                    # 尝试多种常见选择器
                    for sel in ['.zuthor', '.info .zuthor', '.author', '.bookinfo .author', '[class*="author"]']:
                        elem = soup.select_one(sel)
                        if elem:
                            text = elem.get_text(strip=True)
                            # 清理"作者："前缀
                            text = re.sub(r'^作者[：:\s]*', '', text).strip()
                            # 截取到第一个分隔关键字
                            for sep in ['状态', '更新', '最新', '字数', '分类']:
                                idx = text.find(sep)
                                if idx > 0:
                                    text = text[:idx]
                            # 去掉尾部标点
                            text = text.strip(' ,，.。;；\t\n')
                            if text and len(text) < 20:
                                info['author'] = text
                                break
                # 再清理一次：确保作者名干净
                if info.get('author'):
                    # 如果作者名包含非人名内容（如状态、更新时间），截断
                    for sep in ['状态', '更新', '最新', '字数', '分类', '连载', '完结']:
                        idx = info['author'].find(sep)
                        if idx > 0:
                            info['author'] = info['author'][:idx].strip(' ,，.。')
                    if len(info['author']) > 20:
                        info['author'] = ''

                # 回退：从页面中找简介段落（.des 或 .jj + 后续内容）
                if not info.get('intro'):
                    des_div = soup.find(class_='des')
                    if des_div:
                        # 去掉“内容简介：”标题
                        jj = des_div.find(class_='jj')
                        if jj:
                            jj.decompose()
                        text = des_div.get_text(strip=True)
                        if text and len(text) > 10:
                            info['intro'] = text[:500] + '...' if len(text) > 500 else text

                # 回退：从 .info 区域找更新时间
                if not info.get('updateTime'):
                    uptime_div = soup.find(class_='uptime')
                    if uptime_div:
                        time_elem = uptime_div.find('time')
                        if time_elem:
                            info['updateTime'] = time_elem.get_text(strip=True)
                        else:
                            text = uptime_div.get_text(strip=True)
                            text = re.sub(r'^更新时间[：:\s]*', '', text).strip()
                            if text:
                                info['updateTime'] = text

                # 验证 og:image URL 有效性（某些站点会双重拼接导致 URL 无效）
                if info.get('coverUrl'):
                    url_val = info['coverUrl']
                    if url_val.count('https://') > 1 or url_val.count('http://') > 1:
                        info['coverUrl'] = ''  # URL 无效，清空让回退逻辑生效

                # 封面图片相对路径处理
                if info.get('coverUrl') and not info['coverUrl'].startswith('http'):
                    info['coverUrl'] = urljoin(self.url, info['coverUrl'])

                # 回退：从 .cover img 或页面中找封面图
                if not info.get('coverUrl'):
                    cover_img = soup.select_one('.cover img') or soup.select_one('.bookimg img') or soup.select_one('.img img')
                    if cover_img:
                        src = cover_img.get('src', '') or cover_img.get('data-src', '') or cover_img.get('data-original', '')
                        if src:
                            info['coverUrl'] = urljoin(self.url, src)

                # 清理过长字段
                if info.get('author') and len(info['author']) > 30:
                    info['author'] = ''
                if info.get('intro') and len(info['intro']) > 1000:
                    info['intro'] = info['intro'][:500] + '...'

                return info

        self.detail_thread = DetailThread(self.legado_engine, self.book_url, self.site_name, dialog_ref=self)
        self.detail_thread.detail_ready.connect(self._on_detail_ready)
        self.detail_thread.error.connect(self._on_detail_error)
        self.detail_thread.start()

    def closeEvent(self, event):
        # 安全停止加载线程，防止闪退
        try:
            if hasattr(self, 'detail_thread') and self.detail_thread.isRunning():
                self.detail_thread.stop()
                # 断开信号连接，防止线程回调已销毁的控件
                try:
                    self.detail_thread.detail_ready.disconnect()
                    self.detail_thread.error.disconnect()
                except Exception:
                    pass
                self.detail_thread.wait(3000)
            if hasattr(self, 'cover_thread') and self.cover_thread.isRunning():
                try:
                    self.cover_thread.image_ready.disconnect()
                except Exception:
                    pass
                self.cover_thread.wait(2000)
        except Exception:
            pass
        event.accept()

    def _on_detail_ready(self, info):
        if not self.isVisible():
            return
        self.book_info = info
        self.lbl_status.hide()
        self.content_widget.show()
        self.btn_toc.setEnabled(True)

        # 标题：只显示书名
        self.title_label.setText(info.get('name') or '未知书名')
        
        # 元信息：作者 + 更新时间（如果有的话）
        meta_parts = []
        if info.get('author'):
            meta_parts.append(f"作者：{info.get('author')}")
        if info.get('updateTime'):
            meta_parts.append(f"更新：{info.get('updateTime')}")
        self.meta_label.setText("  |  ".join(meta_parts) if meta_parts else "暂无元信息")

        # 简介
        intro = info.get('intro', '')
        if not intro:
            intro = "暂无简介"
        self.intro_label.setText(intro)

        # 加载封面图片
        cover_url = info.get('coverUrl', '')
        if cover_url:
            self._load_cover_image(cover_url)
        else:
            self.cover_label.clear()
            self.cover_label.setText("无封面")

        self.setWindowTitle(f"{info.get('name') or '书籍详情'} - 详情")
        
        # 预加载目录（后台异步加载，用户点击"查看目录"时直接显示）
        self._preload_toc()
    
    def _load_cover_image(self, url):
        """异步加载封面图片"""
        class CoverThread(QThread):
            image_ready = Signal(object)
            
            def __init__(self, url, referer=""):
                super().__init__()
                self.url = url
                self.referer = referer
            
            def run(self):
                try:
                    import cloudscraper
                    s = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
                    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                    if self.referer:
                        headers['Referer'] = self.referer
                    resp = s.get(self.url, headers=headers, timeout=10)
                    if resp.status_code == 200 and len(resp.content) > 100:
                        from PySide6.QtGui import QPixmap
                        pixmap = QPixmap()
                        pixmap.loadFromData(resp.content)
                        if not pixmap.isNull():
                            self.image_ready.emit(pixmap)
                except Exception:
                    pass
        
        referer = self.book_url if self.book_url else ""
        self.cover_thread = CoverThread(url, referer=referer)
        self.cover_thread.image_ready.connect(self._on_cover_loaded)
        self.cover_thread.start()
    
    def _on_cover_loaded(self, pixmap):
        """封面图片加载完成"""
        try:
            if not self.isVisible():
                return
            scaled = pixmap.scaled(
                self.cover_label.width(), 
                self.cover_label.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.cover_label.setPixmap(scaled)
        except Exception:
            pass

    def _on_detail_error(self, err):
        self.lbl_status.setText(f"加载详情失败: {err}")
        # 允许继续查看目录
        self.btn_toc.setEnabled(True)

    def _preload_toc(self):
        """后台预加载目录，用户点击"查看目录"时直接显示"""
        toc_url = self.book_url
        # 检查是否已缓存或正在加载
        if self.parent().get_cached_toc(toc_url):
            return
        if hasattr(self.parent(), 'toc_prefetch_threads') and toc_url in self.parent().toc_prefetch_threads:
            thread_info = self.parent().toc_prefetch_threads[toc_url]
            if thread_info[0].is_alive():
                return  # 已在加载中
        
        # 启动后台加载
        emitter = TocFetchEmitter()
        emitter.result_ready.connect(self._on_toc_preloaded)
        worker = TocFetchWorker(toc_url, emitter)
        worker.start()
        # 记录线程（用于后续检查）
        if hasattr(self.parent(), 'toc_prefetch_threads'):
            self.parent().toc_prefetch_threads[toc_url] = (worker, emitter)
    
    def _on_toc_preloaded(self, chapters, error_msg):
        """目录预加载完成，缓存结果"""
        if error_msg or not chapters:
            return
        toc_url = self.book_url
        self.parent().set_cached_toc(toc_url, chapters)

    def open_toc(self):
        # 构建对话框链，选择章节后自动关闭这些辅助窗口
        # 链的顺序：[当前对话框, 直接调用者, 更上层的调用者...]
        chain = [self]
        if self.caller_dialog:
            chain.append(self.caller_dialog)
        # 添加更上层的调用者链（如 WebDialog）
        chain.extend([d for d in self.caller_chain if d is not None])
        TocDialog(self.parent(), self.book_url, dialog_chain=chain).exec()

    def open_in_browser(self):
        import webbrowser
        webbrowser.open(self.book_url)


class WebDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("网页在线阅读与全网搜书")
        # 设置初始大小，但允许用户手动调整
        self.resize(850, 620)
        self.setMinimumSize(400, 300)  # 最小尺寸限制
        self.setMaximumSize(1920, 1080)  # 最大尺寸限制（防止过大）
        self.parent = parent
        self.site_status, self.ping_threads, self.ping_completed_count = {}, [], 0

        self.ping_emitter = PingEmitter()
        self.ping_emitter.result_ready.connect(self.on_ping_result)
        self.ping_emitter.finished.connect(self.on_ping_finished)

        self.search_worker = None
        self.search_emitter = SearchEmitter()
        self.search_emitter.result_ready.connect(self.on_search_result)
        self.search_emitter.finished.connect(self.on_search_finished)

        self._temp_results = []
        # 加载普通书源和 Legado 书源
        self.current_sites = load_sites_config()
        self.legado_sources = load_legado_sources()

        self.history_mapping = {f"{i['title']} - {i['url']}": i['url'] for i in self.parent.history if
                                urlparse(i.get('url', '')).scheme not in ("file", "localbook")}
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        apply_dialog_style(self, main_layout)

        # 测速区
        self.sites_label = QLabel()
        self.sites_label.setOpenExternalLinks(True)
        self.sites_label.setWordWrap(True)
        self.update_sites_label()
        main_layout.addWidget(self.sites_label)

        self.btn_ping = QPushButton("⚡ 测试网站延迟")
        self.btn_ping.setObjectName("secondaryButton")
        self.btn_ping.clicked.connect(self.start_ping)

        # Legado 分类浏览按钮
        self.btn_explore = QPushButton("📚 浏览分类")
        self.btn_explore.setObjectName("secondaryButton")
        self.btn_explore.setToolTip("浏览 Legado 书源的分类、排行榜")
        self.btn_explore.clicked.connect(self.open_explore_dialog)
        if not self.legado_sources:
            self.btn_explore.setEnabled(False)

        ping_row = QHBoxLayout()
        ping_row.addWidget(self.btn_ping)
        ping_row.addWidget(self.btn_explore)
        ping_row.addStretch()
        main_layout.addLayout(ping_row)

        line1 = QFrame()
        line1.setFrameShape(QFrame.Shape.HLine)
        line1.setStyleSheet("background-color: #ebeef5; margin: 10px 0;")
        main_layout.addWidget(line1)

        # 输入与搜索区
        input_layout = QHBoxLayout()
        self.url_combo = QComboBox()
        self.url_combo.setEditable(True)
        for display_text in self.history_mapping.keys(): self.url_combo.addItem(display_text)

        current_url = "" if urlparse(self.parent.current_url).scheme in ("file",
                                                                         "localbook") else self.parent.current_url
        current_display = next((disp for disp, url in self.history_mapping.items() if url == self.parent.current_url),
                               current_url)
        self.url_combo.setCurrentText(current_display)
        self.url_combo.setPlaceholderText("粘贴链接直接阅读，或输入书名全网搜索...")

        self.btn_action = QPushButton("🔍 智能搜索")
        self.btn_action.setObjectName("primaryButton")
        self.btn_action.clicked.connect(self.handle_input_action)

        btn_manage = QPushButton("⚙️ 管理书源")
        btn_manage.clicked.connect(self.open_site_manager)

        input_layout.addWidget(QLabel("<b>🚀 搜索小说 / 粘贴链接阅读:</b>"))
        input_layout.addWidget(self.url_combo, stretch=1)
        input_layout.addWidget(self.btn_action)
        input_layout.addWidget(btn_manage)
        main_layout.addLayout(input_layout)

        # 输入框提示说明
        help_label = QLabel("💡 提示：可直接粘贴小说章节链接后点击“🔍 智能搜索”阅读，也可输入书名在所有书源中搜索；双击搜索结果即可开始阅读")
        help_label.setStyleSheet("color: #909399; font-size: 12px; margin: 2px 0 6px 0;")
        help_label.setWordWrap(True)
        main_layout.addWidget(help_label)

        # 表格区
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["书名 / 链接动作", "作者", "来源站点"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemDoubleClicked.connect(self.on_table_double_clicked)
        main_layout.addWidget(self.table, stretch=1)

        self.lbl_search_status = QLabel("支持普通书源 + Legado(阅读)书源。输入书名搜索，或粘贴链接直接阅读。")
        self.lbl_search_status.setStyleSheet("color: #909399; font-size: 12px;")
        main_layout.addWidget(self.lbl_search_status)
        self.url_combo.setFocus()

    def open_site_manager(self):
        # 打开书源管理器，关闭时刷新界面列表
        if SiteManagerDialog(self).exec():
            self.current_sites = load_sites_config()
            self.legado_sources = load_legado_sources()
            self.update_sites_label()

    def update_sites_label(self):
        # 使用表格布局来显示书源和测速结果
        parts = []
        
        # 普通书源
        for index, s in enumerate(self.current_sites):
            status = self.site_status.get(index, '')
            # 横向布局：书名 + 固定宽度测速位
            if status:
                parts.append(f"<a href='{s['base_url']}' style='color:#409EFF; text-decoration:none;'>🌐 {s['name']}</a><span style='display: inline-block; width: 90px; text-align: left; margin-left: 5px; font-size:11px;'>{status}</span>&nbsp;&nbsp;")
            else:
                parts.append(f"<a href='{s['base_url']}' style='color:#409EFF; text-decoration:none;'>🌐 {s['name']}</a><span style='display: inline-block; width: 90px; margin-left: 5px;'>&nbsp;</span>&nbsp;&nbsp;")
        
        # Legado 书源（阅读APP书源）
        for idx, ls in enumerate(self.legado_sources):
            # 为每个 Legado 书源生成一个唯一的索引（偏移量）
            legado_idx = len(self.current_sites) + idx
            status = self.site_status.get(legado_idx, '')
            if status:
                parts.append(f"<span style='color:#7C3AED; font-weight:bold;'>📖 {ls['name']} (测试)</span><span style='display: inline-block; width: 90px; text-align: left; margin-left: 5px; font-size:11px;'>{status}</span>&nbsp;&nbsp;")
            else:
                parts.append(f"<span style='color:#7C3AED; font-weight:bold;'> {ls['name']} (测试)</span><span style='display: inline-block; width: 90px; margin-left: 5px;'>&nbsp;</span>&nbsp;&nbsp;")

        all_sites_count = len(self.current_sites) + len(self.legado_sources)
        self.sites_label.setText(
            f"<div style='line-height: 2.0;'><b>已加载 {all_sites_count} 个书源:</b><br>" + "".join(parts) + "</div>")

    def start_ping(self):
        self.btn_ping.setEnabled(False)
        self.btn_ping.setText("正在测速中...")
        self.site_status, self.ping_completed_count, self.ping_threads = {}, 0, []
        self.update_sites_label()
        
        # 测试普通书源
        for idx, site in enumerate(self.current_sites):
            t = PingWorker(idx, site['base_url'], self.ping_emitter)
            self.ping_threads.append(t)
            t.start()
        
        # 测试阅读APP书源（Legado）
        for idx, ls in enumerate(self.legado_sources):
            legado_idx = len(self.current_sites) + idx
            base_url = ls.get('base_url', '')
            if base_url:
                t = PingWorker(legado_idx, base_url, self.ping_emitter)
                self.ping_threads.append(t)
                t.start()

    def on_ping_result(self, idx, latency, success):
        self.site_status[
            idx] = f"<span style='color:{'#059669' if latency < 1000 else '#D97706' if latency < 3000 else '#DC2626'}; font-size:12px;'>[{int(latency)}ms]</span>" if success else "<span style='color:#DC2626; font-size:12px;'>[超时]</span>"
        self.update_sites_label()

    def on_ping_finished(self):
        self.ping_completed_count += 1
        total_sites = len(self.current_sites) + len(self.legado_sources)
        if self.ping_completed_count >= total_sites:
            self.btn_ping.setEnabled(True)
            self.btn_ping.setText("⚡ 重新测速")

    def handle_input_action(self):
        text = self.url_combo.currentText().strip()
        if not text: return
        target_url = self.history_mapping.get(text, text)

        if target_url.startswith("http://") or target_url.startswith("https://"):
            # 只有用户明确在框里粘贴“直连”时，才直接进单行阅读器强行拉数据！
            self.parent._force_reset_index = True
            self.parent.start_async_load(target_url)
            self.accept()
        else:
            self.start_search(text)

    def start_search(self, keyword):
        self.btn_action.setEnabled(False)
        self.table.setRowCount(0)
        self._temp_results.clear()
        self.lbl_search_status.setText(f"正在全网聚合检索: 【{keyword}】...")

        if self.search_worker and self.search_worker.is_alive():
            self.search_worker.is_cancelled = True

        self.search_worker = SearchWorker(keyword, self.search_emitter)
        self.search_worker.start()

    def on_search_result(self, site_name, results, err):
        # 调试日志：打印接收到的搜索结果
        print(f"\n📥 [DEBUG] Received {len(results)} results from site: {site_name}")
        for i, res in enumerate(results):
            title = res.get('title', '')
            url = res.get('url', '')
            author = res.get('author', '')
            print(f"   Result {i+1}: title='{title}', url='{url[:50]}...', author='{author}'")
            if not title:
                print(f"   ⚠️ WARNING: Empty title detected!")
        
        self._temp_results.extend(results)
        self.update_table_view()

    def update_table_view(self):
        self.table.setRowCount(0)
        
        # 获取当前搜索关键词
        keyword = self.url_combo.currentText().strip()
        if not keyword:
            keyword = ""
        
        # 计算每个结果的相似度分数（用于排序）
        def calculate_similarity(title, keyword):
            """计算书名与搜索词的相似度，返回分数（越高越相似）"""
            if not keyword or not title:
                return 0
            
            title_lower = title.lower()
            keyword_lower = keyword.lower()
            
            # 完全匹配：最高分
            if title_lower == keyword_lower:
                return 1000
            
            # 包含关系：次高分
            if keyword_lower in title_lower:
                return 500 + len(keyword) * 10
            
            # 标题包含在关键词中：中等分
            if title_lower in keyword_lower:
                return 300 + len(title) * 5
            
            # 部分匹配：根据共同字符数计算
            common_chars = set(title_lower) & set(keyword_lower)
            if common_chars:
                return len(common_chars) * 2
            
            return 0
        
        # 分类结果
        exact_matches = []      # 精确匹配或高度相似
        partial_matches = []    # 部分匹配
        system_browser = []     # SYSTEM_BROWSER 结果
        
        for res in self._temp_results:
            url = res.get('url', '')
            title = res.get('title', '')
            
            if url.startswith("SYSTEM_BROWSER:"):
                system_browser.append(res)
            else:
                score = calculate_similarity(title, keyword)
                if score >= 300:  # 高度相似
                    exact_matches.append((res, score))
                else:  # 部分匹配
                    partial_matches.append((res, score))
        
        # 按相似度排序
        exact_matches.sort(key=lambda x: x[1], reverse=True)
        partial_matches.sort(key=lambda x: x[1], reverse=True)
        
        # 显示精确匹配的结果
        display_count = 0
        max_display = 10  # 最多显示10个精确匹配
        
        for res, score in exact_matches[:max_display]:
            self._add_result_row(res)
            display_count += 1
        
        # 如果有更多精确匹配或部分匹配，添加"查看更多"按钮
        remaining_exact = len(exact_matches) - max_display
        has_partial = len(partial_matches) > 0
        
        if remaining_exact > 0 or has_partial:
            row = self.table.rowCount()
            self.table.insertRow(row)
            
            more_btn = QPushButton(f" 查看更多 ({remaining_exact + len(partial_matches)} 条相关结果)")
            more_btn.setObjectName("secondaryButton")
            # 传递所有精确匹配和部分匹配，以便展开时显示全部
            more_btn.clicked.connect(lambda: self._show_all_results(exact_matches, partial_matches))
            
            self.table.setCellWidget(row, 0, more_btn)
            self.table.setItem(row, 1, QTableWidgetItem(""))
            self.table.setItem(row, 2, QTableWidgetItem(""))
        
        # 最后添加 SYSTEM_BROWSER 结果
        for res in system_browser:
            self._add_result_row(res)
        
        print(f"\n📊 [DEBUG] 显示 {display_count} 个精确匹配，{len(partial_matches)} 个部分匹配，{len(system_browser)} 个系统浏览器结果")

    def _add_result_row(self, res):
        """添加一行搜索结果到表格"""
        row = self.table.rowCount()
        self.table.insertRow(row)

        title_val = res.get('title', '')
        if not title_val:
            title_val = "️ 书名提取失败"
        
        item_title = QTableWidgetItem(title_val)
        item_title.setData(Qt.ItemDataRole.UserRole, res['url'])

        if res['url'].startswith("SYSTEM_BROWSER:"):
            item_title.setForeground(QColor("#409EFF"))  # 蓝色表示系统调用
        else:
            item_title.setForeground(QColor("#333333"))
            font = item_title.font()
            font.setBold(True)
            item_title.setFont(font)

        self.table.setItem(row, 0, item_title)
        self.table.setItem(row, 1, QTableWidgetItem(res.get('author', '')))
        self.table.setItem(row, 2, QTableWidgetItem(res.get('site', '')))

    def _show_all_results(self, all_exact_matches, partial_matches):
        """显示所有剩余结果（点击查看更多按钮时）"""
        # 清空当前表格
        self.table.setRowCount(0)
        
        # 显示所有精确匹配（已按相似度排序）
        for res, score in all_exact_matches:
            self._add_result_row(res)
        
        # 显示所有部分匹配
        for res, score in partial_matches:
            self._add_result_row(res)
        
        # 显示所有 SYSTEM_BROWSER 结果
        for res in self._temp_results:
            if res['url'].startswith("SYSTEM_BROWSER:"):
                self._add_result_row(res)
        
        total = len(all_exact_matches) + len(partial_matches)
        system_count = sum(1 for r in self._temp_results if r['url'].startswith("SYSTEM_BROWSER:"))
        self.lbl_search_status.setText(
            f"已展开全部 {total} 条相关结果 + {system_count} 个手动搜索站点。黑色结果双击拉取目录页，蓝色结果双击跳往系统浏览器。")

    def on_search_finished(self):
        self.btn_action.setEnabled(True)
        count = self.table.rowCount()
        self.lbl_search_status.setText(
            f"检索完成，找到 {count} 条结果。黑色结果双击拉取目录页，蓝色结果双击跳往系统浏览器。")

    def on_table_double_clicked(self, item):
        row = item.row()
        title_item = self.table.item(row, 0)
        target_url = title_item.data(Qt.ItemDataRole.UserRole)

        if target_url.startswith("SYSTEM_BROWSER:"):
            real_url = target_url.replace("SYSTEM_BROWSER:", "")
            webbrowser.open(real_url)
            self.lbl_search_status.setText(
                "已在系统电脑浏览器中为你打开！进网站手动搜出章节链接后，复制到上方即可无缝阅读。")
        else:
            # 点击搜索结果 → 先显示书籍详情页，用户确认后再打开目录/阅读
            legado_source = None
            site_name = self.table.item(row, 2).text() if self.table.item(row, 2) else ""
            for ls in self.legado_sources:
                if ls.get('name') == site_name:
                    legado_source = ls.get('source_data', [{}])[0]
                    # 注册 URL 到 Legado 注册表
                    register_legado_url(target_url, legado_source)
                    break

            BookDetailDialog(self.parent, target_url, site_name=site_name, legado_source=legado_source, caller_dialog=self).exec()

    def open_explore_dialog(self):
        """打开 Legado 分类浏览对话框"""
        if not self.legado_sources:
            QMessageBox.information(self, "提示", "尚未导入任何 Legado 书源。\n\n请在「管理书源」中导入 .json 书源文件。")
            return
        ExploreDialog(self.parent, self.legado_sources, caller_dialog=self).exec()

    def closeEvent(self, event):
        if self.search_worker and self.search_worker.is_alive():
            self.search_worker.is_cancelled = True
        for t in self.ping_threads: t.is_cancelled = True
        event.accept()


# ===================== Legado 分类浏览对话框 =====================
class ExploreDialog(QDialog):
    """浏览 Legado 书源的分类、排行榜"""

    def __init__(self, parent, legado_sources, caller_dialog=None):
        super().__init__(parent)
        self.setWindowTitle("📚 分类浏览")
        self.setMinimumSize(800, 580)
        self.parent_reader = parent
        self.legado_sources = legado_sources
        self.caller_dialog = caller_dialog  # 记录调用者（如 WebDialog）
        self._current_engine = None
        self._current_categories = []
        self._explore_results = []
        self._explore_thread = None
        self._explore_emitter = None
        self.init_ui()
        # 加载第一个源的分类
        if self.legado_sources:
            self.source_combo.setCurrentIndex(0)
            self._load_categories(0)

    def init_ui(self):
        layout = QVBoxLayout(self)
        apply_dialog_style(self, layout)

        # 顶部：选择书源
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("<b>📖 书源:</b>"))
        self.source_combo = QComboBox()
        for ls in self.legado_sources:
            self.source_combo.addItem(ls.get('name', ''), ls)
        self.source_combo.currentIndexChanged.connect(self._load_categories)
        top_row.addWidget(self.source_combo, stretch=1)
        layout.addLayout(top_row)

        # 分类网格
        self.category_container = QWidget()
        self.category_layout = QGridLayout(self.category_container)
        self.category_layout.setSpacing(8)
        scroll = QScrollArea()
        scroll.setWidget(self.category_container)
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(180)
        layout.addWidget(scroll)

        # 书籍列表
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["书名", "作者", "最新章节", "分类/字数"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemDoubleClicked.connect(self._on_book_double_clicked)
        layout.addWidget(self.table, stretch=1)

        self.status_label = QLabel("点击上方分类按钮加载书籍列表")
        self.status_label.setStyleSheet("color: #909399; font-size: 12px;")
        layout.addWidget(self.status_label)

    def _load_categories(self, index):
        if index < 0 or index >= len(self.legado_sources):
            return
        ls = self.legado_sources[index]
        source_data = ls.get('source_data', [])
        self._current_engine = LegadoEngine(source_data)
        self._current_categories = self._current_engine.get_explore_categories()

        # 清空并重建分类按钮
        while self.category_layout.count():
            item = self.category_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        cols = 5
        for i, cat in enumerate(self._current_categories):
            btn = QPushButton(cat['title'])
            btn.setObjectName("secondaryButton")
            btn.setFixedHeight(32)
            btn.clicked.connect(lambda checked, u=cat['url'], t=cat['title']: self._load_explore(u, t))
            self.category_layout.addWidget(btn, i // cols, i % cols)

        self.table.setRowCount(0)
        self.status_label.setText(f"已加载 {len(self._current_categories)} 个分类，点击上方按钮查看。")

    def _load_explore(self, url, title):
        self.status_label.setText(f"正在加载：{title}...")
        self.table.setRowCount(0)

        # 如果旧线程还在运行，先停止它
        if self._explore_thread is not None and self._explore_thread.isRunning():
            self._explore_thread.terminate()  # 强制终止旧线程
            self._explore_thread.wait(1000)   # 等待最多1秒

        # 使用线程加载
        class ExploreThread(QThread):
            results_ready = Signal(list)
            error = Signal(str)

            def __init__(self, engine, url):
                super().__init__()
                self.engine = engine
                self.url = url

            def run(self):
                try:
                    results = self.engine.get_explore_results(self.url)
                    self.results_ready.emit(results)
                except Exception as e:
                    self.error.emit(str(e))

        self._explore_thread = ExploreThread(self._current_engine, url)
        self._explore_thread.results_ready.connect(self._on_explore_results)
        self._explore_thread.error.connect(self._on_explore_error)
        self._explore_thread.start()

    def _on_explore_results(self, results):
        self._explore_results = results
        self.table.setRowCount(0)
        for book in results:
            row = self.table.rowCount()
            self.table.insertRow(row)
            title_item = QTableWidgetItem(book.get('title', ''))
            title_item.setData(Qt.ItemDataRole.UserRole, book.get('url', ''))
            title_item.setFont(QFont("PingFang SC", -1, QFont.Weight.Bold))
            self.table.setItem(row, 0, title_item)
            self.table.setItem(row, 1, QTableWidgetItem(book.get('author', '')))
            self.table.setItem(row, 2, QTableWidgetItem(book.get('lastChapter', '')))
            self.table.setItem(row, 3, QTableWidgetItem(book.get('kind', '') or book.get('wordCount', '')))
        self.status_label.setText(f"加载完成，共 {len(results)} 本书。双击打开目录。")

    def _on_explore_error(self, err):
        self.status_label.setText(f"加载失败: {err}")

    def _on_book_double_clicked(self, item):
        row = item.row()
        title_item = self.table.item(row, 0)
        book_url = title_item.data(Qt.ItemDataRole.UserRole)
        if book_url:
            # 注册 URL 到 Legado 注册表
            if self._current_engine:
                source_data = self._current_engine.source
                register_legado_url(book_url, source_data)
                BookDetailDialog(self.parent_reader, book_url,
                                 site_name=self._current_engine.name,
                                 legado_source=source_data,
                                 caller_dialog=self,
                                 caller_chain=[self.caller_dialog] if self.caller_dialog else []).exec()
            else:
                BookDetailDialog(self.parent_reader, book_url,
                                 caller_dialog=self,
                                 caller_chain=[self.caller_dialog] if self.caller_dialog else []).exec()


class FileDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("打开本地文件")
        # 设置初始大小，但允许用户手动调整
        self.resize(600, 400)
        self.setMinimumSize(350, 250)  # 最小尺寸限制
        self.parent = parent
        self.history_mapping = {f"{item.get('title', '本地文件')} - {path}": item.get('url', '') for item in
                                self.parent.file_history if (path := local_path_from_url(item.get('url', '')))}
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        apply_dialog_style(self, main_layout)

        form_layout = QFormLayout()
        form_layout.setSpacing(16)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.file_combo = QComboBox()
        self.file_combo.setEditable(True)
        for display_text in self.history_mapping.keys(): self.file_combo.addItem(display_text)

        current_display = ""
        if urlparse(self.parent.current_url).scheme in ("file", "localbook"):
            current_display = next(
                (disp for disp, url in self.history_mapping.items() if url == self.parent.current_url),
                local_path_from_url(self.parent.current_url))
        self.file_combo.setCurrentText(current_display)
        self.file_combo.setPlaceholderText("请选择 txt/epub/mobi 文件或从历史记录中选择...")
        form_layout.addRow("本地文件:", self.file_combo)

        main_layout.addLayout(form_layout)
        main_layout.addSpacing(10)
        main_layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(16)

        self.btn_browse = QPushButton("📂 浏览文件")
        self.btn_browse.setObjectName("secondaryButton")
        self.btn_browse.clicked.connect(self.choose_file)
        btn_row.addWidget(self.btn_browse, 1)

        self.btn_apply = QPushButton("加载文件并开始阅读")
        self.btn_apply.setObjectName("primaryButton")
        self.btn_apply.clicked.connect(self.apply_load)
        btn_row.addWidget(self.btn_apply, 2)

        main_layout.addLayout(btn_row)
        self.file_combo.setFocus()

    def choose_file(self):
        if path := QFileDialog.getOpenFileName(self, "打开小说文件", "", "小说文件 (*.txt *.epub *.mobi)")[0]:
            self.file_combo.setCurrentText(path)

    def apply_load(self):
        input_text = self.file_combo.currentText().strip()
        if not (target := self.history_mapping.get(input_text, input_text)): return

        target_url = target
        path = local_path_from_url(target) if urlparse(target).scheme in ("file", "localbook") else os.path.abspath(
            os.path.expanduser(target))

        if not os.path.exists(path):
            QMessageBox.warning(self, "打开失败", "本地文件不存在，可能已被移动或删除。")
            return

        if urlparse(target).scheme != "localbook":
            try:
                target_url = self.parent.prepare_local_book(path)[0]
            except Exception as e:
                QMessageBox.warning(self, "打开失败", f"无法打开该文件：\n{e}")
                return

        if target_url:
            self.parent._force_reset_index = True
            self.parent.start_async_load(target_url)
        self.accept()