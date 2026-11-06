---
name: push-message-checks-share-one-public-cli-process
description: Preserve exact Git selection, full message bytes and public Commitizen admission while removing per-SHA interpreter startup.
metadata:
  type: project
created: 2026-11-05
corrects: 2026/11/05/push-message-validation-never-puts-the-message-on-argv.md
---

# Push message checks share one public CLI process

Human authorized autonomous completion; the coordinator explicitly approved this narrow owner fix after a real consumer push spent approximately 1893 per-SHA checks repeatedly starting Python. Work starts from canonical `709745880d74ca6d5af60e1a28dc070d7b3920fd` (PR 117), clean declared worktree, new `fix/cz-public-cli-batch` branch. The separate dev-lab-owner's staged work is untouched.

The shell retains RANGES, OWN, base exclusion, exemption validation, reverse Git order, ordinary no-exemption rev-range fast path and aggregate refusal. Only its existing per-SHA execution segment changes: stream the already validated exemption set and actual selected SHAs through stdin to one checkout-owned interpreter. Neither bodies nor an unbounded SHA list enters Windows argv. The same shell-owned private mktemp path receives each raw binary `git log -1 --format=%B` stdout; the existing EXIT trap still cleans success/refusal. No second message serializer, private validator or new message regex exists.

`dev_lab.dev.czbatch` calls the installed `commitizen.cli.main` public console entrypoint for each file and delegates Commitizen exceptions to its public exception hook. Each call restores the original `sys.argv` object and `sys.excepthook` in finally, including refusal and unexpected failure. Invalid commits do not prevent subsequent commits being checked. Missing Git is an explicit refusal; the existing with-venv module/tool import probe still refuses an absent/incomplete checkout environment. No dependency, credential, global configuration, exemption policy, history, range rule or pushgate changes.

Actual installed Commitizen is 4.19.3. The public CLI oracle compares both exit status and stdout/stderr using the identical file, twice, including ordinary, Unicode/quoted bodies above the Windows argv ceiling, merge, revert, invalid and comment cases. Real-Git controls compare each selected nonexempt raw byte hash and length, unique exact exemption, failure followed by valid commits, one file and aggregate refusal. Existing shell controls retain cleanup-on-success/refusal, missing tools, fallback, upstream exclusion and fast-path coverage; the planted checker now exposes the same public CLI/exception seam instead of a subprocess-only entrypoint.

TDD: first official measure produced ImportError RED before the new module existed. Final focused measure `tests/test_dev_czbatch.py tests/test_dev_githook_scripts.py`: 38/38 pass in 65.95 s, tree `sha256:b2dd22d76bdc027c`, log `sha256:a401b5c8fdd2953f8cbabeaa271797c3a54057235b9704948cbc8abd04144af3@17`. Additional `tests/test_arch_public_surface.py tests/test_dev_gate.py`: 7/7 pass in 10.65 s, log `sha256:52e9a50200cccbd97d5dde629acd3f7932ed29d78ae7edc915209e2168ffd03b@17`. Ruff check/format pass. Only own tooling environment and light tests were used, no solver/native build/full suite.

Measured same-selection experiment (not a 1893-commit projection): `git rev-list --reverse -n 24 origin/integrate/main`, selected SHA sequence digest `d5283e3ff1b1e909178b61ea74398f7dfeb80e9ee9f0b3bc224f55b8f646faed`; message SHA sequence digest `5d06edc7296024cd7fb76464ef74effa158f0a098550e93f2774702c8982c87b`. One private file, actual raw Git bytes and identical per-message CLI arguments in both routes. Separate-process public CLI: 58.5032988 s; one-process public CLI: 8.3166172 s (about 7.03x for these 24 only). All per-message exits and full-byte hashes match, both aggregates zero. This measures the old direct CLI startup cost without adding the old shell wrapper's additional probes; no full-push speed or transport success is claimed.

The consumer's HTTP401 remains a separate unresolved authentication/transport symptom, not proven permission denial, stale kit or lease expiry. A read-only official ls-remote succeeded with no migration ref. No GCM refresh, credential inspection/change, global/OneDrive configuration change or publication occurred in this lane. Root owns PR/merge and consumer adoption.
