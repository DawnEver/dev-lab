"""REVIEW-COMMAND-IS-THE-FAMILY'S: one default review command, a repo declares only where it differs.

Adoption here, plus the planted controls that prove the refusal convicts: a repo that redeclares the family's
command, or a retired host field (``{capabilities.*}``, ``{runtimes.sharp_review.*}``), is refused.
"""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import pytest

from dev_lab.dev.famtests.reviewcommand import (
    assert_the_family_commands_parse,
    assert_the_requirement_precedence_agrees,
    assert_the_review_declares_only_its_difference,
)
from dev_lab.dev.forgereview_declared import (
    FAMILY_COMMAND,
    FAMILY_MODEL,
    LENS_FIELD,
    PATHS_FIELD,
    RANGE_FIELD,
    RULES_FIELD,
    Review,
    command_for,
    review_from,
)
from dev_lab.dev.forgereview_requirements import Required
from dev_lab.dev.forgereview_scope import DISPOSED_FIELD, PRINCIPLES_FIELD, REQUIREMENTS_FIELD, SUMMARY_FIELD, gather
from dev_lab.dev.principles import payload
from dev_lab.dev.rules import RULES

_ROOT = Path(__file__).resolve().parents[1]
_DECLARED = "[tool.dev_lab.review]\ncommand = ['r', '{rules}', '{requirements}']\n"
_HOST = {'ai_lab': {'python': 'C:/rt/python.exe'}}


def test_this_repo_declares_only_its_difference() -> None:
    assert_the_review_declares_only_its_difference(_ROOT)


def test_the_family_command_slices_and_names_one_model() -> None:
    """Undeclared, a repo reviews with the family's command: range, lens and paths, the model one value."""
    review = review_from('', 'p')
    assert review.command == FAMILY_COMMAND
    assert {RANGE_FIELD, LENS_FIELD, PATHS_FIELD} <= set(review.command)
    argv = command_for(review, 'a..b', _HOST, paths=('x.py', 'y.py'), lens='strict')
    assert argv == [
        'C:/rt/python.exe', '-m', 'ai_lab.review', '--range', 'a..b', '--lens', 'strict',
        '--model', FAMILY_MODEL, '--rules', ','.join(rule.id for rule in RULES),
        '--paths', 'x.py', 'y.py', '--principles', PRINCIPLES_FIELD, '--requirements', REQUIREMENTS_FIELD,
        SUMMARY_FIELD, '--disposed', DISPOSED_FIELD,
        '--no-batch',
    ]  # fmt: skip


def test_the_rule_ids_are_given_to_the_method_from_the_registry() -> None:
    """ai-lab imports no registry: ``{rules}`` hands it every id. PLANTED CONTROL: a declared command's too."""
    assert RULES_FIELD in FAMILY_COMMAND
    given = command_for(review_from(_DECLARED, 'p'), 'a..b', _HOST)
    assert given[1].split(',') == [rule.id for rule in RULES]
    assert all(',' not in rule.id for rule in RULES), 'an id with a comma would split in two'


def test_a_repo_overrides_only_the_model_and_still_slices() -> None:
    """A multi-slice head is SLICED, not held: the default carries ``{paths}`` whatever the repo overrides."""
    review = review_from("[tool.dev_lab.review]\nmodel = 'other'\nmax_diff = '5 B'\n", 'p')
    assert PATHS_FIELD in review.command
    assert review.budget.slice_bytes == 5
    assert command_for(review, 'a..b', _HOST, paths=('x.py',))[7:9] == ['--model', 'other']


def test_the_principles_reach_the_method_as_a_file(tmp_path: Path) -> None:
    """``{principles}`` is filled at run time with a JSON file of the family payload, for slices and synthesis."""
    seen: list[object] = []

    def run(argv: Sequence[str], _root: Path) -> str:
        given = Path(argv[list(argv).index('--principles') + 1])
        seen.append(json.loads(given.read_text(encoding='utf-8')))
        raise _Ran

    with pytest.raises(_Ran):
        gather(
            'a..b', [['x', '--principles', PRINCIPLES_FIELD]], (), run, tmp_path, pr_body='', requirements=Required({})
        )
    assert seen == [payload()]


