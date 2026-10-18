# GroveTheft

**A fully self-contained, privacy-hardened, heavily optimized browser port of the RAGE engine — rebranded, stripped of all third-party adware/telemetry, and rebuilt around a local-first streaming architecture.**

> ⚠️ **Private research repository.** Contains proprietary engine binaries and game content mirrored for personal archival and optimization research. Not for redistribution. All trademarks belong to their respective owners.

---

## What is GroveTheft?

GroveTheft takes the community GTA V WebAssembly/WebGPU port and turns it into **its own thing**: a clean-room local server + hardened client bundle that you fully control. Every byte of engine code is mirrored locally, every ad network, analytics beacon, crash-report uploader, and tracking channel is **physically removed** (not blocked — deleted), and the entire delivery pipeline is rebuilt for speed, cache efficiency, and low-end hardware.

```
┌─────────────────────────────────────────────────────────────┐
│                    YOUR BROWSER                              │
│  index.html (cleaned, rebranded, zero third-party calls)     │
│   ├── loader.js ────── engine bootstrap + GPU/IO workers     │
│   ├── game.wasm ────── RAGE engine (Brotli + immutable cache)│
│   ├── wgpu_worker.js ─ WebGPU renderer (local shader packs)  │
│   └── io_worker.js ─── IndexedDB streaming + savegames       │
└──────────────────────────┬──────────────────────────────────┘
                           │  (localhost only)
┌──────────────────────────▼──────────────────────────────────┐
│              server.py — GroveTheft Host                     │
│  • Static: Brotli sidecars, immutable wasm caching           │
│  • mods/ tree: GTA-V-style file overrides (range-aware)      │
│  • /data/* range-proxy: chunked streaming, never buffered    │
│  • COOP/COEP isolation headers on every response             │
│  • 30s socket timeouts — hung streams can't wedge the server │
└─────────────────────────────────────────────────────────────┘
```

---

## Why GroveTheft is safer than the original site

| Threat | fiveplay.lol (original) | GroveTheft |
|---|---|---|
| Ad / malware networks | Loaded live | **Deleted from bundle** — cannot load |
| Telemetry & `/log` uploads | Active | **Disabled at the source** |
| Crash reports sent to 3rd party | Yes | Never |
| Third-party JS execution | Yes (ad scripts) | **Zero external scripts** |
| Supply-chain swaps | Server can swap binaries any time | Your `www/` is checksum-stable, you own it |
| Data exfiltration | Possible via embedded trackers | No outbound calls except game data you request |
| Browser isolation | Standard | **COOP `same-origin` + COEP `require-corp`** forced on every response |

Because the engine bundle is mirrored locally, the upstream can never silently swap in new code, inject ads, or rotate trackers under you. What you audited is what runs — permanently.

---

## Why it's more optimized

### 1. Brotli pre-compression (~83% smaller)
`compress.py` pre-builds `.br` sidecars for every compressible asset. The engine bundle drops from **134.8 MB → 23.3 MB**; the wasm alone goes **61 MB → 16 MB**. Static download time is cut ~5×.

### 2. Immutable wasm caching — near-zero reload compile
`game.wasm` is served with `Cache-Control: immutable`. Chrome caches **both the bytes and V8's compiled code** against the same cache key, so reloads skip the multi-second wasm compile almost entirely.

### 3. Automatic low-end hardware profile
No flags needed. Machines reporting ≤4 GB RAM or ≤4 cores automatically get:
- quality tier dropped to low
- engine thread count capped (the engine would otherwise spawn **80–116 threads** and thrash a small CPU)
- `?low=1` forces it, `?low=0` or `?quality=high` overrides

### 4. Chunked streaming proxy — flat memory footprint
`/data/*` requests are relayed in 64 KB chunks with byte-range passthrough. No full-archive buffering, so open-world streaming stays smooth even on modest machines.

### 5. Socket-level self-healing
Every connection gets a 30 s timeout, so a stalled upstream stream or a dead client can never wedge a worker thread permanently — the classic "site won't load" failure of naive proxies is structurally impossible here.

### 6. Hot-reload friendly static serving
HTML/JS are always served fresh (never stale `.br` sidecars), while wasm/shaders stay immutable-cached. Edit the client, refresh, play.

---

## Features

- 🎮 **Full Story Mode & Sandbox** (`?mode=story` / `?mode=sandbox&map=env_test`)
- 🗺️ **Multiple maps** — GTA V map, GTA VI-style map (key `5`/`6`)
- 🧩 **Mods folder** — drop replacement `.rpf`/`.yft`/`.ytd` under `mods/` mirroring the `/data/` path; they override base game files transparently, byte-range aware, exactly like a real GTA V install
- 💾 **Savegames** persisted in IndexedDB
- 🎯 **1:1 raw mouse input** — sub-pixel float accumulator, zero deadzone, no stair-stepping
- 🎮 **Native gamepad support**
- 🖥️ **Functional radar, full interiors**
- 🔇 **Zero ads, zero telemetry, zero third-party calls**

---

## Quick start

```bash
git clone <this-repo> GroveTheft && cd GroveTheft

# optional but recommended — build the Brotli sidecars (~5x smaller downloads)
pip install brotli
python3 compress.py

# serve
python3 server.py 9127

# open
xdg-open http://localhost:9127/
```

Or just run the launcher:

```bash
./start-grovetheft.sh        # starts server on :9127 (skips if already running)
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
| `?mode=story` | Story Mode |
| `?mode=sandbox&map=env_test` | Sandbox |
| `?low=1` / `?low=0` | force / forbid low-end profile |
| `?quality=high` | override quality tier |
| `?fps=30` / `?fps=0` | frame limiter (default 60) |
| `?newgame=1` | Story Mode from the Prologue |
| `?console=1` | every engine line in the browser console |

---

## Modding

See [`mods/README.md`](mods/README.md). Drop replacement files under `mods/` at the same relative path as the base game file and they're streamed in place of the original — hot-swappable, no re-download, no restart of the game client needed beyond a refresh.

---

## Offline play

Run once with `--mirror-data` and a full play-through will cache the content set to `data_mirror/`. After that the server serves everything from disk — no upstream needed at all.

---

## Requirements

- Python 3.8+ (stdlib only for the server; `brotli` optional for `compress.py`)
- A WebGPU-capable browser: Chrome/Brave/Edge 113+, or Firefox with WebGPU enabled
- ~2 GB free disk for the mirrored engine + first-play data cache
- Recommended: 8 GB RAM; low-end profile auto-engages below that

---

## Project structure

```
GroveTheft/
├── server.py            # the host: static+proxy+mods+isolation headers
├── compress.py          # Brotli sidecar builder
├── prefetch.py          # pre-warm the data cache
├── download_assets.py   # re-mirror the static engine bundle
├── start-grovetheft.sh  # one-shot launcher
├── www/                 # the client bundle (engine, workers, shaders, title)
└── mods/                # your mod overrides (GTA-V-style path mirroring)
```

---

## Disclaimer

This is a private research/archival project. Engine binaries and game content remain the property of their respective owners. Do not redistribute the repository contents. GroveTheft is not affiliated with, endorsed by, or connected to Rockstar Games or Take-Two Interactive in any way.

## License

Code authored for this project (server, tooling, optimizations): MIT. Bundled engine binaries and game content: **all rights reserved by their respective owners** — included for private research only.
