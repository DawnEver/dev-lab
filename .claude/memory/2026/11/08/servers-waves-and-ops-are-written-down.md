---
name: servers-waves-and-ops-are-written-down
description: "Where server facts live, how an agent logs in as ops with a user code, how a break-glass wave is opened and capped, the forge-a1 upgrade deadlock, the lockdown design, the Ada producer roles, and which toolchain repos merge on GitHub (2026-11-08)"
metadata:
  type: project
---

# Servers, waves and ops, written down (2026-11-08)

No codes, keys or secrets are recorded here.

## A. Where server facts live, and how to log in
- Every server fact lives in the user's `OneDrive .../Sync/ServerOperation/` (migration notes, CLAUDE.md). Read it
  first; write there only when the user asks.
- forge-a1 = 79.72.88.152 (Oracle London): Gitea, break-glass, supervise. Logins, as the user's `.bat` files:
  - `ssh-oracle-admin.bat`: `ubuntu@` -- passwordless sudo until the lockdown. An agent uses it ONLY for an admin
    pass the user approved, never for routine reads (a side agent flagged it 11-08: the plan meant to close it).
  - `ssh-oracle-ops.bat`: `ops@` -- key + TOTP; sudo is a fixed list (`systemctl status|restart|reload|daemon-reload`,
    `journalctl --no-pager`, `dev_lab.ops --config /etc/dev-lab/supervise.toml install|upgrade`).
- An agent answers the ops TOTP with a code the USER supplied, non-interactively: a throwaway askpass script that
  echoes the code, `SSH_ASKPASS=<script> SSH_ASKPASS_REQUIRE=force`, stdin from /dev/null. A code lives ~30 s and
  opens ONE session: batch every command for that session.
- ops and break-glass share ONE TOTP secret (verified by comparing fields on the host, never printing them).

## B. Break-glass waves (server still pre-#311)
- Open: one JSON line to `ssh -T breakglass@79.72.88.152`:
  `{"action": "open", "hours": 24, "max_merges": <n>, "code": "<user code>"}`. The dev-lab client after #311
  wants a consent credential the deployed server cannot issue yet, so the raw line is the working path.
- A wave is capped by MERGES as well as hours: default 20, ceiling `max_merges_max = 100`. Ask for the cap you need.
- An open but exhausted wave refuses a new open: `{"action": "close"}` first, then open within the code's window.
- Acknowledging a wave's audit is the USER's (`forge breakglass ack <id>`); the classifier refuses it for an agent.
- Merge (`forge pr breakglass N --reason ...`) only after the push is VERIFIED ("push OK") and the HEAD's
  tests/base, tests/base@windows, tests/security are all green. 11-08: lab-commons #136 merged at its OLD head
  because a refused push and the merge ran back to back; #140 repaired it.
- USER RULING 11-08 (#325): the user gives the code, the agent runs the command with it (CONSENT-CODE-FROM-THE-USER).

## C. forge-a1 upgrade deadlock (open)
- Server dev-lab 6b470cd9. `ops upgrade` with the old supervise.toml: the NEW code's self-check refuses it (#311 moved
  `totp`, `wave_hours`, `max_merges`, `lockout_*` out of `[ops.breakglass]`) and rolls back. With the new config: the
  OLD code refuses it (`Breakglass.__init__() missing ... 'totp'`). Fix = upgrade-on-read in the ops config loader
  (`pr/the-ops-config-upgrades-on-read`, FORMATS-UPGRADE-ON-READ). Then: upgrade with the old config, install the new
  one, `ops install`, check units.
- Migrated config: motronics `scratch/integrator-1108/forgea1-1108b/supervise.new.toml` (adds `[ops.consent]` reusing
  /etc/breakglass/totp, and `disk`/`clean` in `[ops.access]`). Server backup: `/etc/dev-lab/supervise.toml.bak-20261108`.
- The 11-08 "full in 2.5 days" alarm was FALSE (96 GB, 12% used): a 1 h slope projected 60x. Fixed by dev-lab #330.

## D. Lockdown (forge-a1, forge-amd1, forge-amd2) -- not yet
- Design (11-03/11-04): ops on all three (key + TOTP, one secret, fixed sudo); then remove linxu@G from root/ubuntu/opc,
  lock opc, revoke ubuntu NOPASSWD, user deletes the `/permissions` ssh rules.
- Precondition: every host upgraded and each verified by an ops login BEFORE locking, or the only way back is the
  Oracle console. Open contradiction: the notes also plan to disable Run Command, the console recovery path -- confirm
  the serial console first. Open hole: `journalctl --no-pager *` takes any flag (e.g. `--file`).

## E. Ada producers
- ezxmw9 and ezztz are BOTH `role = "verification"`; the role only decides serving (hpchost spec), not part class, so
  both serve PR parts. `[priority]` only orders (ezxmw9 wdg-lab first, ezztz motronics first).
- motronics PR base parts ask ~97 GB; starved alarms list only ezztz (0 free), so ezxmw9 is not a candidate --
  likely its memory declaration (unverified). Fix the declaration or the learned ask, not the role.
- Both accounts self-pull dev-lab integrate/main: a renamed module (hpchost -> hpcaccount, #313) breaks the cron tick
  until `hpcaccount deploy` runs on the account (hand-deployed 11-08; deploy-fleet refuses accounts without [deploy]).

## F. Toolchain repos
- dev-lab, lab-commons, ai-lab, numerics-lab, optimi-lab, learn-lab live on GitHub and merge by PR; only wdg-lab and
  motronics are on Gitea (user, 11-08).
- numerics-lab's checkout carried a hand-set `remote.origin.pushurl = DISABLED-...` from the private-history era;
  removed 11-08 (backup `.git/config.bak-20261108`). The `public-root` pre-push row is the guard.
- learn-lab: every test runs on GitHub Actions (no Ada/G serving). Its one CUDA-only test
  (`tests/unit/deep/test_artifact.py::test_a_fit_saved_on_cuda_loads_on_cuda_exactly_and_on_the_cpu_within_float32`)
  goes to `[tool.dev_lab.verify] allowed_skips`, reason "Actions runners have no GPU" (user ruling). It needs a
  relock onto dev-lab >= #320 (`forge pr continue`). Cloning it beside its siblings needs #329's sibling-clone admit
  in the SESSION's rendered guard (the motronics checkout).
