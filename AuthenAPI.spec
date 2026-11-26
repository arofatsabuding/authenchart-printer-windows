# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('main.py', '.'), ('app.png', '.'), ('app.ico', '.')]
binaries = []
hiddenimports = [
    'win32timezone', 'win32ui',
    # ✅ เพิ่มสำหรับฟีเจอร์อ่านบัตรประชาชน (pyscard)
    'smartcard_reader',
    'app_paths',
    'smartcard',
    'smartcard.System',
    'smartcard.util',
    'smartcard.Exceptions',
    'smartcard.pcsc',
    'smartcard.scard',
    'smartcard.CardConnection',
    'smartcard.CardConnectionDecorator',
    'smartcard.ReaderMonitoring',
    'smartcard.CardMonitoring',
    # ✅ เพิ่มสำหรับฟีเจอร์เช็ค/ดาวน์โหลดอัปเดตอัตโนมัติ (requests)
    'requests',
    'urllib3',
    'certifi',
    'idna',
    'charset_normalizer',
    'PIL.ImageTk',
    # ✅ เพิ่มสำหรับฟีเจอร์สร้าง shortcut (.lnk) ตอนติดตั้งอัตโนมัติ
    'win32com',
    'win32com.client',
    'win32com.shell',
    'win32com.shell.shell',
    'pythoncom',
    'pywintypes',
]
tmp_ret = collect_all('pywin32')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['tray_runner.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=['.'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AuthenAPI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app.ico'],
)
