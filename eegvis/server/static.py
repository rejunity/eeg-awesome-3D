"""Static frontend serving.

Serves the built Vite app from ``web/dist`` when present. If the frontend has
not been built yet, serves a small placeholder page that explains how to build
it or run the Vite dev server — so ``python -m eegvis run`` is always useful,
even before ``npm run build``.
"""

from __future__ import annotations

from pathlib import Path

# repo_root/eegvis/server/static.py -> repo_root
REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_DIST = REPO_ROOT / "web" / "dist"

PLACEHOLDER_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>eegvis — frontend not built</title>
  <style>
    body { font-family: system-ui, sans-serif; background:#0b0d12; color:#e6e9ef;
           margin:0; display:grid; place-items:center; height:100vh; }
    .card { max-width:640px; padding:2rem; line-height:1.6; }
    code { background:#1b1f2a; padding:.15em .4em; border-radius:4px; }
    h1 { font-size:1.4rem; } a { color:#7aa2f7; }
    .status { margin-top:1rem; font-size:.9rem; color:#9aa5b1; }
  </style>
</head>
<body>
  <div class="card">
    <h1>eegvis backend is running ✅</h1>
    <p>The browser frontend hasn't been built yet. To build it:</p>
    <pre><code>cd web
npm install
npm run build</code></pre>
    <p>…then reload this page. For live frontend development, run the Vite dev
    server instead (it proxies the WebSocket back here):</p>
    <pre><code>cd web
npm run dev</code></pre>
    <p class="status">The realtime stream is live at
    <code>ws://%(host)s:%(port)s/ws/eeg</code> and status at
    <a href="/api/status">/api/status</a>.</p>
  </div>
</body>
</html>
"""


def frontend_built() -> bool:
    return (WEB_DIST / "index.html").exists()


def placeholder_html(host: str, port: int) -> str:
    return PLACEHOLDER_HTML % {"host": host, "port": port}
