---
name: break-glass-records-the-key-and-locks-out-wrong-codes
description: The user's answers to the forge-host-roles PLAN's open questions -- no review before a break-glass merge, the connecting ssh key recorded, a persisted lockout after wrong codes, one TOTP secret per host.
corrects: PLAN-forge-host-roles-are-one-configured-mechanism
metadata:
  type: project
created: 2026-11-03
accessed: 2026-11-03
---

# Break-glass records the key and locks out wrong codes (user answers, 2026-11-03)

- No posted review before a break-glass merge: it exists for emergencies in which review cannot run; review-bot
  reviews the head after the merge.
- The connecting ssh key is recorded: the rendered sshd `Match` block sets `ExposeAuthInfo yes`, the sudoers line
  keeps `SSH_USER_AUTH`, and the role (`dev_lab.ops.sshkey`) writes the key's `SHA256:` fingerprint into each merge
  announcement, the wave record, every audit line and the wave report.
- Lockout (`dev_lab.ops.lockout`): `lockout_after` (default 5) consecutive wrong codes refuse every code for
  `lockout_minutes` (default 15); persisted in the role's state so a restart keeps it; a right code resets the count;
  while locked even a right code is refused; the lockout alerts once.
- One TOTP secret per host for now.
