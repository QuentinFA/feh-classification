"""Local UI server: static files from web/ and build/, plus GET/PUT /api/state (state.json)."""
import json
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

SERVED = ("/web/", "/build/")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, state_path, **kw):
        self.state_path = state_path
        super().__init__(*a, **kw)

    def do_GET(self):
        if self.path == "/":
            self.send_response(302)
            self.send_header("Location", "/web/index.html")
            self.end_headers()
        elif self.path == "/api/state":
            body = b"{}"
            if os.path.exists(self.state_path):
                with open(self.state_path, "rb") as f:
                    body = f.read()
            self._send(200, body)
        elif self.path.startswith(SERVED):
            super().do_GET()
        else:
            self._send(404, b'{"error":"not found"}')

    def do_PUT(self):
        if self.path != "/api/state":
            return self._send(404, b'{"error":"not found"}')
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            state = json.loads(raw)
        except ValueError:
            return self._send(400, b'{"error":"invalid json"}')
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.state_path)
        self._send(200, b'{"ok":true}')

    def end_headers(self):
        # data.js and app.js change on every build: make the browser revalidate instead of
        # reusing a heuristically cached copy
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _send(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def serve(root, state_path, port):
    handler = partial(Handler, directory=root, state_path=state_path)
    print(f"http://localhost:{port}/")
    ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()
