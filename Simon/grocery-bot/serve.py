"""
Replay viewer server — serves viewer.html and provides API for replay files.

Usage:
    python grocery-bot/serve.py [--port 8000]
"""

import argparse
import json
import os
import sys
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

DIR = Path(__file__).parent
REPLAY_DIR = DIR / "replays"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIR), **kwargs)

    def do_GET(self):
        if self.path == "/":
            self.path = "/viewer.html"
            return super().do_GET()

        if self.path == "/api/replays":
            return self.list_replays()

        if self.path.startswith("/api/replays/"):
            filename = self.path[len("/api/replays/"):]
            return self.serve_replay(filename)

        return super().do_GET()

    def list_replays(self):
        REPLAY_DIR.mkdir(exist_ok=True)
        replays = []
        for f in sorted(REPLAY_DIR.glob("*.json"), reverse=True):
            try:
                with open(f) as fh:
                    # Read only metadata and result without loading all frames
                    data = json.load(fh)
                    replays.append({
                        "filename": f.name,
                        "metadata": data.get("metadata", {}),
                        "result": data.get("result"),
                        "frame_count": len(data.get("frames", [])),
                    })
            except (json.JSONDecodeError, OSError):
                continue

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(replays).encode())

    def serve_replay(self, filename):
        # Prevent path traversal
        if "/" in filename or "\\" in filename or ".." in filename:
            self.send_error(400, "Invalid filename")
            return

        filepath = REPLAY_DIR / filename
        if not filepath.exists():
            self.send_error(404, "Replay not found")
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        with open(filepath, "rb") as f:
            self.wfile.write(f.read())

    def log_message(self, format, *args):
        # Quieter logging — only show non-200 or API calls
        status = args[1] if len(args) > 1 else ""
        if str(status) != "200" or "/api/" in (args[0] if args else ""):
            super().log_message(format, *args)


def main():
    parser = argparse.ArgumentParser(description="Grocery Bot Replay Viewer")
    parser.add_argument("--port", "-p", type=int, default=8000)
    parser.add_argument("--no-open", action="store_true", help="Don't open browser")
    args = parser.parse_args()

    REPLAY_DIR.mkdir(exist_ok=True)

    server = HTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://localhost:{args.port}"
    print(f"Replay viewer: {url}")
    print(f"Replays dir:   {REPLAY_DIR}")
    print("Press Ctrl+C to stop\n")

    if not args.no_open:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
