# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['video_color_converter_bundled_final.py'],
    pathex=[],
    binaries=[('ffmpeg', '.'), ('ffprobe', '.')],
    datas=[('/Users/may/Library/Python/3.9/lib/python/site-packages/PyQt5/Qt5/plugins', 'PyQt5/Qt5/plugins')],
    hiddenimports=[],
    hookspath=[],
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
    [],
    exclude_binaries=True,
    name='VideoColorConverter',
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
    icon=['icon.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VideoColorConverter',
)
app = BUNDLE(
    coll,
    name='VideoColorConverter.app',
    icon='icon.icns',
    bundle_identifier=None,
)
