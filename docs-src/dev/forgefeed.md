# How a task hears the forge

A task hears what it subscribes to without anyone relaying it (`TASK-HEARS-ITS-FORGE-EVENTS`, D79).

- **Subscribe with a label.** Put `task:<slug>` on an issue or PR. A PR a session of the task opened or pushed is
  subscribed already. Nothing else subscribes.
- **One read per forge.** One machine hearer, `python -m dev_lab.dev.forgefeed run` (started at session start),
  reads each forge host's notification feed once per tick from a saved cursor, and only a changed thread costs one
  more read (its labels). Commit statuses are in no feed, so open PRs still have their statuses read.
- **Heard at the next prompt.** Each change lands in the inbox of every session bound to the task on that machine.
  A task with no bound session keeps it: `python -m dev_lab.dev.forgefeed task-pending <slug>` lists it, and the
  next session that binds the task hears it. A comment this machine posted is not news.

The token must be able to read the feed: Gitea scope `read:notification`, GitHub classic scope `notifications`
(a fine-grained token cannot). Without it every bound session is told so by name.

Detail: the module doc of `dev_lab.dev.forgefeed`; the PR record is `dev_lab.dev.sessionprs`; the binding store is
`dev_lab.dev.taskbinding`.
