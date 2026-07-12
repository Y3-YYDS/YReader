<p align="center">
  <!-- APP 图标 -->
  <img src="https://github.com/user-attachments/assets/1de4daea-c9ce-4abd-a942-89a5c42d088d" alt="YReader" width="128" height="128" style="border-radius: 28px;;" />

  <h1 align="center">YReader</h1>
  <p align="center">YReader - 极简单行小说阅读器 - 上班摸鱼神器</p>
  <p align="center">
    <img src="https://img.shields.io/badge/Platform-macOS%20%7C%20Windows-blue" alt="Platform">
    <img src="https://img.shields.io/badge/Python-3.12+-green" alt="Python">
    <img src="https://img.shields.io/badge/UI-PySide6%20%2F%20Qt6-purple" alt="UI">
    <img src="https://img.shields.io/badge/License-MIT-yellow" alt="License">
  </p>
</p>

---

## ✨ 简介

YReader 是一款为了**上班摸鱼**而设计的极简风格的单行小说阅读器，支持**在线阅读**和**本地文件阅读**。窗口小巧精致，可置顶显示，适合边工作边摸鱼阅读。

### 🖥️ 系统支持
- **macOS**：MacOS Tahoe 26.5.1 Apple Silicon（MacOS仅在该系统进行测试，其他版本系统请自行测试）
- **Windows**：Windows 11 或 Windows 10 64位以上系统

## 📸 功能特性

<img width="800" height="426" alt="image" src="https://github.com/user-attachments/assets/155970ff-c6e3-4254-ac02-f4bcdc8ca9c1" />

<p align="center"><sub>做 PPT 时可以摸鱼使用</sub></p>

  
<img width="800" height="426" alt="75-ezgif com-video-to-gif-converter" src="https://github.com/user-attachments/assets/dbce82f6-24c1-4d49-8633-31c7e2a2b861" />

<p align="center"><sub>聊天时候可以完美隐藏在聊天界面</sub></p>

### 📖 在线阅读
- **9 大书源**内置，涵盖主流小说站点
- **阅读APP书源**兼容，支持导入自定义书源
- **聚合搜索功能**，全网搜书一步到位
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
2. 选择「**在线阅读**」搜索小说，或「**打开文件**」阅读本地电子书
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
├── legado_adapter.py    # 阅读APP书源适配(测试)
├── dialog_reading.py    # 阅读对话框（网页/本地/目录）
├── dialog_settings.py   # 偏好设置对话框
├── search.py            # 搜索功能
├── mac_hotkey.py        # macOS 全局热键
├── windows_hotkey.py    # Windows 全局热键
├── sites.json           # 内置书源配置
├── legado_sources.json  # 阅读APP书源配置
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
- `sites.json` — 本地书源配置
- `legado_sources.json` — 阅读APP书源配置

## 📋 书源列表

已内置书源。更多书源请点击 [阅读APP书源](https://www.yckceo.com/yuedu/shuyuan/index.html) (测试)

> **自动**：自动搜索并解析章节列表
> **手动**：需手动输入书籍目录页 URL

## 📄 License

[MIT License](LICENSE)

## ⚖️ 免责声明 (Disclaimer)

1. 本项目（YReader）是一个**纯技术研究与功能演练的开源学习项目**，代码仅供个人学习、技术交流与研究使用。
2. 本软件本身**不存储、不传播、不提供**任何小说内容、文本数据或音视频资源。
3. 任何通过本软件加载、搜索或阅读的网络内容，均来自互联网第三方公开渠道。
4. 本软件作者不鼓励、不支持任何形式的商业侵权行为。**请勿将本项目用于任何商业用途或非法分发。** 用户因不当使用本软件而导致的任何版权纠纷或法律责任，均由用户个人承担，作者不承担任何连带责任。
5. **如有侵权，请联系删除**：若版权方认为本软件的某些内置解析示例或开源代码侵犯了您的合法权益，请提交 Issue 或通过 GitHub 与作者取得联系，我们将会在第一时间配合删除或修改相关代码。
