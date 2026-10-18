# GroveTheft — Mods

Drop mods here the same way you would into GTA V's own `mods/` folder.

A file in `mods/` that mirrors a `/data/` path is served **instead of** the base
game file, byte-range and all. So a replacement archive or loose file works
exactly like on a real install.

## Placement

Mirror the path the game requests (which is the path under `/data/`):

```
mods/
└── x64/
    ├── models/
    │   └── vehicles.rpf        ← replaces the base game's x64/models/... archive
    └── textures/
        └── skydome.ytd         ← a loose file override
```

The engine reads files by path (`-rootdir=/game/`), so any `mods/<relpath>`
file is picked up transparently when the game asks for `<relpath>`.

## What works

- **Replacements** — drop a modded `.rpf` / `.ydd` / `.ytd` / `.yft` under
  `mods/` at the same relative path as the vanilla file. The mod is streamed
  in place of the original.
- **Loose-file overrides** — single data files (scripts, data tables, textures)
  that the game loads by path.
- The mod folder is served from disk, so files are added/removed with a restart
  and no re-download.

Not supported (yet): injecting files that are *not* in the base manifest unless
the engine requests them by path (addon RPF mounts are typically path-driven).
A full `data_mirror/` (via `server.py --mirror-data` over a play-through) gives
the closest thing to a local install for mod tooling.