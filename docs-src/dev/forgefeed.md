# How a task hears the forge

A task hears what it subscribes to without anyone relaying it (`TASK-HEARS-ITS-FORGE-EVENTS`, D79, D81).

- **Subscribe with a label.** Put `task:<slug>` on an issue or PR. A PR a session of the task opened or pushed is
  subscribed already. Nothing else subscribes.
- **One read per repository.** One machine hearer, `python -m dev_lab.dev.forgefeed run` (started at session start),
  asks each repository the machine file declares under `[repos]` for its issues and PRs updated since that
  repository's saved cursor (`issues?state=all&since=`). Labels come with each row, so routing costs no further
  read; adding a label moves the thread's `updated_at`, so it is heard on the next tick. A 304 to the stored ETag
  costs nothing. Commit statuses are in no listing, so open PRs still have their statuses read.
- **The tick is a setting:** `[forgefeed] tick_s` in the machine file, default 120 seconds.
- **The prune duty rides on its own interval.** Where the family binds `prune = { host = "<this machine>" }`, every
  `[forgefeed] prune_duty_s` (default 1800 s) the hearer fetches each declared checkout and runs the prune duty:
  close landed PRs, sweep, prune merged heads, observe the branch policy ([branch set](branch-set.md)).
- **A break-glass wave awaiting review is news, never an issue.** Where the machine file declares a `[breakglass]`
  endpoint, the hearer asks its status at most every 30 minutes and each session is told each wave in `audit`
  once, with its door (`forge breakglass status`, then `forge breakglass ack <wave>`): `dev_lab.dev.forgewaves`.
- **Heard at the next prompt.** Each change lands in its task's queue (`python -m dev_lab.dev.forgefeed
  task-pending <slug>` lists it); every session whose checkout is on a head `pr/<slug>/<feature>` of the task reads
  it once, through its own cursor. A PR a session pushed belongs to the task its branch names. A comment this
  machine posted is not news.

Detail: the module doc of `dev_lab.dev.forgefeed`; the PR record is `dev_lab.dev.sessionprs`; the task of a checkout
is `dev_lab.dev.taskledger.task_of`.
