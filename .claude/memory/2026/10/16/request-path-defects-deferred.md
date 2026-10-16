# Request path: what landed on lane/request-path, and what was deferred

created: 2026-10-16

Landed (one commit each): S1 per-row cpu/mem_gb and per-name learning, S5 per-row wall_h, R1 frozen
bootstrap + lockless refusal, R4 unserved-sha refusal (claim and publish), R2 git-source probe before
claim, X1 trunks-or-allowed-author, S2 one unadmitted comment, O1-O3 record path + sha256 +
`request:done` (no auto-close), P3 `forge request` verb (creates labels), P1 paging, S4 tree per
sha+context, S6 unvouched host pin refused.

Deferred, for later:

- R0: a reproduction check that materialises the sha as a serve host does and runs the producer up to
  its first host resource; publish should require it.
- R5: host state a sha does not pin (vendor material libraries a producer may rewrite, machine-file
  tables, resource search paths): declare what a producer reads, record its hash in the result.
- S7: vendor-tool seats used outside serve are invisible to admission.
- O4: lifecycle -- an edited body silently re-targets yet keeps its aging; a failed request is never
  re-claimable; a reopened issue.
- R1/R2 scope: a pending decision makes vendor jobs file bundles (deck + runner + manifest) run without
  the repo tree or venv; the lock and git-source checks then apply only to tree-based requests and should
  not be extended for vendor jobs.
- Unverified live: Gitea accepting a label by id on `POST issues/<n>/labels` (fake-transport tests only).
