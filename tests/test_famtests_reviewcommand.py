"""REVIEW-COMMAND-IS-THE-FAMILY'S: one default review command, a repo declares only where it differs.

Adoption here, plus the planted controls that prove the refusal convicts: a repo that redeclares the family's
command, or a retired host field (``{capabilities.*}``, ``{runtimes.sharp_review.*}``), is refused.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from dev_lab.dev.famtests.reviewcommand import assert_the_review_declares_only_its_difference
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
from dev_lab.dev.forgereview_scope import DISPOSED_FIELD, PRINCIPLES_FIELD, SUMMARY_FIELD, gather
from dev_lab.dev.principles import payload
from dev_lab.dev.rules import RULES

_ROOT = Path(__file__).resolve().parents[1]
_DECLARED = "[tool.dev_lab.review]\ncommand = ['r', '{rules}']\n"
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
        '--paths', 'x.py', 'y.py', '--principles', PRINCIPLES_FIELD, SUMMARY_FIELD, '--disposed', DISPOSED_FIELD,
    ]  # fmt: skip


def test_the_rule_ids_are_given_to_the_method_from_the_registry() -> None:
    """ai-lab imports no registry: ``{rules}`` hands it every id. PLANTED CONTROL: a declared command's too."""
    assert RULES_FIELD in FAMILY_COMMAND
    given = command_for(review_from(_DECLARED, 'p'), 'a..b', _HOST)
    assert given[1].split(',') == [rule.id for rule in RULES]
    assert all(',' not in rule.id for rule in RULES), 'an id with a comma would split in two'


def test_a_repo_overrides_only_the_model_and_still_slices() -> None:
    """A multi-slice head is SLICED, not held: the default carries ``{paths}`` whatever the repo overrides."""
    review = review_from("[tool.dev_lab.review]\nmodel = 'other'\nmax_diff_bytes = 5\n", 'p')
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
        gather('a..b', [['x', '--principles', PRINCIPLES_FIELD]], (), run, tmp_path, pr_body='', disposed={})
    assert seen == [payload()]


def _slice_doc(**top: object) -> str:
    return json.dumps({
        'schema_version': 3, 'range': 'a..b', 'profiles': ['c'],
        'reviewers': [{'name': 'c', 'provider': 'p', 'status': 'ok', 'dropped_findings': 0}], 'findings': [], **top,
    })  # fmt: skip


def test_one_call_summarizes_with_the_pr_body_and_every_call_is_handed_the_dispositions(tmp_path: Path) -> None:
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
                    pr_body='Why: x.', disposed={'F-1': 'upstream'})  # fmt: skip
    assert [body for _, body, _ in seen] == ['Why: x.', '', '']
    assert ['--no-summary' in argv for argv, _, _ in seen] == [False, True, True]
    assert all(gone == {'disposed': [{'id': 'F-1', 'reason': 'upstream'}]} for _, _, gone in seen)
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
    assert review_from("[tool.dev_lab.review]\ncommand = ['r', '{range}']\n", 'p').command == ('r', '{range}')


def test_the_planted_manifest_is_convicted_by_the_famtest(tmp_path: Path) -> None:
    """The famtest itself goes RED on a planted stale copy, GREEN on a model-only override."""
    (tmp_path / 'pyproject.toml').write_text("[tool.dev_lab.review]\nmodel = 'm'\n", encoding='utf-8')
    assert_the_review_declares_only_its_difference(tmp_path)
    assert Review().command == FAMILY_COMMAND
    bad = "[tool.dev_lab.review]\ncommand = ['x', '--method', '{capabilities.sharp_review.path}']\n"
    (tmp_path / 'pyproject.toml').write_text(bad, encoding='utf-8')
    with pytest.raises(AssertionError, match='sharp_review'):
        assert_the_review_declares_only_its_difference(tmp_path)
