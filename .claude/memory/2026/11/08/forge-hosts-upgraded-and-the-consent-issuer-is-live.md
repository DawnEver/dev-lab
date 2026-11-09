---
name: forge-hosts-upgraded-and-the-consent-issuer-is-live
description: "forge-a1 and AMD-2 upgraded and installed, the consent issuer deployed on forge-a1, the login scripts and passwords in place; AMD-1, the AMD-2 logrotate file and the lockdown still open (2026-11-08 evening)"
metadata:
  type: project
---

> Redacted 2026-11-09: site markers removed (public repo).

# Forge hosts upgraded; the consent issuer is live (2026-11-08 evening)

Follows `servers-waves-and-ops-are-written-down.md`. No secrets recorded.

## Access facts
- AMD-1 (forge-amd1) has no public IP: private `<ip>`, reachable only by a jump through AMD-2
  (`<ip>`). forge-a1 is `<ip>`.
- <private-ops-notes> holds six login scripts: `ssh-forge-{a1,amd2,amd1}-{admin,ops}.bat`. The admin ones use
  `ubuntu@` and stop working after the lockdown; the ops ones ask one code per hop.
- `ops` needs NO password: key + TOTP through PAM keyboard-interactive. A password on ops may change what
  PAM prompts for, so none is set.
- The user set `ubuntu` (and `root`) passwords on all three hosts: the sudo password after the lockdown
  removes NOPASSWD, and the serial-console login when ssh fails.
- An agent answers the ops TOTP with a user-supplied code via `SSH_ASKPASS` + `SSH_ASKPASS_REQUIRE=force`.

## forge-a1
- dev-lab upgraded `6b470cd9` -> `49bf43b1`, possible only after #333 (the config upgrades the pre-#311
  `[ops.breakglass]` shape on read). Then the new `supervise.toml` was installed (backup
  `/etc/dev-lab/supervise.toml.bak-20261108`).
- `ops install` WRITES its files and then prints `next, on the live host:` -- steps root must run (useradd,
  visudo -cf, sshd -t + reload, enable timers, consent keygen). All 20 ran; no failed units.
- The consent issuer is deployed: account `consent`, signing key under `/etc/dev-lab/consent/`. the integrator workstation's machine
  file declares `[consent]` (endpoint `consent@<ip>` + the public key; backup
  `the private consumer.toml.bak-20261108-consent`).

## AMD-2 and AMD-1
- AMD-2 upgraded `34b7099a` -> `83c4f298` (its `[ops.upgrade] ref` is `main`), install + live-host steps run.
- AMD-2 `/etc/logrotate.d/forge-probe` is written on ONE line, which logrotate cannot parse, so log
  rotation fails every night. The hand fix was refused by the classifier; the right fix is to render that
  file from `dev_lab.ops install` so it has one source.
- AMD-1 is NOT upgraded yet, and `dev-lab-ops-judge.service` is failed (cause unread).

## Open
- The classifier refuses remote writes over `ubuntu@` sudo without a user permission rule.
- dev-lab #334 (`ops config apply`, boundary changes need an `ops.config` consent credential) is open.
- The private repo for host configs (dev-lab is public) is the user's to name.
- Then: add `config apply` to ops' sudo list on all three, verify each as ops, lock down.
