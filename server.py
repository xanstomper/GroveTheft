#!/usr/bin/env python3
"""
GroveTheft — optimized self-hosted port server.

Serves the mirrored static engine (www/) locally with the cross-origin
isolation headers (COOP/COEP) the wasm engine requires (SharedArrayBuffer /
threading), and relays /data/ game content (byte-range streamed, never
fully buffered) from the configured UPSTREAM origin.

  Local static  (mirrored) : /            -> www/
  Game content  (proxied)  : /data/*      -> UPSTREAM/data/*  (ranges, POST batch, cached batches)
  Shader fallback (proxied): /shaders/*   -> UPSTREAM/b/<build>/shaders/*  (individual files only,
                                             the mirrored packs cover the normal path)

Options:
  ./server.py PORT             serve on PORT (default 9127)
  ./server.py --mirror-data    also cache every /data/ file fetched into ./data_mirror
                               for true offline operation after the first full play-through
"""

import argparse, json, os, re, sys, threading, socket
import urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
WWW = os.path.join(ROOT, "www")
MODS = os.path.join(ROOT, "mods")            # GroveTheft mods/ folder (GTA V-style overrides)
DATA_MIRROR = os.path.join(ROOT, "data_mirror")

UPSTREAM = "https://fiveplay.lol"                  # content origin (game data + shader fallback)
DATA_UPSTREAM = UPSTREAM + "/data/"
SHADER_UPSTREAM = UPSTREAM + "/b/8b0b5899ed/shaders/"

# static asset MIME map
MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".wasm": "application/wasm",
    ".json": "application/json; charset=utf-8",
    ".wgsl": "text/plain; charset=utf-8",
    ".bin": "application/octet-stream",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".png": "image/png",
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}
def mime(p):
    return MIME.get(os.path.splitext(p)[1].lower(), "application/octet-stream")

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}

class FileLike:
    """Minimal read()-only wrapper so error bodies and streams look the same."""
    def __init__(self, data=b""):
        self._d = data
        self._i = 0
    def read(self, n=-1):
        if n is None or n < 0:
            n = len(self._d) - self._i
        b = self._d[self._i:self._i + n]
        self._i += len(b)
        return b

def stream_to(io, out):
    """Copy io -> out in chunks (no full buffering)."""
    while True:
        chunk = io.read(65536)
        if not chunk:
            break
        out.write(chunk)

