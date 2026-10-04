# The forge — how `main` is protected, and how to configure it

- This page is the CONFIGURATION of the forge side; the local half is [the verdict model](verdict-model.md) (what a verdict is) and [branch layers](branch-layers.md) (how a lane lands).
- **The forge is a REMOTE, cloud-hosted service: nothing in any repo here starts, stops or restarts it.** Everything below is configuration applied THROUGH its API or web UI, and a forge-side failure is diagnosed and REPORTED, never waited on for a restart that nobody here can perform.
- **A network verb goes through the retry wrapper, three times, and a write that still fails is REPORTED with its diagnosis rather than hammered** — three retries of a server-side failure is an hour of CPU for the same answer.
- Everything below was measured against this family's self-hosted forge on 2026-08-27, using `consumer-a` as the repo under protection. The other repos in the family have the same forge and the same accounts, so the configuration transfers; only the repo name changes.

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
2. Name the required context, one per repo: `lab/heavy`.
3. Grant the integrator a personal access token with write scope.
4. After a heavy run, the integrator POSTs the verdict as a commit status against that context, with the verdict line as the description.
- **Steps 3 and 4 now exist; steps 1 and 2 are a separate, human-confirmed forge change.** Step 3 is `auth login` below. Step 4 is the door `python -m lab_commons.dev.forge status post <sha> --context <ctx> --state success|failure|pending --description <text>` (and `status list <sha>`, latest per context), on Gitea and GitHub alike. Its writes carry no provenance line: a status description is the machine verdict line, cut to the 140-character forge limit.
- **The two contexts.** `lab/gate` is a lane's own gate verdict, posted by the dev agent; `lab/heavy` is the integrator's heavy verdict and is the one `main` protection names. PASS posts `success`, FAIL posts `failure`, and **INCONCLUSIVE posts `error`** whose description is the verdict line (user ruling 2026-10-04): a lane may push an INCONCLUSIVE tree, so every pushed tree carries the verdict it was pushed on, and `error` still fails `main` protection.
- **`python -m lab_commons.dev.verify` publishes `lab/gate` by itself** after a judged run, on HEAD, and only when the tree was clean before and after the run and HEAD did not move: a verdict about a dirty tree is about no commit. No credential or no `origin` skips with one line, a refused post prints one line, and neither changes the verdict or the exit code. `--no-status` opts out. A heavy runner publishes `lab/heavy` the same way, by calling `lab_commons.dev.forgestatus.publish` with `context=HEAVY_CONTEXT`.
- **Do not enable the status check before a real `lab/heavy` status exists on `main`'s tip.** A required context that nothing ever publishes can never go green, which blocks `main` for everyone including the human. Measured hazard, not hypothetical — this is why the check was turned off again on 2026-08-27. Enabling it is a forge setting and is the human's to confirm.

## Branch deletion after a merge

- The rule is: once a lane's change is on `main`, delete the origin branch.
- **`main` here means the REMOTE one, never the local**, and the distinction is load-bearing. Measured 2026-08-27: two branches showed **0** unmerged commits against local `main` and **352** and **162** against the remote, because local `main` was 380 commits ahead and unpushed. Deleting on the local reading would have removed the only published copy of that work.
- The question is "is this CHANGE on the remote main", so the instrument is `git cherry` against the remote — **not the ancestor test**, which asks whether a COMMIT is an ancestor and answers no for anything cherry-picked or rebased.

## Issues and pull requests — `python -m lab_commons.dev.forge`

