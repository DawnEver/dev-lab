---
name: ada-compute-nodes-have-outbound-https
description: Measured 2026-11-27: Ada compute nodes reach the internet over HTTPS; user rulings on login-node polling and ssh reach
created: 2026-11-27
---

# Ada compute nodes have outbound HTTPS; login-node polling and ssh reach (2026-11-27)

## Measured fact (2026-11-27)

- Ada compute nodes have outbound HTTPS.
- Job 8516573 ran on comp007 (partition `shortq`) and got HTTP 200 from https://pypi.org/simple/,
  https://github.com and the family Gitea forge, and an answer (404 at the root) from
  https://static.crates.io.
- It was submitted from a campus workstation through `lab_commons.hpc submit` / `gather` on the research account,
  with no consent needed.
- Consequence: a compute-node task may fetch packages, crates and git objects itself; nothing has to be
  staged through a login node for lack of egress.

## User rulings (2026-11-27)

- "An HPC login node may run exactly one cron poller; no other unapproved polling or scripts."
- "Ada login nodes take ssh directly from the three campus workstations; every other machine only over VPN."
