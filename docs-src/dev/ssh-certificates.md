# Short-lived ssh certificates

The user's TOTP code stays the human proof; its output can be a short-lived ssh user certificate that every
server the family administers admits (user ruling 2026-11-28, dev-lab #1058). Code: `dev_lab.ops.sshca`.

- **Who signs.** The consent issuer, with a CA key it alone holds (`[ops.ssh_ca] key`, made once by
  `ops consent ca-keygen`). It certifies only a LIVE credential it issued, so no second code is asked
  (`Issuer.certify`, serve verb `ssh-cert`).
- **Who trusts.** Each administered host renders ONE row, `[ops.ssh_ca] public_key`, as sshd `TrustedUserCAKeys`
  through `ops install` / `config apply`. Shared cluster (HPC) accounts are out of scope: their sshd is not ours,
  so they stay on keys.
- **The client.** `python -m dev_lab.ops.consent certify <credential.json> --principal <account> --public-key <pub>`
  keeps the certificate beside the credential; the next ssh call to that account presents it with
  `-o CertificateFile=` (`door.live_certificate`, `remote.certificate_options`).

## The row

```toml
[ops.ssh_ca]
public_key = "ssh-ed25519 AAAA..."   # what `ops consent ca-keygen` printed; public, never the key
principals = ["consent", "breakglass"]  # the accounts a certificate may name
revoked = []                          # the KRL row: certificate key ids (= credential ids)
accept_keys = true                    # N-1: listed keys still open the accounts; false = N, certificates only
ttl = "1 h"                           # the longest certificate, a duration with its unit
key = "/etc/dev-lab/ops/ssh-ca.key"   # the issuer's host only
```

## Lifetime, skew and revocation

- A certificate lives `min(ttl, the credential's remaining life)`: it never outlives the wave or hold it rides on.
- Clock skew: sshd tolerates none, so `valid_after` is backdated by `sshca.SKEW_S` (120 s). A host clock behind by up
  to that still admits a fresh certificate; one ahead by *d* shortens it by *d*. The end is never extended.
- Revocation is the short lifetime, plus the KRL row: `revoked` renders a KRL spec that `ssh-keygen -k` compiles on
  the host. That step precedes every sshd reload in the install's next steps, because sshd refuses EVERY key while
  its `RevokedKeys` file is absent.
- The issuer's ledger records each certificate as `certified` with its credential id, serial and principals, never
  the key.

## N/N-1 rollout

1. Issuer host: declare `key`, run `ops consent ca-keygen` once, and copy its printed public line into the row.
2. Every administered host: the row with `accept_keys = true` (N-1). Both certificates and listed keys open the
   accounts. `ops install` renders the drop-in, the CA file and the KRL spec, and names the KRL build and sshd reload.
3. Once every client certifies, set `accept_keys = false` (N): each principal's `AuthorizedKeysFile` becomes `none`.

Each step changes who may log in, so each lands through `config apply` under an `ops.config` consent.
