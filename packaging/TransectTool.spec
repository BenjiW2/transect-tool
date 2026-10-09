# PyInstaller spec for the Mac app.  Build with:  packaging/build_mac.sh
from pathlib import Path

ROOT = Path(SPECPATH).parent
VERSION = (ROOT / 'packaging' / 'VERSION').read_text().strip()

a = Analysis(
    [str(ROOT / 'desktop.py')],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / 'static'), 'static')],
    hiddenimports=['webview.platforms.cocoa'],
    excludes=['tkinter', 'matplotlib', 'scipy', 'pandas', 'IPython', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
              'webview.platforms.qt', 'webview.platforms.gtk', 'webview.platforms.cef'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Transect Tool', console=False,
          target_arch='arm64', codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, name='Transect Tool')
app = BUNDLE(
    coll,
    name='Transect Tool.app',
    icon=str(ROOT / 'packaging' / 'TransectTool.icns'),
    bundle_identifier='au.edu.uq.transecttool',
    version=VERSION,
    info_plist={
        'CFBundleDisplayName': 'Transect Tool',
        'CFBundleShortVersionString': VERSION,
        'LSMinimumSystemVersion': '13.0',
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,
    },
)
