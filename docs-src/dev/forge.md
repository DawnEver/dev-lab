# The forge — how `main` is protected, and how to configure it

- This page is the CONFIGURATION of the forge side; the local half is [the verdict model](verdict-model.md) (what a verdict is) and [branch layers](branch-layers.md) (how a lane lands).
- **The forge is a REMOTE, cloud-hosted service: nothing in any repo here starts, stops or restarts it.** Everything below is configuration applied THROUGH its API or web UI, and a forge-side failure is diagnosed and REPORTED, never waited on for a restart that nobody here can perform.
- **A network verb goes through the retry wrapper, three times, and a write that still fails is REPORTED with its diagnosis rather than hammered** — three retries of a server-side failure is an hour of CPU for the same answer.
- Everything below was measured against this family's self-hosted forge on 2026-08-27, using `motronics-studio` as the repo under protection. The other repos in the family have the same forge and the same accounts, so the configuration transfers; only the repo name changes.

## The rule being enforced

- **`main` accepts only a tree that the HEAVY tier has judged** — user directive 2026-08-27: the integrator does the merge, and a heavy PASS is the standard it merges on.
- **A gate PASS is NOT sufficient, and the difference is not academic**: the heavy partition excludes the integration-test layer and every live vendor engine from the gate, so a gate PASS is SILENT about business acceptance. Measured the same day, 15 integration failures sat behind a green gate all day because no gate tier ran them.
- The local enforcement is a pre-push check that refuses unless a stored verdict holds a heavy PASS whose tree is this clean HEAD and whose environment is this environment.

## Layer A — the push whitelist (REQUIRED, no token needed)

- The integrator updates `main` directly; nothing goes through a pull request.
- **Run the script; do not click.** One command reports every clause and whether it MEETS the target; the same command with an apply flag sets the push permission and the whitelist.
- **Prose could not fire, and this is the measurement that proves it**: on 2026-08-27 the rule everyone believed was in place was push DISABLED with an EMPTY whitelist, and no amount of reading a page would have said so.
- A second machine joining the forge runs the same command rather than re-typing a checklist, which is how two machines end up differently protected.
- **Add a machine's account to the whitelist constant in the script, not by hand in the UI**, so the whitelist is reviewable and travels with the repo.
- The credential comes from the git credential helper the transport already uses — no new secret, no environment variable — and **only its hash prefix is ever printed**.
- What this buys: the "heavy judged this tree" rule still holds, enforced by the CLIENT-SIDE hook. What it does not buy: **a client-side check shares fate with the client.**

## Layer C — the server-side status check (REQUIRED once more than one machine writes)

- **Why it is not optional under multi-machine, multi-agent iteration.** The layer-A guarantee lives in a hook inside ONE checkout. A second machine whose hooks are not installed has an unobstructed path to putting an unjudged commit on `main`, and nothing on the server would notice. A script can report whether a checkout's hooks are live, but only about the checkout it runs in.
- **What it does:** the server refuses any `main` update whose commit does not carry a green status in a NAMED context, so the rule stops depending on what each client happens to run.
- Configuration, in order:
1. Enable the status check on the branch protection rule for `main`.
2. Name the required context, one per repo.
3. Grant the integrator a personal access token with write scope.
4. After a heavy run, the integrator POSTs the verdict as a commit status against that context, with the verdict line as the description.
- **Do not enable the status check before steps 3 and 4 exist.** A required context that nothing ever publishes can never go green, which blocks `main` for everyone including the human. Measured hazard, not hypothetical — this is why the check was turned off again on 2026-08-27.

## Branch deletion after a merge

- The rule is: once a lane's change is on `main`, delete the origin branch.
- **`main` here means the REMOTE one, never the local**, and the distinction is load-bearing. Measured 2026-08-27: two branches showed **0** unmerged commits against local `main` and **352** and **162** against the remote, because local `main` was 380 commits ahead and unpushed. Deleting on the local reading would have removed the only published copy of that work.
- The question is "is this CHANGE on the remote main", so the instrument is `git cherry` against the remote — **not the ancestor test**, which asks whether a COMMIT is an ancestor and answers no for anything cherry-picked or rebased.

## What is needed from a human

| # | need | blocks | notes |
|---|---|---|---|
| 1 | the layer-A whitelist | every update of `main` | done 2026-08-27 |
| 2 | the status check DISABLED until layer C is wired | `main` updates, if it was enabled | done 2026-08-27 |
| 3 | a write-scoped personal access token for the integrator | layer C only | hand it over as an environment variable; **it is never written to a log, a commit, or a memory file — this family records secrets as hashes only** |
| 4 | confirmation that the token is a token, not the account password | layer C only | newer forge versions reject password basic-auth for the API, so a stored password authenticates the transport and fails the API |

- Reading the OS credential store to reuse the existing credential was attempted and refused by the sandbox, **and that refusal is correct**: extracting a secret is a decision for the human, not a convenience for the agent.
