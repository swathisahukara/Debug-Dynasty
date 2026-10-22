"""Serve snapshot CSVs as JSON so Zetaris REST tables can read them. Stdlib only.
Run on the Mac:  python3 snapshot/serve_rows.py [--dir data/raw] [--port 9000]
Endpoints: /releases /maintainers /dependencies  -> {"rows":[...]}   Optional ?package=name
Zetaris (Docker) should reach it at http://host.docker.internal:9000/<table>
"""
import argparse, csv, json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

TABLES = ("releases", "maintainers", "dependencies")


def make_handler(d):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urlparse(self.path)
            name = u.path.strip("/")
            if name == "health":
                return self._send(200, {"ok": True})
            if name not in TABLES:
                return self._send(404, {"error": "unknown table"})
            pkg = parse_qs(u.query).get("package", [None])[0]
            with (d / f"{name}.csv").open(newline="") as f:
                rows = [r for r in csv.DictReader(f) if not pkg or r["package"] == pkg]
            self._send(200, {"rows": rows})

        def _send(self, code, obj):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
    return H


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/build")
    ap.add_argument("--port", type=int, default=9000)
    a = ap.parse_args()
    print(f"serving {a.dir} on 0.0.0.0:{a.port}")
    HTTPServer(("0.0.0.0", a.port), make_handler(Path(a.dir))).serve_forever()