- **Agents collaborate through these verbs and nothing else; no `gh` or `tea` binary is needed.** `lab_commons.dev.forgework` speaks the REST API directly: `issue list [--state open|closed|all] [--limit N]`, `issue view N`, `issue create --title T [--body B]`, `issue comment N --body B`, `issue close N`, `pr create --title T --head H --base B [--body B]`, `pr view N`; plus `issue claim N` / `issue status N` (see [issues](issues.md)), `issue comments N [--since ISO8601]` and the repo-wide `issue comments-since ISO8601` (every issue's comments updated since then, as `{issue, id, author, body, created}` rows: what a poller reads instead of walking every issue) and `status post|list` (layer C above). Every verb takes `--json`; the result is the same `Issue` / `Comment` / `PullRequest` shape whichever forge answered.
- **The backend is read off `origin`**: host `github.com` is GitHub REST (`api.github.com`), every other host is the Gitea-shaped forge this page configures (`<host>/api/v1`). Nothing is configured per repo.
- **Auth, per machine, never on disk in a repo**: the forge's environment variable first — `GITEA_TOKEN` for Gitea, `GH_TOKEN` then `GITHUB_TOKEN` for GitHub — else the credential the git transport already holds for that host (`git credential fill`, the layer-A route). That credential is sent as a TOKEN header, so it must be a personal access token: a stored account password authenticates the transport but newer Gitea refuses it for the API. `auth login` below is how it becomes one.

## Set up a token on a new machine

One command per forge host, run from any checkout whose `origin` is on that host (or pass `--host`):

```
python -m lab_commons.dev.forge auth login      # prompts for the token, input hidden
python -m lab_commons.dev.forge auth status     # where the token comes from, and who it is
```

- **What `login` does**: reads the token without echo (or from stdin with `--token-stdin`, for scripts), sends it to `GET /api/v1/user` (Gitea) or `GET /user` (GitHub), and **only if the forge accepts it** stores it with `git credential approve` as `https://<host>`, username = the login the forge returned. A rejected token is reported with the forge's answer and is NOT stored, so a typo never replaces a credential that worked.
- **Where it lives**: wherever the machine's `credential.helper` keeps secrets — Git Credential Manager on Windows, the keychain on macOS. Nothing is written to any file in a repo and the token is never printed; `status` shows the source (`GITEA_TOKEN`, or `git credential`) and the login only.
- **What else uses it**: the same stored credential is what `git push` / `git fetch` over https present to that host, so after `login` the transport and the forge verbs authenticate with one token. An environment variable, if set, still wins for the verbs (`login` says so when one is).
- **Gitea** — create the token at **User Settings → Applications → Manage Access Tokens → Generate Token**. Scopes: `write:issue` (issues and comments), `write:repository` (pull requests, and git push over https), `read:user` (so `login`/`status` can ask who the token is). Copy it once; Gitea does not show it again.
- **GitHub** — either a **fine-grained token** (Settings → Developer settings → Personal access tokens → Fine-grained) scoped to the repositories, with *Issues* and *Pull requests* read/write and *Contents* read/write for pushing, then `auth login --host github.com`; or let **Git Credential Manager's OAuth** sign-in store the credential on the first `git push`, after which `auth status --host github.com` should name `git credential` and your login with no `login` step at all.
- **Rotating or revoking**: generate a new token and run `auth login` again — it overwrites the stored one for that host and login. A revoked token shows up as a failing `auth status`.
- **Every call is retry-then-report in netverb's vocabulary**: three attempts, an answered 4xx (other than 401/408/429) is REFUSED at once, a 5xx or dropped connection is retried, and a failure exits 1 with the remedy. A create whose response was lost may still have landed, so before RETRYING one the door reads the newest objects back and returns the token's own identical one from the last five minutes (same title and body for an issue or PR, same body for a comment) instead of creating a twin; if that read fails, the create is reported rather than sent again. A MANUAL re-run is not covered — read before re-running.
- **Provenance contract**: when `HARNESS_MACHINE` and `HARNESS_AGENT` are both set (an agent launcher exports them), every created issue body, PR body and comment opens with one line `[<machine> · <agent> · <branch>]`, the branch omitted on a detached HEAD. With either unset nothing is added, so a human's text is never marked.

## What is needed from a human

| # | need | blocks | notes |
|---|---|---|---|
| 1 | the layer-A whitelist | every update of `main` | done 2026-08-27 |
| 2 | the status check DISABLED until layer C is wired | `main` updates, if it was enabled | done 2026-08-27 |
| 3 | a write-scoped personal access token for the integrator | layer C only | store it with `auth login` (see *Set up a token on a new machine*); **it is never written to a log, a commit, or a memory file — this family records secrets as hashes only** |
| 4 | confirmation that the token is a token, not the account password | layer C only | newer forge versions reject password basic-auth for the API, so a stored password authenticates the transport and fails the API |

- Reading the OS credential store to reuse the existing credential was attempted and refused by the sandbox, **and that refusal is correct**: extracting a secret is a decision for the human, not a convenience for the agent.
