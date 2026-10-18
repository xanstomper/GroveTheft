#!/usr/bin/env python3
"""GroveTheft — prefetch game data into data_mirror/ so it serves from local disk.

The slowest load phase is "Loading audio metadata" (the engine reads the audio
archives' metadata one serial round-trip at a time from a throttled upstream).
Downloading those archives ahead of time into data_mirror/ makes the server
serve them from local disk — instant, no network.

Usage:
  python3 prefetch.py audio          # cache the audio set (~1.8 GB) — fixes the stall
  python3 prefetch.py bootset        # cache the boot set (LARGE, 13+ GB, only if disk allows)
  python3 prefetch.py all            # try to cache as much as fits
  python3 prefetch.py <file>...      # cache specific /data/ files

Ranges are fetched in parallel bands (resumable): interrupt anytime, re-run to
continue. Safe to run while the game is loading.
"""
import json, os, sys, urllib.request, urllib.error, time, re, threading, tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
MIRROR = os.path.join(ROOT, "data_mirror")   # must match DATA_MIRROR in server.py
UPSTREAM = "https://fiveplay.lol/data/"  # content origin — set to your mirror
XML = os.path.join(ROOT, "_manifest.json")    # cached manifest
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
BAND = 4 * 1048576        # fetch in 4 MB bands
PARALLEL = 8              # concurrent files
FETCHES = 32              # concurrent band fetches overall

def get_manifest():
    if os.path.isfile(XML):
        return json.load(open(XML))
    r = urllib.request.Request(UPSTREAM + "manifest.json", headers=UA)
    with urllib.request.urlopen(r, timeout=60) as resp:
        m = json.load(resp)
    open(XML, "w").write(json.dumps(m))
    return m

def select_files(args, manifest):
    files = manifest["files"]
    key = args[0] if args else "audio"
    if key == "all":
        return files
    if key == "audio":
        return [f for f in files if f[0].startswith("x64/audio/") and f[0].endswith(".rpf")]
    if key == "bootset":
        try:
            bs = json.load(urllib.request.urlopen(urllib.request.Request(UPSTREAM + "bootset.json", headers=UA), timeout=60))
            wanted = {f[0] for f in bs}
            return [f for f in files if f[0] in wanted]
        except Exception as e:
            sys.stderr.write("could not fetch bootset.json: %s\n" % e); return []
    # specific paths
    wanted = set(args)
    return [f for f in files if f[0] in wanted]

def fetch_band(dest, start, end, errors):
    """Download bytes [start,end] of a file via one Range request into a per-band
    temp file (resumable: re-running skips complete bands)."""
    bandtmp = dest + ".part%d" % start
    if os.path.isfile(bandtmp) and os.path.getsize(bandtmp) >= (end - start + 1):
        return True, bandtmp, start, end
    hdrs = dict(UA); hdrs["Range"] = "bytes=%d-%d" % (start, end)
    # data_mirror/x64/... -> x64/... (drop the cache-root prefix)
    rel = dest[len(MIRROR) + 1:]
    if os.sep != "/":
        rel = rel.replace(os.sep, "/")
    req = urllib.request.Request(UPSTREAM + rel, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            with open(bandtmp, "wb") as f:
                while True:
                    chunk = resp.read(BAND)
                    if not chunk:
                        break
                    f.write(chunk)
        return True, bandtmp, start, end
    except Exception as e:
        errors.append((dest, str(e)))
        return False, None, start, end

def cache_file(path, size):
    dest = os.path.join(MIRROR, path)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    # already fully cached?
    if os.path.isfile(dest) and os.path.getsize(dest) >= size:
        return "cached", size, 0
    bands = []
    n = size; s = 0
    while s < n:
        bands.append((s, min(s + BAND - 1, n - 1)))
        s += BAND
    fetch_dest = dest   # final target is under data_mirror
    results = [None] * len(bands)
    errors = []
    lock = threading.Lock(); idx = [0]
    def worker():
        while True:
            with lock:
                i = idx[0]; idx[0] += 1
            if i >= len(bands):
                return
            ok, tmp, st, en = fetch_band(fetch_dest, *bands[i], errors)
            if ok:
                results[i] = (tmp, st, en)
    ts = [threading.Thread(target=worker) for _ in range(min(PARALLEL, len(bands)))]
    for t in ts: t.start()
    for t in ts: t.join()
    if any(r is None for r in results):
        return "partial", 0, sum(len(o) for o in errors)
    # stitch bands in order into dest
    with open(dest, "wb") as out:
        tmp_paths = []
        for r in results:
            out.write(open(r[0], "rb").read()); tmp_paths.append(r[0])
        for t in tmp_paths:
            try: os.remove(t)
            except Exception: pass
    return "done", size, len(errors)

def main():
    args = sys.argv[1:]
    # --file <json> : read the list of /data/ paths to prefetch (space-safe for huge lists)
    listfile = None
    if "--file" in args:
        i = args.index("--file"); listfile = args[i+1]; args = args[:i]
    manifest = get_manifest()
    if listfile:
        paths = json.load(open(listfile))
        sel = [f for f in manifest["files"] if f[0] in set(paths)]
        print("prefetching %d files from %s, %.2f GB" % (len(sel), listfile, sum(f[1] for f in sel)/1073741824))
    else:
        sel = select_files(args, manifest)
        total = sum(f[1] for f in sel)
        print("prefetching %d files, %.2f GB" % (len(sel), total / 1073741824))
    total = sum(f[1] for f in sel)
    # free-disk guard
    import shutil
    free = shutil.disk_usage(MIRROR if os.path.exists(MIRROR) else ROOT).free
    print("free disk: %.2f GB" % (free / 1073741824))
    if total > free * 0.98:
        print("WARNING: selected set (%.2f GB) near/over free disk (%.2f GB); it may not all fit.\n"
              "Prefer 'audio' (~1.8 GB) which fixes the loading stall." % (total / 1073741824, free / 1073741824))
    # only files not already cached
    todo = [f for f in sel if not (os.path.isfile(os.path.join(MIRROR, f[0])) and os.path.getsize(os.path.join(MIRROR, f[0])) >= f[1])]
    print("to fetch: %d files (%.2f GB)" % (len(todo), sum(f[1] for f in todo) / 1073741824))
    t0 = time.time(); got = 0; reserve = 2 * 1073741824
    import shutil
    for i, entry in enumerate(todo, 1):
        path, size = entry[0], entry[1]
        # hard ceiling: keep a reserve of free disk so the server/OS never starve
        free_now = shutil.disk_usage(MIRROR if os.path.exists(MIRROR) else ROOT).free
        if free_now < reserve and size > 4 * 1048576:
            print("stopping early: free disk %.2f GB < %.2f GB reserve — cache is as full as is safe."
                  % (free_now / 1073741824, reserve / 1073741824))
            break
        status, n, errs = cache_file(path, size)
        got += n if status in ("done", "cached") else 0
        rate = got / max(1, time.time() - t0) / 1048576
        print("[%3d/%d] %-28s %6.1f MB  %s  (%d err)  %.1f MB/s"
              % (i, len(todo), path[:28], n / 1048576, status, errs, rate))
    print("done: %.2f GB cached in data_mirror/" % (got / 1073741824))

if __name__ == "__main__":
    main()