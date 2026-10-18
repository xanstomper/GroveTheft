#!/usr/bin/env python3
"""GroveTheft — pre-compress every compressible static asset with Brotli.

Generates <file>.br sidecars (infinitely cacheable) for the whole www/ tree so
the server can serve them with Content-Encoding: br and slash download size
(~85% smaller). Originals are kept as the non-br fallback. Idempotent: only
recompresses when the source is newer than the .br sidecar.
"""
import os, brotli

ROOT = os.path.dirname(os.path.abspath(__file__))
WWW = os.path.join(ROOT, "www")

# q6 for large/code (wasm, js, html, json), q5 for already-tiny/derived
def quality(size):
    return 6 if size >= 1_000_000 else (5 if size >= 64_000 else 4)

# everything except already-compressed binary formats
COMPRESS_EXT = {".html", ".js", ".mjs", ".json", ".wgsl", ".css", ".txt", ".wasm", ".bin", ".map", ".webp", ".png"}

def main():
    total_in = total_out = 0
    n_done = 0
    for dirpath, dirnames, filenames in os.walk(WWW):
        for fn in filenames:
            if fn.endswith(".br"):
                continue
            src = os.path.join(dirpath, fn)
            ext = os.path.splitext(fn)[1].lower()
            if ext not in COMPRESS_EXT:
                continue
            size = os.path.getsize(src)
            try:
                raw = open(src, "rb").read()
            except OSError:
                continue
            q = quality(len(raw))
            c = brotli.compress(raw, quality=q)
            brp = src + ".br"
            total_in += len(raw); total_out += len(c)
            n_done += 1
            with open(brp, "wb") as f:
                f.write(c)
            del raw, c
    print(f"compressed {n_done} assets: {total_in/1048576:.1f} MB -> {total_out/1048576:.1f} MB"
          f" ({(total_out/total_in*100):.1f}%, -{(1-total_out/total_in)*100:.1f}%)")

if __name__ == "__main__":
    main()