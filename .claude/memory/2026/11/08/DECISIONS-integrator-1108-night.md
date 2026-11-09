---
name: DECISIONS-integrator-1108-night
description: Integrator decisions of the 2026-11-08 night under the user's full-day autonomy grant -- forge hosts, forge-hosts repo, lockdown held, mistakes on record.
metadata:
  type: project
---

> Redacted 2026-11-09: site markers removed (public repo).
# Integrator decisions, 2026-11-08 night (user away; full autonomy; reviewed afterwards)

Follows `forge-hosts-upgraded-and-the-consent-issuer-is-live.md`. No secrets here.

| # | decision | the rule that decided it |
|---|---|---|
| a | All three forge hosts (forge-a1, AMD-1, AMD-2) track `integrate/main`, one code everywhere. The 11-06 user ruling recorded at `src/dev_lab/ops/config.py:115` ("every repo tracks integrate/main; nothing waits for a promotion") wins. My contrary "track main" answer was WRONG; dev-lab `main` was promoted to ffdd3116 anyway. | user ruling over my advice; single source of truth (one ref for all hosts) |
| b | Host configs live in Gitea `<org>/forge-hosts` (private), read over HTTPS with a per-host read-only token file `/etc/dev-lab/forge-hosts/token` (option B). Gitea SSH stays disabled (`DISABLE_SSH = true`); the deploy keys made first were removed. First commits 80d3222 and b2acb3c went straight to `main` (empty repo, user away); the user reviews them afterwards. | user choice B; least exposure (no new port) |
| c | The reader account shows `push: true` on forge-hosts. A read-only token scope still cannot push, but the account should be Read -- the user's to set. | least privilege |
| d | The hand-written `/opt/dev-lab/overrides.txt` (lab-commons 01c8fb8) is retired: `ops upgrade` installs the family revisions dev-lab's own lock pins (#337). A judge host now also installs its reviewer ai-lab at the locked revision (`pr/a-judge-host-installs-its-reviewer`, ef87f04b) -- AMD-1 had kept ai-lab 76b45b6 because its `[ops.upgrade]` named no packages. `python3.12-venv` installed on AMD-1 (the review runtime's `venv` exited 1 with its message on stdout). | single source of truth; fix the cause |
| e | AMD-2 `/etc/logrotate.d/forge-probe` was one invalid line, so logrotate failed nightly; rewritten as a proper block (backup `/root/forge-probe.logrotate.bak-20261108`). Owed: render it from `dev_lab.ops install` so it has one home. | fix the cause |
| f | The lockdown script `/root/tighten-20261108.sh` is installed on all three hosts (root 700, syntax-checked) and NOT run. It removes <user>@G from root/opc/ubuntu, ubuntu's NOPASSWD, locks opc, with `visudo -c` + `sshd -t` and restore on failure. It waits for the user's code to re-verify `ops` first: recoverability before tightening. The user set ubuntu/root passwords on all three (sudo after lockdown; serial console). | recoverability first |
| g | `ops config apply` (#334, #336) reads each host's file from forge-hosts; run on all three it reported `unchanged`. | the door is verified before it is relied on |
| h | AMD-1 judge: `judged` on dev-lab, ai-lab, lab-commons, numerics-lab after ai-lab moved to the locked 86935099; the two Anthropic pr-review keys still listed by `ai_lab.auth status`. | -- |

## Mistakes on record

- lab-commons #136 merged at its OLD head: its push was refused and the merge ran unchecked (repaired by #140). Rule since: a merge follows only a VERIFIED push.
- I said <hpc-account> is "verification, so it takes no PR parts"; both Ada accounts are `role = "verification"` and the role only decides serve-or-not.
- I advised "servers track main" against the recorded 11-06 ruling (item a).

## Lockdown done (2026-11-09 early)
- ops verified by the integrator on forge-a1, forge-amd2, forge-amd1 (key + user-supplied code; one code served both
  AMD-1 hops: the shared TOTP is replay-checked per host). sudo list holds config apply, disk *, clean *, install, upgrade.
- The classifier refused the agent running /root/tighten-20261108.sh; the USER ran it on all three (AMD-1 first) and
  confirmed ops logins. Probe after: `ubuntu@` key login is refused (publickey) on forge-a1 and AMD-2.
- From now on: ops + a user code for maintenance; config changes via forge-hosts + `ops config apply`; the serial
  console with the ubuntu password is the recovery path. The two `/permissions` ssh rules are the user's to remove.
- Small follow-up: `disk *` / `clean *` sudo rules do not match the bare verb (no arguments); opsserver always
  passes arguments, so maintenance is unaffected.
