"""REVIEW-COMMAND-IS-THE-FAMILY'S: a repo's ``[tool.dev_lab.review]`` declares only where it differs.

The command is :data:`dev_lab.dev.forgereview_declared.FAMILY_COMMAND`, owned here in dev-lab; a repo overrides the
model, bounds or globs. A redeclared family command, or a retired host field (any ``{capabilities.*}``), is refused
by :func:`dev_lab.dev.forgereview_declared.review_from`; this body runs that refusal over the repo's own manifest at
test time, so a stale copy is red in its own repo before the forge ever loads it.

The ENGINE side of the same contract (review items 2 and 7 on dev-lab #1121), run by the engine's repo (ai-lab) over
its own code, so a drift between the two is red where it is made:

* :func:`assert_the_family_commands_parse` -- every argument ``FAMILY_COMMAND`` and ``FAMILY_BUNDLE`` hand the
  engine, placeholders filled as a run fills them, parses with the engine's own parser;
* :func:`assert_the_requirement_precedence_agrees` -- the engine's ``[merge.requirements] precedence`` (how one run's
  reviewers combine) is :data:`~dev_lab.dev.forgereview_findings.REQUIREMENT_VERDICTS` (how dev-lab combines the
  slices): one order, never two that drift.
"""

from __future__ import annotations

import argparse
import tomllib
from typing import TYPE_CHECKING

from dev_lab.dev.forgereview_batch import NO_BATCH
from dev_lab.dev.forgereview_declared import Review, command_for, load_review
from dev_lab.dev.forgereview_findings import REQUIREMENT_VERDICTS
from dev_lab.dev.forgereview_scope import DISPOSED_FIELD, PRINCIPLES_FIELD, REQUIREMENTS_FIELD, SUMMARY_FIELD

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

__all__ = [
    'assert_the_family_commands_parse',
    'assert_the_requirement_precedence_agrees',
    'assert_the_review_declares_only_its_difference',
]

#: The leading words of a family command before the engine's own arguments: the interpreter, ``-m``, the module.
_LAUNCH = 3

#: What a run fills the per-run placeholders with (:func:`dev_lab.dev.forgereview_scope.gather`).
_PER_RUN = {
    PRINCIPLES_FIELD: 'principles.json',
    REQUIREMENTS_FIELD: 'requirements.json',
    DISPOSED_FIELD: 'disposed.json',
}


def assert_the_review_declares_only_its_difference(root: Path) -> None:
    """*root*'s review table loads: no redeclared family command, no retired host field, no unknown key."""
    try:
        load_review(root)
    except ValueError as refused:
        raise AssertionError(str(refused)) from refused


def _filled(argv: Sequence[str]) -> list[str]:
    """*argv* past its launch words, each per-run placeholder filled as a run fills it (summary: ``--no-summary``)."""
    return [
        one
        for arg in argv[_LAUNCH:]
        for one in (['--no-summary'] if arg == SUMMARY_FIELD else [_PER_RUN.get(arg, arg)])
    ]


def assert_the_family_commands_parse(parse: Callable[[list[str]], object]) -> None:
    """Every argument the family commands hand the engine parses with *parse* (the engine's ``parse_args``).

    *parse* raises -- argparse exits -- on an argument the engine does not take: that drift is named here.
    """
    runtimes = {'ai_lab': {'python': 'python'}}
    review = Review()
    commands = {
        'FAMILY_COMMAND': command_for(review, 'a..b', runtimes, paths=('x.py',), batching=NO_BATCH),
        'FAMILY_BUNDLE': command_for(review, 'a..b', runtimes, bundle=True, batching=NO_BATCH),
    }
    for name, argv in commands.items():
        args = _filled(argv)
        try:
            parse(args)
        except (SystemExit, ValueError, argparse.ArgumentError) as refused:
            msg = f'the engine does not take {name} as dev-lab hands it ({args}): {refused!r}'
            raise AssertionError(msg) from refused


def assert_the_requirement_precedence_agrees(method_toml: Path) -> None:
    """The engine's [merge.requirements] precedence of *method_toml* is dev-lab's slice order, verdict by verdict."""
    spec = tomllib.loads(method_toml.read_text(encoding='utf-8'))
    engine = tuple(spec.get('merge', {}).get('requirements', {}).get('precedence', ()))
    if engine != REQUIREMENT_VERDICTS:
        msg = (
            f'{method_toml} [merge.requirements] precedence is {list(engine)}; dev-lab combines the slices by '
            f'{list(REQUIREMENT_VERDICTS)} (forgereview_findings.REQUIREMENT_VERDICTS): one order, change both'
        )
        raise AssertionError(msg)
