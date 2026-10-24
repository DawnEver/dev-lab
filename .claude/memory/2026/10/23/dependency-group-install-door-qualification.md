---
name: dependency-group-install-door-qualification
description: Published PR15, actual targeted and forge receipts, and unverified UnitJob guard blocked by HPC connectivity.
created: 2026-10-23
metadata:
  type: project
---

# Dependency-group and frozen-install owner qualification

## Published authority

PR15: https://gitea.mingyangbao.site/Tianjie-Zou-Team/dev-lab/pulls/15
Branch: `pr/dependency-groups-and-frozen-install`; target: `integrate/main`.
Published graph before the compute guard: `5fcf31b77e638735218dcfc8ca4e568217fd6d38`.
Normal hooks were used for all commits and pushes. No manual merge was performed.

Group selection is distinct from extras; defaults, explicit groups, includes, exclusions and
only-group selection are measured. Unknown or ambiguous contexts are refused. Explicit frozen/
locked installation requires a tracked readable lock; this is not a freshness certificate.
Freshness remains the separate pre-push `lockcheck` gate. Redirected project/configuration/script
contexts cannot borrow the scanned root's lock proof. Review decisions are preserved in PR15
comments 18087 and 18097; the HIGH suggestion to revert PIN + FRESHNESS was rejected with code evidence.

## Actual receipts, not interchangeable qualifications

- Baseline `2235c51c5eeead0b1e8e57413d9b24682bd9d1e4` plus new mechanism tests:
  HPC7805469, 25 collected, 24 failed and 1 passed.
- Mechanism targeted GREEN: HPC7806477, 178 passed across nine affected files.
- Published `7b481850c11c297e26618c8b591401b523868879` formal full base: HPC7806495,
  4150 ran with four inherited failures. Baseline official full had the exact same four failures.
- Cut-over audit repairs: HPC7806545, four complete affected files, 880 passed. These add the
  existing lazy-import waiver to its named registry, declare seven moved modules' provenance,
  and correct the old kit-name and allocation-command fixtures without weakening their assertions.
- Published `08dd3c5311089ec7e8622e05d78805e1755af832` formal `tests/base` SUCCESS:
  HPC7806565, 4150 observed OK, environment `9e1b88083b52c832`.
  Durable attachment: `695e71df-51f9-4cd2-a649-e8f3ac40432a`.
  It handed 125 workstation cases elsewhere; those are not counted as passed.
- Real dependency-graph change: remote symbolic HEAD was verified as `integrate/main` at
  `26187799584ed85e556f23714ba815560e1579a1`. Removed the branch-qualified runtime source,
  retaining one bare git URL. The lock changed lab-commons from `16140227f570` to `26187799584e`;
  other 35 distributions did not change. This is not merely a URL-only change.
- Source/lock identity TDD: HPC7806588, old graph plus new regression, 1 failed;
  HPC7806589, coherent new graph and affected group/install/lock controls, 196 passed.
- Latest published `5fcf31b77e638735218dcfc8ca4e568217fd6d38` formal base FAILURE:
  HPC7806607, 4151 ran = 4150 observed OK + 1 rejected; environment `0a014bfb1c218924`.
  Durable attachment: `71e5e4d0-ea46-461a-84e6-2c3c786936df`.
  Again, 125 workstation cases are handoffs, not passes.

## Compute guard: targeted qualified, next formal full pending

Exact failing node:
`tests/test_dev_forgeunit.py::test_a_job_spells_its_unit_bundle_size_and_needs_as_paths`.
The newer general `Demand` permits a zero-CPU vendor/resource claim. A forge compute UnitJob
still requires positive CPU; the old parser accidentally delegated that stricter contract to Demand.

Source7 changes only `UnitJob.of` to refuse nonpositive CPU after parsing. The original
zero-CPU refusal assertion is retained. One new positive fractional-memory round-trip assertion
uses 0.25 GiB. Ruff, format and diff checks passed locally. No local behavioral substitute was run.

Execution froze source7 for the complete `test_dev_forgeunit.py` targeted HPC verification. Initial
ADA login02 attempts timed out three times and the already-known login01 also timed out.
No host-key changes, new account, permission bypass, or duplicate producer was used. This is an
external connectivity block, not a failed test. After connectivity recovered, the original frozen
source7 was actually verified as HPC7806650: **5 passed**, official exit0. Tree
`36dd787c5084e5c9`, environment `f222c9cd2e523c17`, log
`3d88e6a5a5e21269c03d249c292a65ff67e63b74d4ea6c245860774bd56198a3@17`.
Next: normal-hook update of this same PR and the new published revision's formal full verdict.
Do not reuse the earlier 4150-pass graph receipt, or claim five targeted cases as a full verdict.
