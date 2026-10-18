# GroveTheft 🌴

**Play GTA V in your browser. Self-hosted, self-contained, zero ads, zero telemetry.**

A fully rebranded, privacy-hardened, heavily-optimized WebAssembly/WebGPU port of the RAGE engine — rebuilt around a local-first streaming architecture. Clone it, run one command, click play.

```bash
git clone https://github.com/xanstomper/GroveTheft.git && cd GroveTheft
python3 server.py 9127
# open http://localhost:9127 → START PLAYING
```

That's it. No pip installs, no build step, no configuration.

---

## 📖 How it works

GroveTheft is two pieces:

1. **The engine bundle** (in this repo, ~216 MB) — the RAGE engine compiled to WebAssembly, its WebGPU renderer, IO/audio workers, shader packs, and title screen. Everything runs **in your browser**, sandboxed by WebAssembly.
2. **The game content** (~21 GB: map, models, textures, audio, scripts) — **not bundled**. It streams on-demand over HTTP Range requests from a content origin, relayed through your local server, and cached to disk as you play.

```
┌──────────────────────────────────────────────────────────────┐
│                      YOUR BROWSER                            │
│  index.html (cleaned, rebranded, zero third-party calls)     │
│   ├── loader.js ────── engine bootstrap + GPU/IO workers     │
│   ├── game.wasm ────── RAGE engine (Brotli + immutable cache)│
│   ├── wgpu_worker.js ─ WebGPU renderer (local shader packs)  │
│   └── io_worker.js ─── IndexedDB streaming + savegames       │
└──────────────────────────┬───────────────────────────────────┘
                           │  (localhost only)
┌──────────────────────────▼───────────────────────────────────┐
│               server.py — GroveTheft Host                    │
│  • Static: Brotli sidecars, immutable wasm caching           │
│  • mods/ tree: GTA-V-style file overrides (range-aware)      │
│  • /data/* range-proxy: chunked streaming, never buffered    │
│  • Auto-cache: every streamed file saved to data_mirror/     │
│  • COOP/COEP isolation headers on every response             │
│  • 30s socket timeouts — hung streams can't wedge the server │
└──────────────────────────────────────────────────────────────┘
```

### The load sequence, step by step

1. **You click START PLAYING** → `loader.js` boots the wasm engine and spawns the GPU + IO workers.
2. **Boot set prefetch** (~540 MB, ~2,900 files) — shaders, metadata, core archives stream in parallel bands. With the Brotli sidecars and parallel fetching this takes ~2 minutes on a decent connection; on repeat loads it comes from `data_mirror/` instantly.
3. **Scene streaming** — as you walk/drive, the engine requests exactly the archives the current area needs (vehicles, peds, props, buildings). The server relays each request as chunked byte-ranges — no multi-GB downloads, ever.
4. **Everything is cached** — every streamed byte lands in `data_mirror/`. Play the same area again and it serves from local disk at memory speed. After a normal play session the game runs fully offline.

---

## 🛡️ Why it's safer than other web ports

| Threat | Typical web port | GroveTheft |
|---|---|---|
| Ad / malware networks | Loaded live | **Deleted from bundle** — cannot load |
| Telemetry & `/log` uploads | Active | **Disabled at the source** |
| Crash reports to 3rd party | Yes | Never |
| Third-party JS execution | Yes (ad scripts) | **Zero external scripts** |
| Supply-chain swaps | Server can swap binaries any time | Your `www/` is checksum-stable — what you audited is what runs |
| Data exfiltration | Possible via embedded trackers | No outbound calls except game data you request |
| Browser isolation | Standard | **COOP `same-origin` + COEP `require-corp`** forced on every response |
| Cookies / fingerprinting | Often | None — the server sets no cookies and logs nothing to disk |

Because the engine bundle is mirrored locally, the origin can never silently swap in new code, inject ads, or rotate trackers under you.

---

## ⚡ Why it's faster / more optimized

