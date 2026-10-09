"""Entry point for the packaged app (Mac .app / Windows .exe): runs the tool's server in the background
and shows it in a native window. Closing the window quits.

    Transect Tool --selftest RESULT_FILE   exercise the bundled libraries without opening a window
"""
import os
import shutil
import sys
import tempfile
import threading
import traceback
from pathlib import Path

FROZEN = getattr(sys, 'frozen', False)


def log_file():
    if sys.platform == 'darwin':
        d = Path.home() / 'Library' / 'Logs'
    elif os.name == 'nt':
        d = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Transect Tool'
    else:
        d = Path.home() / '.transect-tool'
    d.mkdir(parents=True, exist_ok=True)
    return d / 'Transect Tool.log'


if FROZEN and '--selftest' not in sys.argv:
    # no terminal in a packaged app – keep a log for troubleshooting
    sys.stdout = sys.stderr = open(log_file(), 'a', buffering=1, encoding='utf-8')


class Api:
    """Functions the page can call when running inside the app window (window.pywebview.api.*)."""

    def __init__(self, tool, webview):
        self.tool, self.webview, self.window = tool, webview, None

    def save_output(self, pid, fname):
        wv = self.webview
        src = self.tool.output_path(pid, fname)
        save = getattr(getattr(wv, 'FileDialog', None), 'SAVE', None) or wv.SAVE_DIALOG
        res = self.window.create_file_dialog(save, directory=str(Path.home() / 'Desktop'), save_filename=fname)
        if not res:
            return {'saved': False}
        dest = res if isinstance(res, str) else res[0]
        shutil.copy2(src, dest)
        return {'saved': True, 'path': dest}


def main():
    import webview
    from werkzeug.serving import make_server
    import app as tool

    port = tool.free_port()
    server = make_server('127.0.0.1', port, tool.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{port}/'
    print(f'serving on {port}, projects in {tool.PROJECTS}', flush=True)
    api = Api(tool, webview)
    api.window = webview.create_window('Transect Tool', url, js_api=api,
                                       width=1440, height=920, min_size=(1000, 700))
    try:
        webview.start()
    except Exception:  # noqa: BLE001 – e.g. Windows without the WebView2 runtime
        traceback.print_exc()
        fallback_to_browser(url)
    server.shutdown()


def fallback_to_browser(url):
    """No embedded browser available: use the default browser and keep running until the user says stop."""
    import webbrowser
    webbrowser.open(url)
    msg = 'Transect Tool is open in your web browser.\n\nKeep this message open while you work. Click OK to quit.'
    if os.name == 'nt':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, 'Transect Tool', 0x40)
    else:
        threading.Event().wait()


def selftest(result_path):
    """Run the real pipeline on a small synthetic photo inside the packaged app. Exit code 0 = pass."""
    lines = []
    try:
        tmp = Path(tempfile.mkdtemp(prefix='transect-selftest-'))
        os.environ['TRANSECT_PROJECTS'] = str(tmp / 'projects')
        import cv2
        import numpy as np
        import pipeline as pl
        import app as tool

        # sand-coloured photo with a yellow tape running slightly downhill
        img = np.full((1392, 1044, 3), (150, 170, 160), np.uint8)
        rng = np.random.default_rng(0)
        img = cv2.add(img, rng.integers(0, 40, img.shape, dtype=np.uint8))
        cv2.line(img, (0, 700), (1043, 690), (40, 220, 240), 8)
        photo = tmp / 'photo.jpg'
        cv2.imwrite(str(photo), img)
        tape, score = pl.detect_tape(img)
        geo = pl.geometry(1044, 1392, tape)
        assert abs(geo['dline'] - (695 - 696)) < 15, f'tape found in wrong place: {tape}'
        strip, x0 = pl.make_strip(pl.read_full(photo), geo)
        assert strip.shape[0] == 2 * pl.STRIP_HALF * pl.STRIP_ZOOM
        rd = []
        for sx, cm in ((200, 100.0), (1000, 140.0), (1800, 180.0)):
            x, y = pl.strip_x_to_work(geo, sx, x0)
            rd.append((x, y, cm))
        fit = pl.fit_photos({'p': (geo, rd)}, k=0.0)
        assert max(abs(r) for r in fit['residuals']['p']) < 0.5
        out, holes = pl.render_strip([('p', photo, geo)], fit, 105, 175, 10, 20)
        assert out.shape == (400, 700, 3), out.shape
        segs = [dict(s=110, f=150, major='SD', minors=[], extra=[]),
                dict(s=150, f=170, major='HC', minors=['HCC'], extra=[])]
        marked = pl.draw_markers(out, segs, {'site': 'test'}, 105, 10)
        marked.save(tmp / 'marked.jpg')
        assert pl.parse_tape_value("12' 7\"") and abs(pl.parse_tape_value('12ft 7in') - 383.54) < 0.01
        c = tool.app.test_client()
        assert c.get('/').status_code == 200
        assert c.get('/static/app.js').status_code == 200
        assert c.get('/api/projects').status_code == 200
        import webview  # noqa: F401 – the GUI library must be bundled
        if os.name == 'nt':
            import clr  # noqa: F401 – pythonnet, needed by the Windows WebView2 backend
            from webview.platforms import edgechromium  # noqa: F401
        lines.append(f'tape score {score:.0f}, render {out.shape}, holes {holes:.3f}')
        lines.append('SELFTEST PASS')
        code = 0
    except Exception:  # noqa: BLE001
        lines.append(traceback.format_exc())
        lines.append('SELFTEST FAIL')
        code = 1
    text = '\n'.join(lines) + '\n'
    if result_path:
        Path(result_path).write_text(text, encoding='utf-8')
    if sys.stdout:
        sys.stdout.write(text)
    return code


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        i = sys.argv.index('--selftest')
        sys.exit(selftest(sys.argv[i + 1] if len(sys.argv) > i + 1 else None))
    main()
