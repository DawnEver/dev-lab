# The docs pipeline

A repo's documentation site is built by the family driver, `dev_lab.dev.docsite`, from a table of sub-sites
the repo supplies. Write markdown under `docs-src/`, add a sub-site as a ROW, and build through the repo's one
entry point; the output is a build product and stays ignored by git. The driver owns what a requirement and a
skip mean; the repo owns which packages, paths and flags.

## The rules the source tree keeps

- **`docs-src/` is the only hand-written source**, in markdown, the one format a human and a model both edit
  without a toolchain.
- **The built output stays ignored by git**; a test pins that it does.
- **One entry point builds it.** Redirecting the output root and opening the result are flags on it, never
  second scripts.

## The three properties

1. **A failed build never reports success.** Every command runs checked; an empty output directory is a failure.
2. **A missing toolchain SKIPS and SAYS SO**, in the report and on the portal page. Silence would make "the docs
   are missing" and "there are no docs" the same observation. The skipped set is a mapping, not a count.
3. **Adding a sub-site is a ROW, never a branch in the control flow.**

## Rows with their own honesty

- **A crate or package list is DERIVED** from the workspace manifest, never enumerated, and any exclusion list is
  rendered on the portal.
- **A licence notice refuses rather than degrades**: a dependency whose licence cannot be identified fails the
  build. It is a row, never a committed file, so it cannot drift.
- **Relative links are rewritten to the output suffix**, so a tree that reads correctly on the forge navigates
  correctly once rendered; external URLs are untouched.
- **Every built sub-site produces an index**, because the portal links it; the builder checks that contract.

## A sub-site from another repo's tree

- **Its requirement is a CHECKOUT, not a tool** (the driver's `Tree` requirement): a package's `docs-src/` is not
  in its wheel, so the reader is told "not present, clone it" rather than "not on PATH".
- **Resolve the sibling off the PRIMARY checkout**, through `git rev-parse --git-common-dir`; a worktree sits
  deeper, so `repo_root().parent` is wrong there.
- **One renderer, two trees**: the markdown renderer takes its source root as an argument.
- These family pages are rendered that way as a consumer's `family` sub-site; a box without the sibling checkout
  gets that row's announced skip naming the clone.
