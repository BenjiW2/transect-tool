"""Entry point for the packaged Mac app: runs the tool's server in the background and shows it in a
native window. Closing the window (or Cmd-Q) quits."""
import shutil
import sys
import threading
from pathlib import Path

if getattr(sys, 'frozen', False):
    # no terminal in a .app – keep a log for troubleshooting
    log_dir = Path.home() / 'Library' / 'Logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(log_dir / 'Transect Tool.log', 'a', buffering=1)

import webview
from werkzeug.serving import make_server

import app as tool


class Api:
    """Functions the page can call when running inside the app window (window.pywebview.api.*)."""

    def __init__(self):
        self.window = None

    def save_output(self, pid, fname):
        src = tool.output_path(pid, fname)
        save = getattr(getattr(webview, 'FileDialog', None), 'SAVE', None) or webview.SAVE_DIALOG
        res = self.window.create_file_dialog(save, directory=str(Path.home() / 'Desktop'), save_filename=fname)
        if not res:
            return {'saved': False}
        dest = res if isinstance(res, str) else res[0]
        shutil.copy2(src, dest)
        return {'saved': True, 'path': dest}


def main():
    port = tool.free_port()
    server = make_server('127.0.0.1', port, tool.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f'serving on {port}, projects in {tool.PROJECTS}', flush=True)
    api = Api()
    api.window = webview.create_window('Transect Tool', f'http://127.0.0.1:{port}/', js_api=api,
                                       width=1440, height=920, min_size=(1000, 700))
    webview.start()
    server.shutdown()


if __name__ == '__main__':
    main()
