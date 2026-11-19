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
- **Heard at the next prompt.** Each change lands in the inbox of every session bound to the task on that machine.
  A task with no bound session keeps it: `python -m dev_lab.dev.forgefeed task-pending <slug>` lists it, and the
  next session that binds the task hears it. A comment this machine posted is not news.

Detail: the module doc of `dev_lab.dev.forgefeed`; the PR record is `dev_lab.dev.sessionprs`; the binding store is
`dev_lab.dev.taskbinding`.
