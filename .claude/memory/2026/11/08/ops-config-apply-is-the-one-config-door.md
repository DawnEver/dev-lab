---
name: ops-config-apply-is-the-one-config-door
description: After the lockdown a forge host's supervise.toml changes only through `ops config apply`; routine keys free, the boundary needs an ops.config consent credential.
metadata:
  type: project
---
# `ops config apply` is the one config door (2026-11-08)

- USER RULING 2026-11-08 ("go ahead"): after the lockdown only once-a-year events may need the user. The `ops`
  account cannot edit files, and today's forge-a1 upgrade needed exactly a config edit (#311 moved
  `[ops.breakglass]` keys), so a door is required, not wider sudo.
- `dev_lab.ops.configdoor`: `ROUTINE` is an ALLOWLIST of dotted key patterns; any other changed key is boundary and
  needs consent action `ops.config` (single, 15 min default, 1 h max) whose subject = SHA-256 of the candidate text.
  Why an allowlist: the config renders sudoers, unit users/interpreters and probe commands, so a free hand on it is
  root.
- Order inside the door: parse -> diff -> boundary/consent -> load by the CURRENT code -> backup `<file>.bak-<ts>`
  -> atomic replace -> `upgrade.checks` self-check -> restore on failure. Diff names keys, never values.
- NOT DONE: the reviewed SOURCE of each host's file. dev-lab is public, and a host file names site facts (domains,
  IPs, addresses), so it cannot live in dev-lab; it needs a private repo the user names. Until then the candidate
  comes from `--from <file>`. `opsserver` has no `config` verb yet.
- Granting it: add `<python> -m dev_lab.ops --config /etc/dev-lab/supervise.toml config apply *` to
  `[ops.access] commands` on each host in the last admin pass before the lockdown.
