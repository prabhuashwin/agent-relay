"""Loopback-only server for the documentation demo; never starts Relay/pollers."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "coordinator/usagekit/dashboard_assets"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/app.js", "/style.css"):
            name = "index.html" if self.path == "/" else self.path.lstrip("/").split("?")[0]
            self.path = "/" + str((ASSETS / name).relative_to(ROOT)).replace("\\", "/")
        return super().do_GET()


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8790), Handler).serve_forever()