### 1. Brotli pre-compression (~82% smaller)
`compress.py` pre-builds `.br` sidecars for every compressible asset (they're **committed to this repo** — no setup step). Engine bundle: **136 MB → 24 MB**; the wasm alone: **61 MB → 16 MB**. Static download time cut ~5×.

### 2. Immutable wasm caching — near-zero reload compile
`game.wasm` is served with `Cache-Control: immutable`. Chrome caches both the bytes **and V8's compiled code** against the same cache key, so reloads skip the multi-second wasm compile almost entirely.

### 3. Automatic low-end hardware profile
No flags needed. Machines reporting ≤4 GB RAM or ≤4 cores automatically get the quality tier dropped and engine threads capped (the engine would otherwise spawn **80–116 threads** and thrash a small CPU). `?low=1` forces it; `?low=0` overrides.

### 4. Chunked streaming proxy — flat memory footprint
`/data/*` requests are relayed in 64 KB chunks with byte-range passthrough. No full-archive buffering, so open-world streaming stays smooth even on modest machines.

### 5. Socket-level self-healing
Every connection gets a 30 s timeout, so a stalled upstream stream or dead client can never wedge a worker thread — the classic "site won't load" failure of naive proxies is structurally impossible here.

### 6. Aggressive content caching + prefetch tooling
Played content is cached transparently; `prefetch.py` can pre-warm the audio set (fixes the "Loading audio metadata" stall) or the entire 21 GB content set for permanent offline play.

### 7. Hot-reload friendly static serving
HTML/JS are always served fresh (never stale `.br` sidecars); wasm/shaders stay immutable-cached. Edit the client, refresh, play.

---

## ✨ Features

- 🎮 **Full Story Mode & Sandbox** — `?mode=story` (Prologue & campaign) or `?mode=sandbox` (Los Santos free roam)
- 🌆 **Multiple maps** — GTA V map, GTA VI-style Vice City playground (`?mode=sandbox6`)
- 🧩 **GTA-V-style mods folder** — drop replacement `.rpf`/`.ytd`/`.yft` under `mods/` mirroring the `/data/` path; they override base game files transparently, byte-range aware — exactly like a real install
- 💾 **Savegames** persisted in IndexedDB
- 🎯 **1:1 raw mouse input** — sub-pixel float accumulator, zero deadzone, no stair-stepping
- 🎮 **Native gamepad support** — Xbox One / PS5 / PS4 / USB pads
- 🖥️ **Functional radar, full interiors, building interiors active**
- 🔒 **Locked 60 FPS target** with `?fps=` override
- 🔇 **Zero ads, zero telemetry, zero third-party calls**

---

## 🚀 Quick start

```bash
git clone https://github.com/xanstomper/GroveTheft.git && cd GroveTheft
python3 server.py 9127
```

Open **http://localhost:9127** in a WebGPU browser (Chrome/Edge/Brave 113+), pick a mode, click **START PLAYING**.

First load streams ~540 MB boot set from the origin and caches it. Second load is near-instant.

Or use the launcher (also enables transparent disk caching):

```bash
./start-grovetheft.sh        # server on :9127, skips if already running
```

### Server options

| Command | Effect |
|---|---|
| `python3 server.py 9127` | serve on port 9127 |
| `--host 0.0.0.0` | listen address (default: all interfaces) |
| `--mirror-data` | cache every `/data/*` file to `./data_mirror` for true offline play |

### Query-string flags

| Flag | Effect |
|---|---|
| `?mode=story` | Story Mode (Prologue & campaign) |
| `?mode=sandbox` | Sandbox — Los Santos free roam |
| `?low=1` / `?low=0` | force / forbid the low-end hardware profile |
| `?quality=high` | override quality tier |
| `?fps=30` / `?fps=0` | frame limiter (default 60, `0` = uncapped) |
| `?newgame=1` | Story Mode from the Prologue |
| `?console=1` | every engine line mirrored to the browser console (debugging) |
| `=` key | FPS counter overlay |

---

## 🧩 Modding

GroveTheft mods work like GTA V's own `mods/` folder — see [`mods/README.md`](mods/README.md) for the full guide.

```text
mods/
└── x64/
    ├── models/
    │   └── vehicles.rpf     ← replaces the base game's x64/models/vehicles.rpf
    └── textures/
        └── skydome.ytd      ← loose-file override
```

- Mirror the path the game requests (the path under `/data/`) and your file is streamed **instead of** the original — byte-ranges and all, so partial reads inside a modded archive work correctly.
- Hot-swappable: add/remove files and refresh the page. No re-download of the engine, no rebuild.
- The server checks `mods/` before `data_mirror/` and before the upstream — your mods always win.
- For mod tooling that needs a full local file tree, build a complete mirror once: `python3 prefetch.py all`.

---

## 💾 Offline play & content cache

```bash
python3 prefetch.py audio     # cache the audio set (~1.8 GB) — fixes the loading stall
python3 prefetch.py bootset   # cache the boot set (~540 MB)
python3 prefetch.py all       # mirror the complete content set (~21 GB)
python3 prefetch.py <file>... # cache specific /data/ files
```

`prefetch.py` fetches in resumable 4 MB bands with 32-way concurrency — interrupt it any time and re-run to continue. Or just play once with `--mirror-data`: everything you visit gets cached automatically.

After mirroring, the server serves everything from disk — zero upstream needed.

---

## 📦 Repo contents

```
GroveTheft/
├── server.py            # the host: static + range-proxy + mods + isolation headers
├── compress.py          # Brotli sidecar builder (sidecars are committed — no setup needed)
├── prefetch.py          # pre-warm the content cache (resumable, parallel)
├── download_assets.py   # re-mirror the static engine bundle from origin
├── start-grovetheft.sh  # one-shot launcher
├── www/                 # the client bundle: engine wasm, workers, shaders, title art
├── mods/                # your mod overrides (drop-in, path-mirrored)
└── data_mirror/         # (created at runtime) streamed-content cache
```

**Requirements:** Python 3.8+ (stdlib only) · a WebGPU browser (Chrome/Edge/Brave 113+) · ~2 GB disk for a typical cached session, ~21 GB for a full mirror · 8 GB RAM recommended (low-end profile auto-engages below that).

---

## 🤝 Contributing

Issues and PRs welcome — especially: low-end device benchmarks, shader pack tuning, mod compatibility reports, and UX improvements to the loader.

## ⚠️ Disclaimer

Engine binaries and game content remain the property of their respective owners. This project is not affiliated with, endorsed by, or connected to Rockstar Games or Take-Two Interactive. GroveTheft bundles no game assets — content is streamed from the origin by your own local server. Use at your own risk; the authors accept no liability for how you use it.

## 📄 License

Code authored for this project (server, tooling, optimizations): **MIT**. Bundled engine binaries: all rights reserved by their respective owners, included for personal research only.
