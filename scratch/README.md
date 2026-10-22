# scratch

The one place an agent may leave a one-off: an experiment, probe or verification. It is visible to
`git status` on purpose, and nothing here but this README is ever committed
(SCRATCH-IS-NEVER-COMMITTED, `lab_commons.dev.scratch`).

Every one-off leaves by one of two exits:

1. **Promote** it into `src/` with tests, when it is useful.
2. **Delete** it, when it is not: `python -m lab_commons.dev.scratch discard <path>`.

A finding it produced goes to memory as numbers. `scripts/` is not an exit: it holds dev mechanisms
only. `python -m lab_commons.dev.scratch pending` lists what is here, oldest first.
