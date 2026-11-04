---
name: forge-host-backup-access-and-probe-are-roles-too
description: The forge-host-roles PLAN's follow-ups landed on the same PR -- backup export/pull with an overwrite-safe single-PUT off-site copy, a key+TOTP ops-access account via pam_oath, and the probe as supervise configuration.
corrects: PLAN-forge-host-roles-are-one-configured-mechanism
metadata:
  type: project
created: 2026-11-04
accessed: 2026-11-04
---

# Backup, ops access and the probe are roles too (follow-ups of the 11-03 PLAN)

- BACKUP (`dev_lab.ops.backup`, `[ops.backup]`): `ops backup export` is the export account's forced command
  (`restrict,command="sudo -n ..."`), runs every declared dumper (`gitea`: `gitea dump` as the Gitea user;
  `postgresql`: `pg_dump -Fc` as the database user; one function each, so another forge or database is one more
  entry), refuses an empty dump before writing a byte, and writes ONE tar to stdout. `ops backup pull` (timer)
  fetches it over ssh with a dedicated key, unpacks into `<dest>/<UTC stamp>/` via a partial directory, refuses an
  empty stream or file, and removes stamped backups older than `retention_days`.
- OFF-SITE (`dev_lab.ops.offsite`, `[ops.backup.offsite]`), encoding the 2026-11-03 Oracle Object Storage
  measurement as the rule for every store: keys `<label>/<stamp>/<name>-<sha256[:16]>.<ext>` (the retention rule
  forbids overwrite); single `PutObject` only, a file above `max_put_bytes` (5 GB) refused before any PUT (the
  credential cannot create multipart uploads); path-style (the AWS CLI config file must say so, checked); remote
  size read back. Through the AWS CLI's `s3api put-object`/`head-object`, not boto3: no new dependency, and
  `put-object` is one request whatever the transfer client (classic vs CRT matters only to `aws s3 cp`). Every
  failure alerts through `[alerts]`.
- OPS ACCESS (`dev_lab.ops.access`, `[ops.access]`): ssh key AND TOTP (`AuthenticationMethods
  publickey,keyboard-interactive`), every forwarding off, sudo limited to the declared commands (sudoers syntax in a
  command refused). pam_oath, not libpam-google-authenticator: the latter keeps the secret in the account's own
  home, readable by the agent it gates; pam_oath reads a root-only users file. The PAM include applies to that
  account only; the operator adds `@include dev-lab-ops-access` as the first auth line of `/etc/pam.d/sshd`.
- PROBE: configuration only. supervise's `HttpHealth` (`[components.http_health] endpoints = [{name, url, expect}]`)
  probes through DNS and has no host-to-IP pin; to probe a host at a fixed address (as the hand-written
  `forge-probe` did with `curl --resolve`), declare a `ShellProbe` (`[components.shell_probe] probes`) running
  `curl --resolve <host>:443:<ip> https://<host>/...`. No new code.
