"""Serve the deck for presenting: http://localhost:5190/

    python serve.py            (from this folder)

Same as `python -m http.server`, but every response says "don't cache", so
an edited slide or intro shows up on the next reload instead of an old copy.
Binds to loopback only; open it as http://localhost:5190/ (not 127.0.0.1)
so the live demo frame shares the app's sign-in.
"""
import functools
import http.server
from pathlib import Path

PORT = 5190


class NoCache(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    handler = functools.partial(NoCache, directory=str(Path(__file__).parent))
    with http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler) as httpd:
        print(f"Deck on http://localhost:{PORT}/  (Ctrl+C to stop)")
        httpd.serve_forever()
