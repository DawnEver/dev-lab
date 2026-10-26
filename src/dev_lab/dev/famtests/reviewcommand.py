"""REVIEW-COMMAND-IS-THE-FAMILY'S: a repo's ``[tool.lab_commons.review]`` declares only where it differs.

The command is :data:`dev_lab.dev.forgereview.FAMILY_COMMAND`, owned here in dev-lab; a repo overrides the model,
bounds or globs. A redeclared family command, or a retired capability (``{capabilities.sharp_review.*}``), is
refused by :func:`dev_lab.dev.forgereview.review_from`; this body runs that refusal over the repo's own manifest at
test time, so a stale copy is red in its own repo before the forge ever loads it.
"""

from __future__ import annotations

from pathlib import Path

from dev_lab.dev.forgereview import load_review

__all__ = ['assert_the_review_declares_only_its_difference']


def assert_the_review_declares_only_its_difference(root: Path) -> None:
    """*root*'s review table loads: no redeclared family command, no retired capability, no unknown key."""
    try:
        load_review(root)
    except ValueError as refused:
        raise AssertionError(str(refused)) from refused
