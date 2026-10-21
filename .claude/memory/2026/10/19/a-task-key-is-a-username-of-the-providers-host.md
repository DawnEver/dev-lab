---
name: a-task-key-is-a-username-of-the-providers-host
description: The PR reviewer's invented credential host is retired; a model API key is the provider host plus username api-key (default) or api-key-<task>, read by lab_commons.credentials.api_key, with no fallback from a task to the default
created: 2026-10-19
---

# A task key is a username of the provider's host

User rulings 2026-10-19: the reviewer's Anthropic key uses the EXISTING credential scheme (one source of
truth), and each task gets its own AI API key.

- The scheme had no task dimension; it already had SLOTS (`api-key`, `api-key-2`... fallback keys of one
  account, `ai_lab.client`). Extended, not paralleled: `api-key-<task>` under the same provider host.
- `lab_commons.credentials`: `API_KEY_TASKS` (declared: `pr-review`, `optimization`; never a number, which
  would collide with a slot), `task_username`, `api_key(host, task=)`, and `credential_for(username=)`
  which refuses a helper answering another username -- so a missing task key can never be served the
  default by a helper that ignores the username filter.
- `forgereview` reads `api_key('api.anthropic.com', task='pr-review')`; the invented host
  `pr-review.anthropic.lab-commons` is registered in `hpc/retired.py`.
- The second key serves `optimization`: the a consumer repo `turing` decider (Anthropic Haiku through
  `ai_lab.connect`), which the HPC AI-intervention campaign also runs. Wiring the decider to pass the task
  is a a consumer repo follow-up; `ai_lab.connect(spec, task=...)` carries it.
- Stored by `python -m ai_lab.auth login anthropic --task <task>` (ai-lab lane `lane/task-api-keys`).
