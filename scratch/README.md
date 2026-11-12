# scratch

The one place an agent may leave a one-off: an experiment, probe or verification. It is visible to
`git status` on purpose, and nothing here but this README is ever committed
(SCRATCH-IS-NEVER-COMMITTED, `dev_lab.dev.scratch`).

Every one-off leaves by one of two exits:

1. **Promote** it into `src/` with tests, when it is useful.
2. **Delete** it, when it is not: `python -m dev_lab.dev.scratch discard <path>`.

A finding it produced goes to memory as numbers. `scripts/` is not an exit: it holds dev mechanisms
only. `python -m dev_lab.dev.scratch list` lists what is here, oldest first; `python -m dev_lab.dev.scratch clear [NAME ...] [--keep NAME ...] --yes` deletes the named untracked entries, or those this session left.