def test_the_requirements_reach_the_method_as_a_file(tmp_path: Path) -> None:
    """D226: ``{requirements}`` is filled at run time with the payload the caller read at the trusted branch.

    PLANTED CONTROL: a different payload reaches the method as that payload, never a constant.
    """
    seen: list[object] = []

    def run(argv: Sequence[str], _root: Path) -> str:
        seen.append(json.loads(Path(argv[list(argv).index('--requirements') + 1]).read_text(encoding='utf-8')))
        raise _Ran

    for given in (
        {'principles': True},
        {'architecture': [{'id': 'arch:A.md', 'path': 'A.md', 'blob': 'b', 'text': 't'}]},
    ):
        with pytest.raises(_Ran):
            gather('a..b', [['x', '--requirements', REQUIREMENTS_FIELD]], (), run, tmp_path, pr_body='',
                   requirements=Required(given))  # fmt: skip
    assert seen == [
        {'principles': True},
        {'architecture': [{'id': 'arch:A.md', 'path': 'A.md', 'blob': 'b', 'text': 't'}]},
    ]


def _slice_doc(**top: object) -> str:
    return json.dumps({
        'schema_version': 3, 'range': 'a..b', 'profiles': ['c'],
        'reviewers': [{'name': 'c', 'provider': 'p', 'status': 'ok', 'dropped_findings': 0}], 'findings': [], **top,
    })  # fmt: skip


def test_one_call_summarizes_with_the_pr_body_and_every_call_is_handed_no_dispositions(tmp_path: Path) -> None:
    """The FIRST slice carries ``--pr-body``; the other slices and the synthesis pass ``--no-summary``.

    PLANTED control: a summary only the first call printed is the merged document's; the rest printed none.
    """
    seen: list[tuple[list[str], str, object]] = []
    summary = {'changes': [{'claim': 'adds x', 'cites': ['abc1234']}]}

    def run(argv: Sequence[str], _root: Path) -> str:
        argv = list(argv)
        body = Path(argv[argv.index('--pr-body') + 1]).read_text(encoding='utf-8') if '--pr-body' in argv else ''
        gone = json.loads(Path(argv[argv.index('--disposed') + 1]).read_text(encoding='utf-8'))
        seen.append((argv, body, gone))
        return _slice_doc(summary=summary) if body else _slice_doc()

    shape = ['r', SUMMARY_FIELD, '--disposed', DISPOSED_FIELD]
    merged = gather('a..b', [shape, shape], ['s', '{findings}', *shape], run, tmp_path,
                    pr_body='Why: x.', requirements=Required({}))  # fmt: skip
    assert [body for _, body, _ in seen] == ['Why: x.', '', '']
    assert ['--no-summary' in argv for argv, _, _ in seen] == [False, True, True]
    assert all(gone == {'disposed': []} for _, _, gone in seen), 'nothing is disposed of in a one-shot review'
    assert json.loads(merged)['summary'] == summary


class _Ran(Exception):
    """The run stub stops ``gather`` once it has read the file it was handed."""


def test_the_identical_command_redeclared_is_refused() -> None:
    """PLANTED: the family command copied into a repo is the stale copy this rule retires."""
    copied = ', '.join(f'"{arg}"' for arg in FAMILY_COMMAND)
    with pytest.raises(ValueError, match='redeclares the family'):
        review_from(f'[tool.dev_lab.review]\ncommand = [{copied}]\n', 'p')


def test_a_retired_capability_is_refused_naming_its_replacement() -> None:
    """PLANTED: ``{capabilities.sharp_review.path}`` is retired; ai-lab packages the method."""
    stale = "command = ['{runtimes.ai_lab.python}', '--method', '{capabilities.sharp_review.path}', '{range}']"
    with pytest.raises(ValueError, match=r'sharp_review.*retired'):
        review_from(f'[tool.dev_lab.review]\n{stale}\n', 'p')


def test_a_capability_field_is_retired_into_a_runtime_field() -> None:
    """PLANTED: a host value is where a runtime lives, never a capability (user ruling 2026-10-28)."""
    stale = "command = ['{capabilities.corpus.path}', '{range}']"
    with pytest.raises(ValueError, match=r'\{capabilities\.corpus\.path\} is retired: \{runtimes\.corpus\.path\}'):
        review_from(f'[tool.dev_lab.review]\n{stale}\n', 'p')


def test_a_genuinely_different_command_is_kept() -> None:
    """Control: a repo whose method differs may declare it."""
    assert review_from("[tool.dev_lab.review]\ncommand = ['r', '{range}', '{requirements}']\n", 'p').command == (
        'r',
        '{range}',
        '{requirements}',
    )


