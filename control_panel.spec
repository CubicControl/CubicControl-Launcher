# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Collect all hidden imports
hidden_imports = [
    'flask',
    'flask_socketio',
    'socketio',
    'engineio',
    'jinja2',
    'werkzeug',
    'mcstatus',
    'mcrcon',
    'requests',
    'dns',
    'dns.resolver',
    'engineio.async_drivers.threading',
    'socketio.async_drivers.threading',
    'engineio.async_drivers',
    'socketio.async_drivers',
    'pygetwindow',
]

# Add all submodules from your src package
hidden_imports += collect_submodules('src')

# Data files to include
datas = [
    ('src/interface/templates', 'templates'),
    ('src/interface/static', 'static'),
]

# Add any config files if needed
if os.path.exists('ServerConfig.ini'):
    datas.append(('ServerConfig.ini', '.'))
if os.path.exists('APIServerConfig.ini'):
    datas.append(('APIServerConfig.ini', '.'))

a = Analysis(
    ['src/app.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='CubicControl',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='CubicControlICO.ico',
)

