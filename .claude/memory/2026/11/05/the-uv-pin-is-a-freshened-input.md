---
name: the-uv-pin-is-a-freshened-input
description: dev-lab's uv pin moved from a Python constant to src/dev_lab/dev/uv.toml and joined FRESHENED; the forge relock raises it to the newest uv release tag, written by that uv.
metadata:
  type: project
created: 2026-11-05
---

# The uv pin is a FRESHENED input

User directive 2026-11-05: uv must be as new as possible. `lockcheck.UV_VERSION = '0.13.5'` was the one pinned
input outside the relock mechanism that already keeps `uv.lock` and `rust-toolchain.toml` at the newest.

- The pin now lives in ONE data file, `src/dev_lab/dev/uv.toml` (`version = "X.Y.Z"`), read by
  `lockcheck.uv_version(root)`: a program rewrites a data line (`pin_uv`) rather than Python source, and a
  dev-lab checkout's own pin is what its lock is written by. `UV_VERSION` is retired; callers moved.
- `newest_uv()` reads the highest `X.Y.Z` tag of `https://github.com/astral-sh/uv` by `git ls-remote --tags --refs`
  through `run_network_verb` (no API token, no rate limit; pre-release tags never match).
- `stale()` adds `src/dev_lab/dev/uv.toml is not the newest uv: A -> B` where the tree carries the pin;
  `FRESHENED` includes `UV_PIN`, so `refreshable()` accepts it and the relock branch is `pr/relock-uv-<sha>`.
- The door's `lock_upgrade` on a tree carrying the pin requires the NEWEST uv as the writer, then rewrites the pin;
  `carry` refuses first (`RelockFailed` naming `uv self update B`) when the host's uv is not B.
- Raised by hand 0.13.5 -> 0.13.7. No `uv.lock` was relocked here (the host's uv is being changed); the first
  relock after merge writes the lock with 0.13.7.
