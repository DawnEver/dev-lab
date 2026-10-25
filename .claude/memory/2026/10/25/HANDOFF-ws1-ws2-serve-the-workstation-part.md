---
name: HANDOFF-ws1-ws2-serve-the-workstation-part
description: For the agent on WS1 (DUIPEZZTZ) and WS2 (DUIP622037) -- deploy forge serve offering ONLY the workstation part, so the fleet stops waiting on G alone; JMAG stays out until lab-commons #414 lands
created: 2026-10-25
---

# HANDOFF: WS1 and WS2 serve the workstation part (2026-10-25)

## Why

- Measured 2026-10-25 ~13:10Z: G is the only workstation host. One wdg-lab part held its serve and 13 dev-lab
  PRs read `no host provides workstation`; G showed STALE. dev-lab #135 fixes the lanes, but more hosts is the cure.
- User ruling 2026-10-25: WS1 and WS2 serve the WORKSTATION part only, now. JMAG is NOT offered yet: it waits
  for lab-commons #414 (seats measured; people declare their use with `box claim`) and dev-lab #136.
- The registry already carries the role: `hosts.json` (synced folder `Sync/workstation/jmag-job-system/`) has
  `"forge"` on WS1 and WS2 (WS1 added 2026-10-25 by the integrator).

## Before you start (on the box, logged on as the person who serves)

1. Disk: WS2 alarmed at 843/944 GB on 2026-10-16. Each claimed part makes a worktree and a venv under the
   repo checkouts. Free space first; report what you removed (never delete another person's work or `attic/`).
2. Tools on PATH: `git`, `uv`, and whatever the `workstation` capability probes for (at least `node` and
   `codex` per review SR-20261025-003). Trust the deploy, not this list: its dry run refuses every missing
   tool together, each with its remedy -- install those and re-run.
3. A forge credential for this user: `git clone https://gitea.mingyangbao.site/Tianjie-Zou-Team/dev-lab.git`
   somewhere and sign in (Git Credential Manager stores it). On a fresh box dev_lab is not installed yet, so
   do NOT use a bare `python -m dev_lab...`; after the deploy, use `$HOME\src\dev-lab\.venv\Scripts\python.exe`.
   Never print the token.
4. The machine file (`$env:LAB_COMMONS_CONFIG` if set, else `~/.config/lab-commons/config.toml`):
   - must name the registry: `[workstation]` `registry = "<this box's path to>/Sync/workstation/jmag-job-system/hosts.json"`;
   - must NOT still declare `[capabilities.jmag]` (WS2 declared `jmag = 4` before): the deploy only MERGES the
     tables you pass and keeps the rest, so an old `[capabilities.jmag]` keeps offering JMAG. Delete that table
     by hand now (keep a copy of the file first); it comes back with the JMAG deploy later.

## Deploy (PowerShell)

```powershell
$forge = "https://gitea.mingyangbao.site/Tianjie-Zou-Team"
uv run --no-project --with "dev-lab @ git+$forge/dev-lab.git@integrate/main" -- `
  python -m dev_lab.dev.workstation deploy --forge $forge `
  --repos dev-lab,lab-commons,numerics-lab,optimi-lab,ai-lab,wdg-lab,motronics-studio `
  --capabilities workstation --dry-run
```

Read the dry run (every action and the machine-file diff), then run the same line WITHOUT `--dry-run`.
Do NOT pass `jmag` yet. The deploy clones/fast-forwards each repo under `~/src`, bootstraps each `.venv`,
installs hooks, merges `[capabilities.workstation]` and `[serve]` into the machine file, and writes the one
Scheduled Task `lab-forge-serve` (every 5 min, only while logged on, windowless).

## Verify

- `Get-Content $env:LOCALAPPDATA\lab-forge\serve.log -Tail 40` shows a serve tick, not `not a forge host`.
- From any dev-lab checkout: `.venv\Scripts\python.exe -m dev_lab.dev.forge queue` lists this host (WS1/WS2) with
  `workstation=1` in its supply and a fresh `ticked` time; the `no host provides workstation` lines go away.
- Report back: host, deploy output summary, first claimed part (sha:part), disk free before/after.

## Stop

1. `schtasks /Change /TN lab-forge-serve /DISABLE` -- stops new ticks; it does not kill a running one.
2. Find the running FORGE serve (not the Task's `pythonw -m dev_lab.dev.workstation serve` parent -- stoprun
   refuses that pid with exit 3): `Get-CimInstance Win32_Process | ? CommandLine -match 'dev_lab.dev.forge serve' | select ProcessId,CommandLine`.
3. `$HOME\src\dev-lab\.venv\Scripts\python.exe -m dev_lab.dev.stoprun --pid <that pid>` for each: its producers
   stop first and its claim is released as `error: stopped`; the workstation parent then exits by itself.

## Later (not now)

- After lab-commons #414 and dev-lab #136 land and dev-lab relocks: re-run the deploy with
  `--capabilities workstation,jmag:<seats>` (WS1/WS2 have several solve seats each). No fixed margin: people
  declare JMAG work with `<dev-lab .venv python> -m lab_commons.box claim --seat jmag=<k> --cpu <n> --mem-gb <g> --wall <h> --why "<text>"`
  and the forge only uses what lies outside every declared claim; observed solver processes still count.
