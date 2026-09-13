# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for 全球水电站数据平台 V1
# Build: pyinstaller hydro_platform.spec

block_cipher = None

a = Analysis(
    ['hydro_platform/app/main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # 仅打包只读种子资源；运行期 data/db、raw、archive、logs 不得进入安装包。
        ('data/seed', 'data/seed'),
        # D17修复：打包Web资源（HTML/CSS/JS）
        ('hydro_platform/app/web', 'hydro_platform/app/web'),
        # D17修复：打包数据库schema和迁移脚本
        ('hydro_platform/database/schema.sql', 'hydro_platform/database'),
        ('hydro_platform/database/migrations', 'hydro_platform/database/migrations'),
    ],
    hiddenimports=[
        # hydro_platform 核心模块
        'hydro_platform',
        'hydro_platform.acquisition',
        'hydro_platform.acquisition.router',
        'hydro_platform.acquisition.http_client',
        'hydro_platform.acquisition.browser_client',
        'hydro_platform.acquisition.result',
        'hydro_platform.archive',
        'hydro_platform.archive.archiver',
        'hydro_platform.parsing',
        'hydro_platform.parsing.dispatcher',
        'hydro_platform.parsing.pdf_parser',
        'hydro_platform.parsing.html_parser',
        'hydro_platform.parsing.table_parser',
        'hydro_platform.extraction',
        'hydro_platform.extraction.rule_extractors',
        'hydro_platform.extraction.llm',
        'hydro_platform.common',
        'hydro_platform.common.enums',
        'hydro_platform.common.exceptions',
        'hydro_platform.models',
        'hydro_platform.database',
        'hydro_platform.tasking',
        'hydro_platform.registry',
        'hydro_platform.evidence',
        'hydro_platform.review',
        'hydro_platform.validation',
        'hydro_platform.pipeline',
        'hydro_platform.config',
        'hydro_platform.app',
        'hydro_platform.app.api',
        'hydro_platform.app.bridge',
        'hydro_platform.app.gui',
        'hydro_platform.app.workers',
        # pywebview 后端
        'webview',
        'webview.platforms.winforms',
        'webview.platforms.edgechromium',
        'clr',
        # 可选解析库不强制 hidden-import；未安装时按代码降级，安装后由实际导入收集。
        # pandas/openpyxl/pypdf/pdfplumber 等均由解析器运行时探测，避免把整套
        # 科学计算生态无条件带入桌面包。
        'bs4',
        # 标准库
        'sqlite3',
        'csv',
        'json',
        'threading',
        'uuid',
        'hashlib',
        'email',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Qt 绑定（不使用）
        'PyQt5', 'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets',
        'PyQt5.QtWebEngine', 'PyQt5.QtWebEngineWidgets', 'PyQt5.QtWebEngineCore',
        'PyQt5.QtNetwork', 'PyQt5.QtQml', 'PyQt5.QtQuick',
        'PySide6', 'PySide2', 'PyQt6',
        # webview 其他平台
        'webview.platforms.qt', 'webview.platforms.cef',
        'webview.platforms.gtk', 'webview.platforms.cocoa',
        # 浏览器回退为可选能力；未安装/未打包时路由会如实降级到 HTTP 结果。
        'playwright',
        # Excel 解析首选 openpyxl；pandas 仅为运行时兜底，禁止其科学计算
        # 依赖树进入桌面包。
        'pandas', 'numpy', 'pyarrow', 'numexpr', 'numba', 'llvmlite',
        # 深度学习（如果项目不使用）
        'torch', 'torchvision', 'torchaudio',
        'paddle', 'paddlepaddle',
        'tensorflow', 'keras',
        'transformers', 'tokenizers', 'huggingface_hub',
        'onnxruntime', 'onnx',
        # 可视化（如果不需要）
        'matplotlib', 'bokeh', 'plotly', 'seaborn',
        # 云 SDK
        'botocore', 'boto3', 's3transfer',
        'azure', 'google.cloud',
        # 其他大型库
        'IPython', 'jupyter', 'notebook',
        'scipy', 'sympy', 'statsmodels',
        'tkinter',
        'wx', 'gi', 'pygments',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='全球水电站数据平台',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # 无控制台窗口
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='全球水电站数据平台',
)