def test_the_planted_manifest_is_convicted_by_the_famtest(tmp_path: Path) -> None:
    """The famtest itself goes RED on a planted stale copy, GREEN on a model-only override."""
    (tmp_path / 'pyproject.toml').write_text("[tool.dev_lab.review]\nmodel = 'm'\n", encoding='utf-8')
    assert_the_review_declares_only_its_difference(tmp_path)
    assert Review().command == FAMILY_COMMAND
    bad = "[tool.dev_lab.review]\ncommand = ['x', '--method', '{capabilities.sharp_review.path}']\n"
    (tmp_path / 'pyproject.toml').write_text(bad, encoding='utf-8')
    with pytest.raises(AssertionError, match='sharp_review'):
        assert_the_review_declares_only_its_difference(tmp_path)


# --- the engine side of the contract (review items 2 and 7 on #1121): ai-lab runs these over its own code ---------


def _engine(*, takes_requirements: bool) -> argparse.ArgumentParser:
    """A stand-in of the engine's parser: every flag the family commands hand it, ``--requirements`` optionally."""
    parser = argparse.ArgumentParser(exit_on_error=False)  # an unknown flag raises, as the famtest names it
    given = parser.add_mutually_exclusive_group(required=True)
    given.add_argument('--range')
    given.add_argument('--bundle')
    for flag in ('--lens', '--model', '--rules', '--principles', '--disposed'):
        parser.add_argument(flag)
    parser.add_argument('--paths', nargs='*')
    parser.add_argument('--no-summary', action='store_true')
    parser.add_argument('--no-batch', action='store_true')
    if takes_requirements:
        parser.add_argument('--requirements', required=True)
    return parser


def test_the_family_commands_parse_with_an_engine_that_takes_them() -> None:
    """PLANTED CONTROL: an engine without ``--requirements`` (ai-lab before #72) is named as the drift."""
    assert_the_family_commands_parse(_engine(takes_requirements=True).parse_args)
    with pytest.raises(AssertionError, match='the engine does not take FAMILY_COMMAND'):
        assert_the_family_commands_parse(_engine(takes_requirements=False).parse_args)


def test_the_requirement_precedence_is_one_order_on_both_sides(tmp_path: Path) -> None:
    """PLANTED CONTROL: an engine combining in another order is refused, naming both orders."""
    method = tmp_path / 'method.toml'
    order = '["violated", "amended", "unverified", "met", "untouched"]'
    method.write_text(f'[merge.requirements]\nprecedence = {order}\n', encoding='utf-8')
    assert_the_requirement_precedence_agrees(method)
    method.write_text('[merge.requirements]\nprecedence = ["amended", "violated", "unverified", "met", "untouched"]\n',
                      encoding='utf-8')  # fmt: skip
    with pytest.raises(AssertionError, match='one order, change both'):
        assert_the_requirement_precedence_agrees(method)


#: The first ai-lab commit count (its version's ``devN``) that can take ``--requirements``: the count of the commit
#: that added it (7851d06, 468) plus one, a LOWER BOUND until the lock bump records the merge of ai-lab #72.
_AI_LAB_TAKES_REQUIREMENTS: Final = 469


@pytest.mark.xfail(
    strict=True,
    reason='uv.lock pins ai-lab 732194db (dev464), before --requirements: the lock bump to the merge of ai-lab #72 '
    'is the last commit of dev-lab #1121, and it removes this marker (a strict xfail turns red once it passes)',
)
def test_the_lock_pins_an_ai_lab_that_takes_the_family_commands() -> None:
    """Review item 2: FAMILY_COMMAND hands ``--requirements``, so the ai-lab the lock pins must take it.

    The pinned ai-lab is not importable here (the ``review`` group is not installed), so its version's commit count
    is the reading: ``0.0.1.devN+g<sha>``, N counting the commits of that ai-lab.
    """
    lock = tomllib.loads((_ROOT / 'uv.lock').read_text(encoding='utf-8'))
    (pinned,) = [one['version'] for one in lock['package'] if one['name'] == 'ai-lab']
    found = re.fullmatch(r'.*\.dev(\d+)\+g[0-9a-f]+', pinned)
    assert found is not None, pinned
    assert int(found[1]) >= _AI_LAB_TAKES_REQUIREMENTS, f'uv.lock pins ai-lab {pinned}'
