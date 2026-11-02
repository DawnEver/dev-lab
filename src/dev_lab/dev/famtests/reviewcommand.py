"""REVIEW-COMMAND-IS-THE-FAMILY'S: a repo's ``[tool.dev_lab.review]`` declares only where it differs.

The command is :data:`dev_lab.dev.forgereview_declared.FAMILY_COMMAND`, owned here in dev-lab; a repo overrides the
model,
bounds or globs. A redeclared family command, or a retired host field (any ``{capabilities.*}``), is
refused by :func:`dev_lab.dev.forgereview_declared.review_from`; this body runs that refusal over the repo's own
manifest at
test time, so a stale copy is red in its own repo before the forge ever loads it.
"""

from __future__ import annotations

from pathlib import Path

from dev_lab.dev.forgereview_declared import load_review

__all__ = ['assert_the_review_declares_only_its_difference']


def assert_the_review_declares_only_its_difference(root: Path) -> None:
    """*root*'s review table loads: no redeclared family command, no retired host field, no unknown key."""
    try:
        load_review(root)
    except ValueError as refused:
        raise AssertionError(str(refused)) from refused
