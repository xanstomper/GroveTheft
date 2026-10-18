#!/usr/bin/env python3
"""Mirror the static engine + shader + title assets of the upstream origin into ./www local tree.

Downloads every file the RAGE browser build needs statically (engine JS/wasm, workers,
shaders incl. packs, title art). The dynamic /data/ (GTA V archives, ~1.2 GB) is handled
by the server's range proxy, NOT mirrored here (see server.py --mirror-data).
"""
import json, os, sys, urllib.request, concurrent.futures, time

ORIGIN = "https://fiveplay.lol"
BUILD = "/b/8b0b5899ed"
BASE = ORIGIN + BUILD
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "www")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}

# Static engine boot files (paths relative to BUILD)
BOOT = [
    "loader.js",
    "game.js",
    "game.wasm",
    "wgpu_worker.js",
    "io_worker.js",
    "audio-worklet.js",
    "shaders/pipelines.json",
]

def fetch(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return "skip"
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            with open(dest, "wb") as f:
                f.write(data)
            return f"ok:{len(data)}"
        except Exception as e:
            if attempt == 3:
                return f"ERR:{e}"
            time.sleep(1.5 * (attempt + 1))

def main():
    os.makedirs(OUT, exist_ok=True)
    tasks = []

    # 1. boot files
    for p in BOOT:
        rel = p
        tasks.append((BASE + "/" + p, os.path.join(OUT, rel)))

    # 2. title art
    tasks.append((BASE + "/title/chalet.woff", os.path.join(OUT, "title/chalet.woff")))
    tasks.append((BASE + "/title/logo.png", os.path.join(OUT, "title/logo.png")))
    tasks.append((BASE + "/title/spinner.png", os.path.join(OUT, "title/spinner.png")))
    import re
    html = open(os.path.join(OUT, "index.html"), "rb").read().decode("utf-8", "replace") if os.path.exists(os.path.join(OUT, "index.html")) else ""
    art_names = set(re.findall(r"art/ls([0-9]+)_([a-z0-9_]+)\.webp", open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")).read()))
    if not art_names:
        # fallback known set
        art_names = {(n, n2) for n in range(17) for n2 in ["background", "foreground", "foreground_franklin", "foreground_chop", "foreground_michael", "foreground_car"]}
    for n, name in art_names:
        tasks.append((f"{BASE}/title/art/ls{n}_{name}.webp", os.path.join(OUT, f"title/art/ls{n}_{name}.webp")))

    # 3. shaders: index + packs (packs cover all shaders). Individual files fetched later on demand by server proxy.
    si_dest = os.path.join(OUT, "shaders/index.json")
    fetch(BASE + "/shaders/index.json", si_dest)
    try:
        idx = json.load(open(si_dest))
    except Exception as e:
        print("WARN: shader index parse failed:", e); idx = {}
    packs = idx.get("_packs", [])
    print(f"shader index: {len([k for k in idx if '.' not in k])} shaders, {len(packs)} packs")
    for p in packs:
        tasks.append((BASE + "/shaders/" + p["file"], os.path.join(OUT, "shaders", p["file"])))

    # download concurrently
    counter = [0]
    def work(t):
        r = fetch(*t)
        counter[0] += 1
        return counter[0], t[1], r
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        for i, (n, dest, res) in enumerate(ex.map(work, tasks), 1):
            print(f"[{i}/{len(tasks)}] {res:>12}  {dest.replace(OUT,'.')}")

    # report
    total = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT) if os.path.isfile(os.path.join(OUT, f)))
    sizes = {}
    for root, _, files in os.walk(OUT):
        for f in files:
            p = os.path.join(root, f)
            top = os.path.relpath(root, OUT).split(os.sep)[0]
            sizes[top] = sizes.get(top, 0) + os.path.getsize(p)
    print("\n== Summary ==")
    for k, v in sorted(sizes.items(), key=lambda x: -x[1]):
        print(f"  {k:15} {v/1048576:8.2f} MB")
    print(f"  TOTAL local static: {sum(sizes.values())/1048576:.2f} MB")

if __name__ == "__main__":
    main()