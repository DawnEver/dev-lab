# Components

A product mounts each engine it composes as a git submodule under `components/<name>` and consumes it
by path. Libraries float: an engine depends on its peers by floating git dependencies. A product
composes exactly: its sha fixes every engine's source through the gitlinks, so one verdict per sha
means one thing. lab-commons is never a component; it stays a floating git dependency of every repo.

## The table

Declared once in the product's `pyproject.toml`, one table per engine (`<x>-lab`):

```toml
[tool.dev_lab.components.numerics-lab]
url = "https://<forge>/<owner>/numerics-lab.git"   # the engine's repository
branch = "main"                                     # the branch a bump follows
parts = ["base", "linux"]                           # the product's forge parts that verify a bump
package = "numerics-lab"                            # optional: the Python distribution it provides
crates = { numerics = "crates/numerics" }           # optional: Cargo crate -> its path in the engine
```

The mount path is derived, never declared: `components/<name>`. A missing or unknown key, a name that
is not `<x>-lab`, or `lab-commons` itself is refused, naming the row
(`dev_lab.dev.components.components_of`).

## Derived files, checked

Three files restate the table, and `drift(...)` / `drift_at(root)` check them against it. Each
disagreement names the file and the fix:

| file | what the table derives |
|---|---|
| `.gitmodules` | `[submodule "components/<name>"]` with `path`, `url`, `branch` (`gitmodules_text`) |
| `[tool.uv.sources]` | `<package> = { path = "components/<name>" }`, which overrides the engine's floating git dependency, so the environment holds one copy of it |
| Cargo manifests | each path dependency into `components/` is a declared crate at its declared path, and each declared crate is used |
| the index | a gitlink at every mount, and no undeclared gitlink under `components/` |

Only what lies under `components/` is checked. A product adopts it with one test,
`assert drift_at(ROOT) == ()`. From a shell: `python -m dev_lab.dev.components [--root R]`
exits 1 on any drift.

## The bump loop

`python -m dev_lab.dev.componentbump [--root R]` fetches origin and runs one tick
(`dev_lab.dev.componentbump.tick`). Nothing is stored: each tick derives its state from origin's
refs, the forge's statuses and its issues, so a repeated tick or two hosts ticking at once see the
same state.

1. An engine's branch tip is forge-green (every part on it PASS on the engine's own forge) and differs
   from the product's pointer on the integration branch.
2. The tick opens the one bump lane, `pr/components-bump`: one commit on the integration tip moving
   that gitlink, `chore(deps): bump <engine> to <sha12>`.
3. The forge produces the lane's verdict like any other lane's.
4. Green on every part the component declares: the lane is READY, and the
   [the forge](integration.md) merges it like any other PR. Once the integration branch holds it,
   the next tick deletes the lane.
   Red on any declared part: the tick opens one issue,
   `components: bump <engine> to <sha12> is red`, naming the engine commit and the red parts, and
   deletes the lane. Nothing merges, and the pointer stays on the last green commit. That engine
   commit is held while its issue exists (open or closed). The engine's next green commit is a new
   candidate.
5. Bumps run one at a time. There is one lane name, created only if absent
   (`--force-with-lease=<lane>:`), and no candidate is considered while it exists. A host that loses
   the race reports `raced`.

## Trees carry their components

Every tree that runs a product's code initialises its submodules at their pinned commits: the forge's
local part trees (`shatree`), the cluster's run trees (`hpc.shell`), and each served checkout that the
deploy and its tick update (`hpchost.steps.update`).
