from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QCheckBox, QHBoxLayout,
                               QFontComboBox, QSpinBox, QComboBox, QLabel, QPushButton,
                               QKeySequenceEdit, QColorDialog, QFileDialog, QMessageBox)
from PySide6.QtGui import QColor, QFont, QKeySequence
from PySide6.QtCore import Qt

from utils import apply_dialog_style, WEIGHT_MAP, IS_MAC, set_mac_dock_icon_visible, set_mac_window_shadow

class SettingsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("偏好设置")
        self.setMinimumWidth(550)
        self.parent, self.temp_text_color, self.temp_bg_color = parent, parent.text_color, parent.bg_color
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        apply_dialog_style(self, main_layout)

        form_layout = QFormLayout()
        form_layout.setSpacing(16)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.cb_multi_line = QCheckBox("开启多行显示模式 (根据窗口高度自动换行)")
        self.cb_multi_line.setChecked(self.parent.multi_line)
        form_layout.addRow("多行显示模式:", self.cb_multi_line)

        self.cb_taskbar = QCheckBox("在任务栏/Dock 栏显示程序图标")
        self.cb_taskbar.setChecked(self.parent.show_taskbar)
        form_layout.addRow("任务栏/Dock 栏:", self.cb_taskbar)

        self.cb_seamless = QCheckBox("开启无缝阅读 (继续按上/下一句自动切换章节)")
        self.cb_seamless.setChecked(self.parent.seamless_chapter)
        form_layout.addRow("翻页模式:", self.cb_seamless)

        self.cb_always_on_top = QCheckBox("阅读窗口始终显示在最前 (关闭后点击其他软件会遮挡本窗口)")
        self.cb_always_on_top.setChecked(self.parent.always_on_top)
        form_layout.addRow("窗口置顶:", self.cb_always_on_top)

        font_layout = QHBoxLayout()
        font_layout.setSpacing(12)
        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(QFont(self.parent.font_family))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(8, 150)
        self.size_spin.setValue(self.parent.font_size)

        self.weight_combo = QComboBox()
        self.weight_combo.addItems(list(WEIGHT_MAP.keys()))
        self.weight_combo.setCurrentText(self.parent.font_weight_name)

        font_layout.addWidget(self.font_combo, stretch=3)
        font_layout.addWidget(QLabel("大小:"))
        font_layout.addWidget(self.size_spin, stretch=1)
        font_layout.addWidget(QLabel("粗细:"))
        font_layout.addWidget(self.weight_combo, stretch=2)
        form_layout.addRow("字体设置:", font_layout)

        spacing_layout = QHBoxLayout()
        spacing_layout.setSpacing(12)
        self.spin_letter = QSpinBox()
        self.spin_letter.setRange(0, 50)
        self.spin_letter.setValue(self.parent.letter_spacing)
        self.spin_letter.setToolTip("字间距像素")

        self.spin_line = QSpinBox()
        self.spin_line.setRange(50, 300)
        self.spin_line.setSuffix(" %")
        self.spin_line.setValue(self.parent.line_spacing)
        self.spin_line.setToolTip("行间距(仅多行生效)")

        spacing_layout.addWidget(QLabel("字间距:"))
        spacing_layout.addWidget(self.spin_letter)
        spacing_layout.addWidget(QLabel("行间距:"))
        spacing_layout.addWidget(self.spin_line)
        spacing_layout.addStretch(1)
        form_layout.addRow("间距调整:", spacing_layout)

        color_layout1 = QHBoxLayout()
        color_layout1.setSpacing(12)
        self.btn_text_color = QPushButton("修改文字颜色")
        self.btn_text_color.setObjectName("secondaryButton")
        self.btn_text_color.clicked.connect(self.choose_text_color)

        self.text_opacity_spin = QSpinBox()
        self.text_opacity_spin.setRange(0, 100)
        self.text_opacity_spin.setSuffix(" %")
        self.text_opacity_spin.setValue(self.parent.text_opacity)

        color_layout1.addWidget(self.btn_text_color, stretch=1)
        color_layout1.addWidget(QLabel("文字不透明度:"))
        color_layout1.addWidget(self.text_opacity_spin, stretch=1)
        form_layout.addRow("文字色彩:", color_layout1)

        color_layout2 = QHBoxLayout()
        color_layout2.setSpacing(12)
        self.btn_bg_color = QPushButton("修改背景颜色")
        self.btn_bg_color.setObjectName("secondaryButton")
        self.btn_bg_color.clicked.connect(self.choose_bg_color)

        self.bg_opacity_spin = QSpinBox()
        self.bg_opacity_spin.setRange(0, 100)
        self.bg_opacity_spin.setSuffix(" %")
        self.bg_opacity_spin.setValue(self.parent.bg_opacity)

        color_layout2.addWidget(self.btn_bg_color, stretch=1)
        color_layout2.addWidget(QLabel("背景不透明度:"))
        color_layout2.addWidget(self.bg_opacity_spin, stretch=1)
        form_layout.addRow("背景色彩:", color_layout2)

        form_layout.addRow(QLabel(""), QLabel(""))

        self.ks_prev_line = QKeySequenceEdit(QKeySequence(self.parent.key_prev_line))
        self.ks_next_line = QKeySequenceEdit(QKeySequence(self.parent.key_next_line))
        self.ks_prev_page = QKeySequenceEdit(QKeySequence(self.parent.key_prev_page))
        self.ks_next_page = QKeySequenceEdit(QKeySequence(self.parent.key_next_page))

        shortcut_layout1 = QHBoxLayout()
        shortcut_layout1.setSpacing(12)
        shortcut_layout1.addWidget(QLabel("上一句(←):"))
        shortcut_layout1.addWidget(self.ks_prev_line, stretch=1)
        shortcut_layout1.addWidget(QLabel("下一句(→):"))
        shortcut_layout1.addWidget(self.ks_next_line, stretch=1)
        form_layout.addRow("快捷键(按句):", shortcut_layout1)

        shortcut_layout2 = QHBoxLayout()
        shortcut_layout2.setSpacing(12)
        shortcut_layout2.addWidget(QLabel("上一章(↑):"))
        shortcut_layout2.addWidget(self.ks_prev_page, stretch=1)
        shortcut_layout2.addWidget(QLabel("下一章(↓):"))
        shortcut_layout2.addWidget(self.ks_next_page, stretch=1)
        form_layout.addRow("快捷键(按章):", shortcut_layout2)

        self.ks_boss = QKeySequenceEdit(QKeySequence(self.parent.key_boss))
        shortcut_layout3 = QHBoxLayout()
        shortcut_layout3.setSpacing(12)
        shortcut_layout3.addWidget(self.ks_boss, stretch=1)
        shortcut_layout3.addWidget(QLabel(""), stretch=1)
        shortcut_layout3.addWidget(QLabel(""), stretch=1)
        form_layout.addRow("老板键(显示/隐藏界面):", shortcut_layout3)

        self.btn_icon = QPushButton("🖼️ 选择自定义程序图标 (支持 .png .ico)")
        self.btn_icon.setObjectName("secondaryButton")
        self.btn_icon.clicked.connect(self.choose_icon)
        form_layout.addRow("个性化图标:", self.btn_icon)

        main_layout.addLayout(form_layout)
        main_layout.addSpacing(20)
        main_layout.addStretch()

        self.btn_apply = QPushButton("保存所有设置并应用")
        self.btn_apply.setObjectName("primaryButton")
        self.btn_apply.clicked.connect(self.apply_settings)
        main_layout.addWidget(self.btn_apply)

    def _get_translated_color_dialog(self, initial_color, title):
        dialog = QColorDialog(initial_color, self)
        dialog.setWindowTitle(title)
        dialog.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel, False)
        dialog.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        return dialog

    def choose_text_color(self):
        init_color = QColor(self.temp_text_color)
        init_color.setAlpha(255)
        if dialog := self._get_translated_color_dialog(init_color, "请选择文字颜色"):
            if dialog.exec():
                self.temp_text_color = dialog.currentColor()
                self.btn_text_color.setText("文字颜色已选定")

    def choose_bg_color(self):
        init_color = QColor(self.temp_bg_color)
        init_color.setAlpha(255)
        if dialog := self._get_translated_color_dialog(init_color, "请选择背景颜色"):
            if dialog.exec():
                self.temp_bg_color = dialog.currentColor()
                self.btn_bg_color.setText("背景颜色已选定")

    def choose_icon(self):
        if path := QFileDialog.getOpenFileName(self, "选择自定义图标", "", "Images (*.png *.ico *.jpg *.jpeg *.webp)")[0]:
            self.parent.icon_path = path
            self.parent.update_icon()
            self.parent.save_current_config()
            self.btn_icon.setText("✅ 图标已更换并保存")

    def apply_settings(self):
        if self.bg_opacity_spin.value() == 0:
            QMessageBox.information(
                self, "全透明提示",
                "背景不透明度已设为 0% (即完全透明)。\n\n⚠️ 注意：在全透明状态下，鼠标点击背景会直接【穿透】本窗口！\n如果你接下来想拖动窗口位置或调整大小，请将鼠标【精准放在文字的笔画上】再进行拖动。"
            )

        taskbar_changed = self.parent.show_taskbar != self.cb_taskbar.isChecked()
        bosskey_changed = self.parent.key_boss != self.ks_boss.keySequence().toString()
        always_on_top_changed = self.parent.always_on_top != self.cb_always_on_top.isChecked()

        self.parent.multi_line = self.cb_multi_line.isChecked()
        self.parent.seamless_chapter = self.cb_seamless.isChecked()
        self.parent.show_taskbar = self.cb_taskbar.isChecked()
        self.parent.always_on_top = self.cb_always_on_top.isChecked()
        self.parent.font_family = self.font_combo.currentFont().family()
        self.parent.font_size = self.size_spin.value()
        self.parent.font_weight_name = self.weight_combo.currentText()
        self.parent.text_color = self.temp_text_color
        self.parent.bg_color = self.temp_bg_color
        self.parent.text_opacity = self.text_opacity_spin.value()
        self.parent.bg_opacity = self.bg_opacity_spin.value()
        self.parent.letter_spacing = self.spin_letter.value()
        self.parent.line_spacing = self.spin_line.value()

        self.parent.key_prev_line = self.ks_prev_line.keySequence().toString()
        self.parent.key_next_line = self.ks_next_line.keySequence().toString()
        self.parent.key_prev_page = self.ks_prev_page.keySequence().toString()
        self.parent.key_next_page = self.ks_next_page.keySequence().toString()
        self.parent.key_boss = self.ks_boss.keySequence().toString()

        self.parent.update_custom_shortcuts()

        if IS_MAC:
            if bosskey_changed:
                if hasattr(self.parent, '_mac_hotkey_manager') and self.parent._mac_hotkey_manager:
                    self.parent._mac_hotkey_manager.register(self.parent.key_boss)
            if taskbar_changed:
                # macOS: 立即调用原生 API 控制 Dock 图标（无需重启）
                set_mac_dock_icon_visible(self.parent.show_taskbar)
            if always_on_top_changed or taskbar_changed:
                # 重新设置窗口标志
                flags = Qt.WindowType.FramelessWindowHint
                if self.parent.always_on_top:
                    flags |= Qt.WindowType.WindowStaysOnTopHint
                if not self.parent.show_taskbar:
                    flags |= Qt.WindowType.Tool
                self.parent.setWindowFlags(flags)
                self.parent._apply_window_attributes()  # 重新应用窗口属性（阴影等）
                if not self.parent.is_hidden: self.parent.show()
                # show() 后可能重置阴影，需再次禁用
                if IS_MAC:
                    try:
                        set_mac_window_shadow(int(self.parent.winId()), False)
                    except Exception:
                        pass
        else:
            if bosskey_changed and hasattr(self.parent, '_win_hotkey_manager') and self.parent._win_hotkey_manager:
                self.parent.register_global_boss_key(self.parent.key_boss)
            if taskbar_changed or always_on_top_changed:
                flags = Qt.WindowType.FramelessWindowHint
                if self.parent.always_on_top:
                    flags |= Qt.WindowType.WindowStaysOnTopHint
                if not self.parent.show_taskbar: flags |= Qt.WindowType.Tool
                self.parent.setWindowFlags(flags)
                self.parent._apply_window_attributes()  # 重新应用窗口属性（阴影等）
                if not self.parent.is_hidden: self.parent.show()

        self.parent.apply_styles()
        self.parent.update_text()
        self.parent.save_current_config()

        self.accept()
