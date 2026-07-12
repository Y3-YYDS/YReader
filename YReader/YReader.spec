# -*- mode: python ; coding: utf-8 -*-
"""
YReader macOS 打包配置
用法: pyinstaller YReader.spec
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
    icon=os.path.join(PROJECT_DIR, 'icon.icns'),
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

bundle = BUNDLE(
    coll,
    name='YReader.app',
    icon=os.path.join(PROJECT_DIR, 'icon.icns'),
    bundle_identifier='com.yreader.app',
    info_plist={
        'CFBundleShortVersionString': '1.1.0',
        'CFBundleName': 'YReader',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.15',
        'CFBundleDocumentTypes': [
            {
                'CFBundleTypeName': 'Text File',
                'CFBundleTypeRole': 'Viewer',
                'LSItemContentTypes': ['public.plain-text'],
                'CFBundleTypeExtensions': ['txt'],
            },
            {
                'CFBundleTypeName': 'EPUB File',
                'CFBundleTypeRole': 'Viewer',
                'LSItemContentTypes': ['org.idpf.epub-container'],
                'CFBundleTypeExtensions': ['epub'],
            },
            {
                'CFBundleTypeName': 'MOBI File',
                'CFBundleTypeRole': 'Viewer',
                'CFBundleTypeExtensions': ['mobi'],
            },
        ],
    },
)

# 打包后清理不需要的 Qt 模块（减小体积）
import shutil
_app_dir = os.path.join(PROJECT_DIR, 'dist', 'YReader.app', 'Contents', 'Frameworks', 'PySide6', 'Qt')
_lib_dir = os.path.join(_app_dir, 'lib')
_unneeded_frameworks = [
    'QtPdf.framework', 'QtQuick.framework', 'QtQml.framework',
    'QtQmlModels.framework', 'QtQmlMeta.framework', 'QtQmlWorkerScript.framework',
    'QtVirtualKeyboard.framework', 'QtVirtualKeyboardQml.framework',
    'QtOpenGL.framework',
]
for fw in _unneeded_frameworks:
    p = os.path.join(_lib_dir, fw)
    if os.path.exists(p):
        shutil.rmtree(p)
        print(f'  移除 Framework: {fw}')

# 移除 Qt 翻译文件（不需要，我们用系统 qtbase_zh_CN）
_res_qt = os.path.join(PROJECT_DIR, 'dist', 'YReader.app', 'Contents', 'Resources', 'PySide6', 'Qt', 'translations')
if os.path.exists(_res_qt):
    shutil.rmtree(_res_qt)
    print(f'  移除 Qt translations')
print('清理完成')
