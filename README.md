<p align="center">
  <h1 align="center">YReader</h1>
  <p align="center">极简单行小说阅读器</p>
  <p align="center">
    <img src="https://img.shields.io/badge/Platform-macOS%20%7C%20Windows-blue" alt="Platform">
    <img src="https://img.shields.io/badge/Python-3.12+-green" alt="Python">
    <img src="https://img.shields.io/badge/UI-PySide6%20%2F%20Qt6-purple" alt="UI">
    <img src="https://img.shields.io/badge/License-MIT-yellow" alt="License">
  </p>
</p>

---

## ✨ 简介

YReader 是一款极简风格的单行小说阅读器，支持**在线阅读**和**本地文件阅读**。窗口小巧精致，可置顶显示，适合边工作边摸鱼阅读。

## 📸 功能特性

### 📖 在线阅读
- **9 大书源**内置，涵盖主流小说站点
- **Legado（阅读 3.0）书源**兼容，支持导入自定义书源
- **owllook 聚合搜索**，全网搜书一步到位
- 智能章节解析，自动提取正文内容
- 上下章无缝切换，支持自动预加载

### 📁 本地阅读
- 支持 **TXT / EPUB / MOBI** 三种格式
- TXT 智能分章，自动识别章节标题
- EPUB/MOBI 完整解析，保留章节目录
- 阅读进度自动保存

### 🎨 个性化
- 自定义字体、字号、字重
- 自定义文字颜色、背景颜色
- 文字/背景透明度调节
- 字间距、行间距精细控制
- 自定义图标支持

### ⌨️ 快捷键
- 全局热键（老板键），一键隐藏/显示
- 自定义翻页、翻行快捷键
- 鼠标滚轮翻页支持

### 🖥️ 系统特性
- **macOS**：隐藏 Dock 图标、去除窗口阴影、菜单栏显示
- **Windows**：系统托盘、全局热键
- 窗口置顶 / 无边框 / 自定义位置
- 阅读进度、窗口位置自动记忆

## 🚀 快速开始

### 下载

前往 [Releases](https://github.com/Y3-YYDS/YReader/releases/) 页面下载对应平台的安装包：

| 平台 | 文件 | 说明 |
|------|------|------|
| macOS | `YReader.dmg` | 拖拽到 Applications 安装 |
| Windows | `YReader.zip` | 解压后运行 `YReader.exe` |

### 首次使用

1. 打开应用后，**右键**窗口唤出菜单
2. 选择「**网页在线阅读**」搜索小说，或「**打开本地文件**」阅读本地电子书
3. 在「**偏好设置**」中自定义外观和快捷键

## 🛠️ 开发环境

### 环境要求

- Python 3.12+
- PySide6 (Qt6)

### 安装依赖

```bash
pip install PySide6 cloudscraper beautifulsoup4 mobi
```

### 运行

```bash
python main.py
```

### 打包

**macOS：**
```bash
pyinstaller YReader.spec --clean --noconfirm
```

**Windows：**
```bash
pyinstaller YReader_win.spec --clean --noconfirm
```

## 📂 项目结构

```
YReader/
├── main.py              # 主窗口 & 应用入口
├── utils.py             # 核心工具（网络请求、文件解析、配置管理）
├── legado_adapter.py    # Legado 阅读 3.0 书源适配器
├── dialog_reading.py    # 阅读对话框（网页/本地/目录）
├── dialog_settings.py   # 偏好设置对话框
├── search.py            # 搜索功能
├── mac_hotkey.py        # macOS 全局热键
├── windows_hotkey.py    # Windows 全局热键
├── sites.json           # 内置书源配置
├── legado_sources.json  # Legado 书源配置
├── YReader.spec         # macOS 打包配置
└── YReader_win.spec     # Windows 打包配置
```

## ️ 配置说明

打包后，用户配置文件存储在：

| 平台 | 路径 |
|------|------|
| macOS | `~/Library/Application Support/YReader/` |
| Windows | `%APPDATA%/YReader/` |

包含以下文件：
- `reader_config.json` — 阅读器设置（字体、颜色、快捷键等）
- `sites.json` — 书源配置
- `legado_sources.json` — Legado 书源

## 📋 书源列表

| 书源 | 类型 | 搜索 |
|------|------|------|
| 新笔趣阁 | 自动 | ✅ |
| 笔趣阁全本 | 手动 | ✅ |
| 浅唱阁 | 手动 | ✅ |
| 乐文小说 | 手动 | ✅ |
| 小说旗 | 手动 | ✅ |
| 笔趣阁(yc) | 手动 | ✅ |
| 紫文书屋 | 手动 | ✅ |
| 爱曲小说 | 自动 | ✅ |
| owllook 聚合搜索 | 自动 | ✅ |

> **自动**：自动搜索并解析章节列表
> **手动**：需手动输入书籍目录页 URL

## 📄 License

[MIT License](LICENSE)

## 🙏 致谢

- [PySide6](https://www.qt.io/product/qt6) — Qt6 Python 绑定
- [cloudscraper](https://github.com/VeNoMouS/cloudscraper) — 反爬虫请求库
- [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/) — HTML 解析
- [Legado](https://github.com/gedoor/legado) — 阅读 3.0 开源项目
