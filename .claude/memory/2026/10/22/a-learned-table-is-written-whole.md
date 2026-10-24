---
name: a-learned-table-is-written-whole
description: compute.learned wrote its table in place, so a concurrent reader saw an empty file and a JSONDecodeError killed a motronics sweep; the table is now written via durable_write (per-thread temp, Windows rename retry) and an unreadable table reads as the prior after a short retry
created: 2026-10-22
---

# A learned table is written whole

Measured 2026-10-22 07:02 (motronics long run): `learned()` read `compute-learned/<hash>.json` while another
process's `_write` truncated and rewrote it in place; the reader got `''` -> `JSONDecodeError` raised through
`run_of` -> `box_demand` -> a JMAG read, and the sweep died. The file was valid seconds later.

- WRITER: `_write` now calls `dev._forge_journal.durable_write` (temp, fsync, rename) -- reused, not
  duplicated. `durable_write` itself was hardened: the temp name was `<name>.<pid>.tmp`, so two THREADS of
  one process (the box's station threads) shared one temp; it is now `<pid>.<thread id>`. A rename onto a
  file a Windows reader holds open raises `PermissionError`; it is retried for `REPLACE_RETRY_S` (2 s).
- READER: the table is ADVISORY. An unparseable/unreadable one is retried for `READ_RETRY_S` (0.5 s),
  then read as `{}` -- the caller's declared prior -- never raised through a run.
- Tests (`tests/test_compute_learned.py`): two writer threads vs a reader (red on the old code with the
  exact `Expecting value: line 1 column 1`), empty file -> `{}`/prior, emptied-then-restored is read
  whole on the retry, a held rename is retried and leaves no temp.

## Other in-place JSON writers found (not changed here)

Read concurrently, worth the same fix:
- `compute/presence.py:_save` -- temp+replace, but ONE shared temp name `<path>.tmp` (two writers collide)
  and no Windows retry; should call `durable_write`.
- `box/demand.py:write_ended` -- temp+replace, pid-only temp, no Windows retry (one writer per path: low).
- `dev/durations.py:328` -- read-merge-write in place; `dev/forgealarm.py:160` state in place;
  `hpc/__main__.py:_save_record` in place; `hpc/collect.py:117` in place.
Single-writer outputs (lower risk): `dev/unit_slices.py`, `dev/forgeunit.py` manifest, `dev/artefacts.py`,
`dev/artefactstores.py` manifests, `dev/agent_guard.py` settings, `hpc/pytest_item.py`.
