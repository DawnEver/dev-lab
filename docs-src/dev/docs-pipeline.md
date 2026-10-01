# The docs pipeline — the three properties, and what a skip must say

- The MECHANISM is `lab_commons.dev.docsite`, whose docstring carries the measured comparison of the three implementations it replaced; this page is the DESIGN it holds, so a repo adding a sub-site knows what the driver will and will not do for it.
- **The split:** the DRIVER is the family's — what a requirement is, what a skip means, what the portal says about a sub-site that was not built, and that every subprocess is checked and bounded. The FACTS are the caller's — which packages, which output path, which flags, which logo.

## The rules the source tree keeps

- **A hand-written source directory is the only hand-written source** — markdown, because markdown is the one format both a human and a model edit without a toolchain.
- **The built output is a build product and stays ignored by git.** A directory that is both tracked and generated drifts by construction, and a test should pin that it stays ignored.
- **One entry point builds it.** Redirecting the output root and opening the result are flags on that entry, never second scripts.

## The three properties, each replacing a measured defect

1. **A failed build must not report success.** Every command runs checked. Measured: one implementation ran the API generator unchecked and reported exit 0 over an EMPTY output directory — indistinguishable from a real build at every downstream point.
2. **A missing toolchain must SKIP and SAY SO.** Rust is not installed everywhere and a JavaScript toolchain even less so, so a sub-site whose tool is absent is skipped — but it is named in the report AND on the portal page. **Silence makes "the Rust docs are missing" and "there are no Rust docs" the same observation.**
3. **Adding a sub-site is a ROW, never a branch in the control flow.** The table is the thing under review.

- The skipped set is a MAPPING rather than a count, for the same reason a pin is a named set rather than an integer: "3 sub-sites skipped" is the shape of message that lets a permanently-broken toolchain look routine.

## Rows that carry their own honesty mechanics

- **A crate or package list is DERIVED, never enumerated.** One version globbed the crate directory and missed a whole binding crate — an exclusion doing no work while looking like one. Derive from the workspace manifest, and RENDER any exclusion list on the portal, so a sub-site that omits a member never reads as complete.
- **A licence notice REFUSES rather than degrades**: it raises on a dependency whose licence it cannot identify, and the build fails with it instead of shipping a notice that silently omits one. It is a ROW, not a committed file (user directive 2026-08-21) — a committed notice can only be as current as whoever last regenerated it, and derived from the environment that produced it there is no drift left to catch.
- **A rendered markdown tree rewrites RELATIVE links to the output suffix**, so a source tree that reads correctly in a git forge also navigates correctly once rendered. Only relative links are rewritten; an external URL must not be touched.

## The contract the portal relies on

- The portal links each built sub-site's index page, so **a build that produces no index ships a dead front-page link.** Measured: generating documentation for a single crate writes no root index, unlike generating it for the whole workspace.
- The builder checks that contract itself, and a test keeps it green.

## A sub-site whose source is ANOTHER repo's tree

- **Its requirement is a CHECKOUT, not a tool.** An installed dependency makes the code reachable, but a package's `docs-src/` is not in its wheel. The driver's `Tree` requirement kind exists for this, so the reader is told "not present" (clone it) rather than "not on PATH" — a remedy that would send them to fix their `PATH` for a repository nobody cloned.
- **Resolve the sibling off the PRIMARY checkout**, by asking git for `--git-common-dir`. `repo_root().parent` is wrong in a worktree — a lane under the checkout sits levels deeper — and was measured reporting the sibling ABSENT on a box that has it.
- **One renderer, two trees.** The markdown renderer takes its source root as an argument, so a local guide row and a sibling-tree row differ only in which directory they read. A second copy of that function would be the fork the shared documentation exists to remove.

## Where the family's own pages stand today

- The pages in this directory are RENDERED as motronics-studio's `family` sub-site (a row in its `scripts/repo/docs.py`), which reads them from a lab-commons checkout beside its primary one, per the section above. They are equally read as markdown from this repo's checkout or from its page on the forge.
- **A box without the sibling checkout gets that row's announced skip naming the clone**, never a portal that silently omits the family half.
