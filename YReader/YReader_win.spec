# -*- mode: python ; coding: utf-8 -*-
"""
YReader Windows 打包配置
用法: pyinstaller YReader_win.spec
"""
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# 项目根目录
PROJECT_DIR = os.path.dirname(os.path.abspath(SPEC))

# 需要打包进去的初始模板文件（首次启动时如果用户目录没有就复制过去）
data_files = [
    (os.path.join(PROJECT_DIR, 'sites.json'), '.'),
    (os.path.join(PROJECT_DIR, 'legado_sources.json'), '.'),
    (os.path.join(PROJECT_DIR, 'icon.icns'), '.'),
    (os.path.join(PROJECT_DIR, 'icon.ico'), '.'),
]

# 收集依赖的隐藏导入（只包含实际使用的 Qt 模块）
hiddenimports = []
for mod in ['cloudscraper', 'bs4', 'mobi']:
    try:
        hiddenimports += collect_submodules(mod)
    except Exception:
        pass
# PySide6: 只导入用到的子模块，避免打包整个 Qt 框架
for mod in ['PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets', 'PySide6.QtNetwork']:
    try:
        hiddenimports += collect_submodules(mod)
    except Exception:
        pass

# 数据文件（只包含项目自己的，不打包 PySide6 的全部数据）
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
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy', 'pandas', 'PIL', 'cv2',
              'PyQt5', 'PyQt6', 'PySide2',
              'IPython', 'jupyter', 'notebook', 'sphinx',
              'black', 'yapf', 'jedi', 'parso',
              'docutils', 'babel',
              'zmq', 'nbformat',
              'gi',
              ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='YReader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(PROJECT_DIR, 'icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='YReader',
)

# 打包后清理不需要的 Qt 模块（减小体积）
import shutil, glob

_dist_dir = os.path.join(PROJECT_DIR, 'dist', 'YReader')
_qt_dir = os.path.join(_dist_dir, 'PySide6', 'Qt')

# 移除不需要的 Qt DLL（Windows 下是 .dll 文件）
_unneeded_dlls = [
    'QtPdf*.dll', 'QtQuick*.dll', 'QtQml*.dll',
    'QtVirtualKeyboard*.dll', 'QtOpenGL*.dll',
    'Qt3D*.dll', 'QtCharts*.dll', 'QtDataVisualization*.dll',
    'QtMultimedia*.dll', 'QtPositioning*.dll', 'QtSensors*.dll',
    'QtSerialPort*.dll', 'QtSql*.dll', 'QtTest*.dll',
    'QtWebChannel*.dll', 'QtWebEngine*.dll', 'QtWebSockets*.dll',
    'QtXml*.dll',
]
_lib_dir = os.path.join(_qt_dir, 'bin')
if os.path.exists(_lib_dir):
    for pattern in _unneeded_dlls:
        for f in glob.glob(os.path.join(_lib_dir, pattern)):
            os.remove(f)
            print(f'  移除 DLL: {os.path.basename(f)}')

# 移除不需要的图片格式插件（只保留 jpeg/ico）
_img_dir = os.path.join(_qt_dir, 'plugins', 'imageformats')
_keep_images = {'qjpeg.dll', 'qico.dll'}
if os.path.exists(_img_dir):
    for f in os.listdir(_img_dir):
        if f not in _keep_images:
            os.remove(os.path.join(_img_dir, f))
            print(f'  移除图片插件: {f}')

# 移除不需要的平台插件（只保留 windows）
_plat_dir = os.path.join(_qt_dir, 'plugins', 'platforms')
_keep_platforms = {'qwindows.dll'}
if os.path.exists(_plat_dir):
    for f in os.listdir(_plat_dir):
        if f not in _keep_platforms:
            os.remove(os.path.join(_plat_dir, f))
            print(f'  移除平台插件: {f}')

# 移除 Qt 翻译文件
_trans_dir = os.path.join(_qt_dir, 'translations')
if os.path.exists(_trans_dir):
    shutil.rmtree(_trans_dir)
    print(f'  移除 Qt translations')

# 移除不需要的 Qt 模块目录
_unneeded_modules = ['qml', 'qtmultimedia', 'qtquick', 'qtwebengine', 'qt3d', 'qtcharts']
for mod in _unneeded_modules:
    p = os.path.join(_dist_dir, 'PySide6', mod)
    if os.path.exists(p):
        shutil.rmtree(p)
        print(f'  移除模块目录: {mod}')

print('清理完成')