MIRROR_LOCK = threading.Lock()

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        # GroveTheft: bound every recv/send so a hung upstream or a client that
        # stops reading can't wedge the whole server forever (a stalled proxy
        # stream would otherwise block a thread indefinitely and, under enough
        # of them, the listener stops accepting connections — the "site won't
        # load" failure). 30 s is far above any legit idle gap yet short enough
        # to self-heal.
        try:
            self.connection.settimeout(30)
        except Exception:
            pass

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionResetError, BrokenPipeError, TimeoutError):
            # client closed the idle keepalive connection / a curl smoke-test closed early
            pass
        except Exception:
            try:
                self.close_connection = True
            except Exception:
                pass

    def send_response(self, code, message=None):
        # Inject the cross-origin isolation headers right AFTER the status line
        # is queued (BaseHTTPRequestHandler buffers status + headers and writes
        # them all at once on end_headers; send_header must come after the status
        # line or the response is malformed).
        super().send_response(code, message)
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "cross-origin")

    def log_message(self, fmt, *args):
        # minimal logging
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def _proxy(self, url, headers=None, method=None, body=None):
        """Open upstream; returns (status, resp_headers_dict, fileobj). Caller
        streams fileobj.read(n) to the client — never buffers a whole archive."""
        hdrs = dict(UA)
        if headers:
            for k, v in headers.items():
                if k and k.lower() not in ("host", "connection", "content-length", "accept-encoding"):
                    hdrs[k] = v
        req = urllib.request.Request(url, headers=hdrs, method=method or "GET", data=body if body is not None else None)
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            return resp.status, dict(resp.headers), resp
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), FileLike(e.read())
        except Exception as e:
            return 502, {}, FileLike(b"proxy error: %s" % str(e).encode())

    # ---- static + proxy dispatch ----------------------------------------
    def _serve_static(self, path):
        rel = urllib.parse.unquote(path.lstrip("/"))
        # GroveTheft: the page references engine files under /b/<build>/... (the PHP
        # host's cache-busting prefix). On the local server the same files live in
        # www/, so strip the /b/<build id>/ prefix before the filesystem lookup.
        if rel.startswith("b/") and "/" in rel[2:]:
            rel = rel.split("/", 2)[2]
        if rel == "":
            rel = "index.html"
        target = os.path.normpath(os.path.join(WWW, rel))
        # path traversal guard
        if not target.startswith(WWW + os.sep) and target != WWW:
            self.send_error(403); return True
        if not os.path.isfile(target):
            return False
        ext = os.path.splitext(target)[1].lower()
        # Pre-compressed Fastly-style Brotli sidecar: serve <file>.br when the
        # client accepts br (build/compress.py). Immutable for wasm so Chrome
        # caches the *compiled* module across reloads — the big "recompile"
        # win plus ~82% download saving.
        accepts_br = "br" in (self.headers.get("Accept-Encoding") or "").split(",")
        brp = target + ".br"
        # Live hot reload: never serve stale .br sidecars for html and js
        use_br = ext not in (".html", ".js", ".mjs") and accepts_br and os.path.isfile(brp) and os.path.getmtime(brp) >= os.path.getmtime(target)
        data = open(brp, "rb").read() if use_br else open(target, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", mime(target))
        self.send_header("Content-Length", str(len(data)))
        if use_br:
            self.send_header("Content-Encoding", "br")
            self.send_header("Vary", "Accept-Encoding")
        if ext == ".wasm":
            # immutable: lets the browser cache both the bytes AND V8's compiled
            # code against the same cache key -> near-zero compile time on reload
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        elif ext in (".html", ".js", ".mjs"):
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        else:
            self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        if getattr(self, "_is_head", False):
            return True
        self.wfile.write(data)
        return True

    def _serve_mods_list(self):
        """Return the active GroveTheft mods (mods/ tree) as JSON. Reads the dir
        live so a mod dropped in shows up without a server restart."""
        out = []
        try:
            for dirpath, _, files in os.walk(MODS):
                for fn in files:
                    if fn == "README.md":
                        continue
                    full = os.path.join(dirpath, fn)
                    rel = os.path.relpath(full, MODS).replace(os.sep, "/")
                    out.append({"path": "/data/" + rel, "size": os.path.getsize(full)})
        except Exception:
            out = []
        out.sort(key=lambda m: m["path"])
        data = json.dumps({"mods": out, "count": len(out)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _serve_local(self, path):
        """Serve a local file (mod override or cached data) honouring Range, like the origin."""
        size = os.path.getsize(path)
        rng = self.headers.get("Range")
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m:
                s_str, e_str = m.group(1), m.group(2)
                if not s_str and e_str:
                    length = int(e_str)
                    start = max(0, size - length)
                    end = size - 1
                else:
                    start = int(s_str) if s_str else 0
                    end = int(e_str) if e_str else size - 1
                    end = min(end, size - 1)
            else:
                start, end = 0, size - 1
            if start >= size or start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                return
            length = max(0, end - start + 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Accept-Ranges", "bytes")
        else:
            start, end, length = 0, size - 1, size
            self.send_response(200)
            self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Type", mime(path))
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Expose-Headers", "Content-Range, Content-Length, Accept-Ranges, Content-Type")
        self.end_headers()
        if getattr(self, "_is_head", False):
            return
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (ConnectionResetError, BrokenPipeError):
                    break
                remaining -= len(chunk)

    def do_GET(self):
        p = self.path.split("?")[0]
        # 0. /mods : JSON list of active mods (real-time: reads the mods/ dir on demand)
        if p == "/mods" or p == "/mods/":
            return self._serve_mods_list()
        # 1. local static first
        if self._serve_static(p):
            return
        # 2. cached-batch GET (host's static copies of /data/batch) -> proxy
        if p.startswith("/data/batchc/"):
            url = DATA_UPSTREAM + "batchc/" + p[len("/data/batchc/"):] + ("?" + self.path.split("?")[1] if "?" in self.path else "")
            st, rheaders, body = self._proxy(url)
            self.send_response(st)
            self._send_rheaders(rheaders, body)
            return
        # 3. /data/ -> local mod / data_mirror / upstream
        if p.startswith("/data/"):
            # ---- GroveTheft mod support: mods/<path> overrides /data/<path> ----
            # Drop a replacement .rpf (or any game file) into mods/ mirroring its
            # /data/ path (e.g. mods/x64/models/vehicles.rpf) and it is served
            # instead of the base game file, exactly like GTA V's mods/ folder.
            rel = urllib.parse.unquote(p[len("/data/"):].split("?")[0])
            modpath = os.path.normpath(os.path.join(MODS, rel))
            if os.path.isfile(modpath):
                self._serve_local(modpath)
                return
            # ---- GroveTheft local cache: a fully-cached /data file serves from
            # disk (instant) instead of the throttled upstream.
            cachepath = os.path.normpath(os.path.join(DATA_MIRROR, rel))
            if os.path.isfile(cachepath):
                self._serve_local(cachepath)
                return
            url = DATA_UPSTREAM + self.path[len("/data/"):]
            rng = self.headers.get("Range")
            hdrs = {"Range": rng} if rng else {}
            st, rheaders, body = self._proxy(url, headers=hdrs)
            if self.server.mirror_data and st in (200, 206):
                cached = self._mirror(p, body, rheaders, rng)
                if cached is not None:
                    body = FileLike(cached)   # re-serve the newly cached copy
            self.send_response(st)
            self._send_rheaders(rheaders, body)
            return
        # 4. individual shader fallback -> upstream shaders
        if p.startswith("/shaders/"):
            url = SHADER_UPSTREAM + self.path[len("/shaders/"):]
            st, rheaders, body = self._proxy(url)
            self.send_response(st)
            self._send_rheaders(rheaders, body)
            return
        self.send_error(404)

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        if p == "/log":
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            txt = body.decode("utf-8", errors="replace")
            with open(os.path.join(ROOT, "engine_session.log"), "a", encoding="utf-8") as f:
                f.write(txt)
            print("[LOG]", txt.strip(), flush=True)
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        # /data/batch : compressed batch request -> relay POST upstream
        if p.startswith("/data/batch"):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            url = DATA_UPSTREAM + "batch" + ("?" + self.path.split("?")[1] if "?" in self.path else "")
            st, rheaders, rbody = self._proxy(url, method="POST", body=body,
                                             headers={"Content-Type": self.headers.get("Content-Type", "application/octet-stream")})
            self.send_response(st)
            self._send_rheaders(rheaders, rbody)
            return
        self.send_error(404)

    def do_HEAD(self):
        self._is_head = True
        try:
            self.do_GET()
        finally:
            self._is_head = False

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD")
        self.send_header("Access-Control-Allow-Headers", "Range, Content-Type, Authorization, X-Requested-With")
        self.send_header("Access-Control-Expose-Headers", "Content-Range, Content-Length, Accept-Ranges, X-Run-Lengths")
        self.end_headers()

    # ---- helpers ---------------------------------------------------------
    def _mirror(self, p, body, rheaders, rng):
        # Consume a proxied body into a cached copy (data_mirror tree) when it is
        # a whole-file GET (not a range) and mirroring is enabled. Returns the
        # buffered bytes so the caller can re-serve them, or None if not cached.
        try:
            if rng or not self.server.mirror_data or p == "/data/batch":
                return None
            data = body.read()
            dest = os.path.join(DATA_MIRROR, p[len("/data/"):].split("?")[0])
            with MIRROR_LOCK:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                open(dest, "wb").write(data)
            return data
        except Exception:
            return None

    def _send_rheaders(self, rheaders, io):
        # copy proxied content headers, drop hop-by-hop, then stream the body
        hop = {"connection", "keep-alive", "transfer-encoding", "upgrade",
               "proxy-authenticate", "proxy-authorization", "te", "trailer"}
        ct = rheaders.get("Content-Type") or rheaders.get("content-type")
        cl = rheaders.get("Content-Length") or rheaders.get("content-length")
        cr = rheaders.get("Content-Range") or rheaders.get("content-range")
        accr = rheaders.get("Accept-Ranges") or rheaders.get("accept-ranges")
        if ct: self.send_header("Content-Type", ct)
        if cl:
            self.send_header("Content-Length", cl)
        else:
            # no known length: stream then close (delimits on EOF)
            self.close_connection = True
        if cr: self.send_header("Content-Range", cr)
        if accr: self.send_header("Accept-Ranges", accr)
        for k, v in rheaders.items():
            if k.lower() in hop or not k:
                continue
            if k.lower() in ("content-length", "content-range", "accept-ranges", "content-type"):
                continue
            self.send_header(k, v)
        self.end_headers()
        if getattr(self, "_is_head", False):
            return
        try:
            stream_to(io, self.wfile)
        except (ConnectionResetError, BrokenPipeError, TimeoutError, socket.timeout):
            # client went away or the stream stalled against the timeout — close
            # cleanly; a stalled proxy stream must NOT wedge the server thread
            pass
        finally:
            # CRITICAL: close the upstream response so its socket is released.
            # Not closing it leaks a connection per request; with the io_worker's
            # many concurrent lanes (RUN_LANES=96) sockets accumulate until the
            # FD limit is hit and every new fetch hangs -> the "stuck loading"
            # deadlock. urllib only frees the socket on close(), not on GC.
            try:
                if hasattr(io, "close"):
                    io.close()
            except Exception:
                pass

def main():
    ap = argparse.ArgumentParser(description="GroveTheft RAGE port server")
    ap.add_argument("port", nargs="?", type=int, default=9127, help="port to serve on")
    ap.add_argument("--mirror-data", action="store_true", help="cache /data files locally for offline")
    ap.add_argument("--host", default="0.0.0.0")
    a = ap.parse_args()

    os.makedirs(WWW, exist_ok=True)
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.mirror_data = a.mirror_data
    print("=" * 62)
    print("GroveTheft RAGE engine — optimized local port")
    print("  local  : http://localhost:%d/  (static mirrored + Brotli-compressed)" % a.port)
    print("  LAN    : http://%s:%d/" % (a.host, a.port))
    print("  data   : /data/* streamed -> %s  (chunked range proxy)" % DATA_UPSTREAM)
    print("  mods   : %s  (GTA V-style overrides; see mods/README.md)" % MODS)
    print("  COOP/COEP isolation: ON   adware/telemetry: REMOVED")
    if a.mirror_data:
        print("  data mirror: caching to %s for offline" % DATA_MIRROR)
    print("=" * 62)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")

if __name__ == "__main__":
    main()