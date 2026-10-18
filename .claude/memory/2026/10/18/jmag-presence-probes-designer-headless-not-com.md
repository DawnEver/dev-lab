---
created: 2026-10-18
accessed: 2026-10-18
---
# JMAG presence probes Designer headless (`designer.exe -w`), not COM

## Defect

<consumer> Lane 11, host G (this Windows box, JMAG 25.2.01zp): the jmag smoke ran
`import win32com.client; Dispatch('scheduler.JobApplication')` in `sys.executable` -- the lab-commons
venv, which declares no `pywin32`. `ModuleNotFoundError: win32com` -> smoke FAILED -> `Engine.vendor('jmag',
cached())` raised EngineAbsent, so `--where` could never choose jmag. The probe tested OUR interpreter,
not the tool, and a route (COM Scheduler) the work no longer uses (<consumer> runs JMAG as a file bundle).

## Fix (`compute/toolchecks.py`)

- `jmag_headless(path)`: `designer.exe -w -l <log> smoke.py` in a temp dir; the script runs in Designer's
  own python3.12 and writes `designer.GetApplication().VersionString(True)` to `version.txt`. The FILE is
  the verdict: Designer exits 0 even when its script raised.
- `jmag_version` reads that version (`designer -w` source); `jmag_smoke` reuses the same reading
  (`_JMAG_READ`, popped), so one probe = one Designer start (~5 s). On no file the version falls back to
  the exe's file version so the smoke records the reason (`...; the script wrote no version file`).
- COM registry is still read, only to FIND `designer.exe`; nothing dispatches. `JMAG_SCHEDULER` removed.
- Measured API (25.2.01zp): `VersionString(True)` -> `'25.2.01zp'`, `(False)` -> `'25.2zp'`;
  `MajorVersion/MinorVersion/SubVersion` -> 25/2/1.

## Tests (`tests/test_compute_presence.py`)

Fake designer executes the generated script against a fake in-process `designer` module: present at
`25.2.01zp` over floor 25.2 with ONE start (planted control); a designer that exits 0 without writing ->
absent, smoke `FAILED: exit 0: ...; the script wrote no version file`.

## Live, this box, 2026-10-18

`probe('jmag', CHECKS['jmag'], Requirement('25.2', ...))` -> present, version `25.2.01zp`;
find registry `C:\Program Files\JMAG-Designer25.2\designer.exe`; smoke `passed: exit 0: Runing script;
wrote version 25.2.01zp`; wall 5.0 s.
