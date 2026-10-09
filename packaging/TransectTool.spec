# PyInstaller spec for the packaged app.
#   Mac:      packaging/build_mac.sh          -> Transect Tool.app
#   Windows:  .github/workflows/windows.yml   -> Transect Tool\Transect Tool.exe
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
VERSION = (ROOT / 'packaging' / 'VERSION').read_text().strip()
MAC, WIN = sys.platform == 'darwin', sys.platform == 'win32'

if MAC:
    hidden, gui_excludes = ['webview.platforms.cocoa'], ['webview.platforms.winforms', 'webview.platforms.edgechromium']
else:
    hidden, gui_excludes = ['webview.platforms.winforms', 'webview.platforms.edgechromium', 'clr'], ['webview.platforms.cocoa']

a = Analysis(
    [str(ROOT / 'desktop.py')],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / 'static'), 'static')],
    hiddenimports=hidden,
    excludes=['tkinter', 'matplotlib', 'scipy', 'pandas', 'IPython', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
              'webview.platforms.qt', 'webview.platforms.gtk', 'webview.platforms.cef'] + gui_excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Transect Tool', console=False,
          target_arch='arm64' if MAC else None, codesign_identity=None,
          icon=str(ROOT / 'packaging' / ('TransectTool.icns' if MAC else 'TransectTool.ico')))
coll = COLLECT(exe, a.binaries, a.datas, name='Transect Tool')

if MAC:
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
