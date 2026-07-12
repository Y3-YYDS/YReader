# -*- mode: python ; coding: utf-8 -*-
"""
YReader Windows 单文件打包配置
用法: pyinstaller YReader_win.spec
"""
import os
import sys
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# 项目根目录
PROJECT_DIR = os.path.dirname(os.path.abspath(SPEC))

# 需要打包进去的初始模板文件
data_files = [
    (os.path.join(PROJECT_DIR, 'sites.json'), '.'),
    (os.path.join(PROJECT_DIR, 'reader_app_sources.json'), '.'), # 已替换关键字
    (os.path.join(PROJECT_DIR, 'icon.icns'), '.'),
    (os.path.join(PROJECT_DIR, 'icon.ico'), '.'),
]

# 收集依赖的隐藏导入
hiddenimports = []
for mod in ['cloudscraper', 'bs4', 'mobi']:
    try:
        hiddenimports += collect_submodules(mod)
    except Exception:
        pass

for mod in ['PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets', 'PySide6.QtNetwork']:
  try:
      hiddenimports += collect_submodules(mod)
  except Exception:
      pass

datas = list(data_files)

a = Analysis(
    [os.path.join(PROJECT_DIR, 'main.py')],
    pathex=[PROJECT_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 排除完全没用到的重量级库，减小单文件体积
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy', 'pandas', 'PIL', 'cv2',
              'PyQt5', 'PyQt6', 'PySide2', 'IPython', 'jupyter',
              # 显式排除没用到的 Qt 模块，从源头瘦身
              'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtWebEngineCore',
              'PySide6.QtWebEngineQuick', 'PySide6.QtMultimedia', 'PySide6.QtSql',
              'PySide6.QtXml', 'PySide6.Qt3DCore', 'PySide6.QtCharts'
              ],
    noarchive=False,
    optimize=0,
)

# 【核心体积优化】在打包成单文件前，过滤掉无用的 Qt 动态链接库和插件
# 这代替了你之前在文件末尾写的物理删除代码
unneeded_dll_keywords = [
    'Qt6Pdf', 'Qt6Quick', 'Qt6Qml', 'Qt6VirtualKeyboard', 'Qt6OpenGL',
    'Qt63D', 'Qt6Charts', 'Qt6DataVisualization', 'Qt6Multimedia',
    'Qt6Positioning', 'Qt6Sensors', 'Qt6SerialPort', 'Qt6Sql', 'Qt6Test',
    'Qt6WebChannel', 'Qt6WebEngine', 'Qt6WebSockets', 'Qt6Xml'
]

# 过滤二进制文件 (DLLs)
filtered_binaries = []
for item in a.binaries:
    name = item[0]
    if any(keyword.lower() in name.lower() for keyword in unneeded_dll_keywords):
        continue
    # 过滤非必要的图片和平台插件
    if 'imageformats' in name and not any(k in name for k in ['qjpeg', 'qico']):
        continue
    if 'platforms' in name and 'qwindows' not in name:
        continue
    filtered_binaries.append(item)
a.binaries = filtered_binaries

# 过滤翻译文件数据
a.datas = [item for item in a.datas if 'translations' not in item[0]]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# 修改此处：将所有东西直接打包进 EXE
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,  # 将二进制文件塞进单文件
    a.datas,     # 将资源数据塞进单文件
    [],
    name='YReader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,    # 开启 UPX 压缩以极大减小单文件体积（如果电脑安装了 UPX）
    console=False, # 隐藏控制台黑框
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(PROJECT_DIR, 'icon.ico'),
)