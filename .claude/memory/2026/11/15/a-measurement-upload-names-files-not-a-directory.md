---
name: A measurement upload names files not a directory
description: The Actions upload explicitly bounds its files and the verification child no longer inherits runner control-file channels.
metadata:
  type: project
---

Follow-up to a4afde51c63dee48ba488a792a6ec4ba248ed190, not an amendment. That commit created three evidence files but passed their whole UUID directory to upload-artifact. Its claim of an exact upload allowlist was therefore not yet proved: tested code could place other ordinary files in the same directory. The parent had published a4 without a PR or dispatch; no live upload or realized disclosure is claimed.

Tests first: verify-20261115T042800Z.log actually ran 57 items and failed 3: the existing step lacked the nonempty-output guard, its path was a directory rather than three explicit filenames, and the directory selector included planted unrelated files. It initially queued at the unchanged 1 GB floor and reported STUCK forecasts, then admitted naturally; nothing was cancelled, repriced or called RED before execution. The strengthened ordinary-file fixture uses stray-private.txt and cache/private.bin rather than relying on an action's treatment of hidden files.

A source read also found the child inherited Actions file-command paths. The parent approved closing that same ownership boundary. Before production changes, verify-20261115T044004Z.log ran 58 items and failed 4: the three upload controls plus a fake verification child that actually overwrote temporary runner control files via the inherited environment. These were isolated fixture files, never real runner channels. The missing-log branch still returned inconclusive, not a manufactured PASS.

The SSOT template now uploads only three explicit paths: receipt.json, stdout.log and verify.log. Its step runs on failure only when steps.measurement.outputs.artifacts is nonempty. It never recursively uploads the directory. The existing jobmeasure child-env owner also omits GITHUB_OUTPUT, GITHUB_ENV, GITHUB_PATH, GITHUB_STATE and GITHUB_STEP_SUMMARY, alongside the original token/producer exclusions. The wrapper retains its own output channel and ordinary SHA metadata still reaches the child. This removes inherited control-file authority; it is not an OS sandbox against hostile same-user code. No permissions, normal part path, selector option, budget, memory floor or waiting default changed.

Final complete qualifications, both on tree sha256:73271fd09fc3feeb+tracked:be168389e9f0837f and canonical environment 3e097177ca1547d2:

- verify-20261115T044253Z.log: 324/0 across complete jobmeasure, ciworkflows, ciworkflows_merge, ciworkflows_prune, jobparts, forgerequest_paths and verify files.
- verify-20261115T044753Z.log: 133/0 across complete actions_alone, famfiles, rendergoldens, prcontinue, review_last_gate, reviewruntime, forgereview_batch, relock and arch_every_forge_call_is_retried files.

Counts include each run's family sentinel, not additive unique-suite totals. Official ciworkflows/rendergoldens checks and Ruff/format checks passed. Official rendering moved only ci.yml and its two GitHub golden projections; other workflows and Gitea stayed unchanged. The lock and environment were not changed. No provider source, PRIMARY, cache or foreign process was modified, and no push or workflow dispatch was performed here. Hosted consumption must use this new head after the parent's normal publication and kit sync; a4's historical local passes are not a remote security qualification.
