---
name: ops-access-installs-itself-and-a-host-has-one-totp-secret
description: The [ops.access] gaps found tightening the Oracle hosts are closed -- install makes the keys dir and the PAM include itself, permit_open serves jump hosts, enrol draws a QR, and the host's one TOTP secret is shared with break-glass.
corrects: forge-host-backup-access-and-probe-are-roles-too
metadata:
  type: project
created: 2026-11-04
accessed: 2026-11-04
---

# Ops access installs itself, and a host has one TOTP secret

- The operator no longer adds the PAM include: install puts `@include dev-lab-ops-access` above
  `@include common-auth` in `/etc/pam.d/sshd` (idempotent) and refuses an absent or other-shaped stack before
  writing anything. Install also creates `/etc/dev-lab/ops` (root 755) when a role renders keys.
- Jump hosts: `[ops.access] permit_open = ["host:port", ...]` renders `AllowTcpForwarding local` + `PermitOpen`;
  empty keeps `AllowTcpForwarding no`.
- ONE TOTP SECRET PER HOST (user ruling 2026-11-04): `[ops.access] totp`, else `[ops.breakglass] totp`; two
  different files refuse ("two TOTP secrets on one host"). The pam_oath users file is DERIVED from it at install
  (root 600). `access enrol` is first-ever only -- a QR on stdout (`--uri` prints the URI; `breakglass enrol` the
  same) -- and refuses when the secret exists; `access adopt --secret-file <path|->` places a secret the phone
  already holds, never echoing it. The QR needs the `dev-lab[ops]` extra (segno).
- Next steps that STAY next steps: `apt-get install libpam-oath` and `useradd` change the host's package set and
  account database with distro-specific tools; a `--root` render must not run them and a test root cannot.
