# The shared checkout

Several agents and a human may write the same checkout at the same time; there is no single-agent mode. Commit
within seconds of editing, stage only the paths you mean, never stash, and never edit a tree whose run is in
progress. This page names what is shared and how each piece goes wrong, so a symptom can be traced to a
mechanism rather than to "the checkout".

## What is shared, and how it bites

| shared thing | the failure | the habit |
|---|---|---|
| the working tree | another party's tool rewrites or restores files under you | commit promptly; an unstaged edit is not storage |
| the index | a broad `git add` sweeps another agent's file into your commit | stage explicit paths; check `git diff --cached --stat` before committing |
| a path-scoped `git commit -- <paths>` | it commits the working-tree snapshot of those paths, not only your changes | stage the content you mean, then verify `git show <sha> -- <path>` |
| the stash | `refs/stash` is one ref per repository, popped by whoever pops next | use a scratch commit or a detached worktree; stash is refused |
| HEAD | `--amend` rewrites whoever committed last | land corrections forward; amend is refused |
| a running test session | collection imports the tree, so an edit mid-run makes the verdict describe neither tree | queue the edit; work in another worktree |
| the environment | an install during a run makes its verdict cite a dead environment | mutate only through the dependency door, which waits for the environment's seat |
| memory directories | a relative memory path written from a worktree lands in that worktree | resolve the top level before staging memory |

## Hooks on a shared tree

- The family hook runner selects among STAGED paths and fails a hook that rewrites the working tree, so a hook
  never silently changes files another party is editing ([project files](project-files.md#git-hooks-and-ci-workflows-are-toml)).
- Format before staging; a formatter that runs at commit time and fails turns every commit into two.
- A push runs no test and takes no lock, so a push that blocks is a defect: stop it and push again later.

## The transferable question

Before trusting a tool on a shared checkout, ask what its correctness assumes (exclusive ownership of the
tree, a ref being current, a lock being uncontended), and whether that assumption is visible in its output. If
the tool reports the same thing either way, the assumption is load-bearing and unmonitored, and that is where a
check belongs.
