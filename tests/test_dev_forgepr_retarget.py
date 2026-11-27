"""dev-lab #1003: a landing that deletes a base branch first moves every PR stacked on it; ``forge pr retarget``.

GitHub CLOSES a PR whose base branch is deleted, and a closed PR whose base is gone cannot be reopened. The stateful
fake forge answers as GitHub does; the evidence is each child's base and its one comment, and every refusal has a
planted control (the same call with the missing condition supplied goes through).
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

import pytest
from _forge_state import StateForge

from dev_lab.dev import _forgecli_args, forgepr
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgemergecall import merge

if TYPE_CHECKING:
    from pathlib import Path

_SHA = 'a' * 40
_MANIFEST = (
    "[tool.dev_lab.integrator]\nintegration = 'integrate/main'\n"
    "[tool.dev_lab.branchset]\ntrunk = 'main'\nsessions = ['integrate/main']\nephemeral = ['pr/*']\n"
)


def _stack() -> tuple[StateForge, int, int, int]:
    """GitHub: ``pr/a`` into integration, ``pr/b`` stacked on ``pr/a``, and an unrelated ``pr/c``."""
    github = StateForge(Forge('github.com', 'o', 'r'))
    parent = github.add_pull('pr/a', 'integrate/main', sha=_SHA)
    child = github.add_pull('pr/b', 'pr/a', sha='b' * 40)
    other = github.add_pull('pr/c', 'integrate/main', sha='c' * 40)
    return github, parent, child, other


def test_a_landing_that_deletes_its_head_first_moves_the_stacked_prs_onto_its_base() -> None:
    github, parent, child, other = _stack()
    merge(github, parent, head=_SHA, message='subject\n\nbody', delete_branch=True)
    assert github.pulls[child]['base']['ref'] == 'integrate/main'
    assert github.pulls[child]['state'] == 'open'
    (said,) = (c['body'] for c in github.comments[child])
    assert f'#{parent}' in said
    assert 'PRS-TARGET-INTEGRATION' in said
    assert github.comments[other] == [], 'a PR not stacked on the landed head is untouched'
    assert github.deleted_refs == ['pr/a']
    patched = github.asked.index(f'PATCH {github.repo}/pulls/{child}')
    assert patched < github.asked.index(f'DELETE {github.repo}/git/refs/heads/pr/a'), 'moved BEFORE the delete'


def test_a_landing_that_keeps_its_head_moves_nothing() -> None:
    """PLANTED CONTROL: the same stack landed without the delete keeps its child on the (still living) head."""
    github, parent, child, _ = _stack()
    merge(github, parent, head=_SHA, message='subject\n\nbody', delete_branch=False)
    assert github.pulls[child]['base']['ref'] == 'pr/a'
    assert github.comments[child] == []


def test_retarget_refuses_an_undeclared_base_before_any_call() -> None:
    """PLANTED CONTROL: the same move onto the integration branch goes through."""
    github, _, child, _ = _stack()
    with pytest.raises(ValueError, match='PRS-TARGET-INTEGRATION'):
        forgepr.pr_retarget(github, child, 'pr/c', allowed={'integrate/main', 'main'}, reason='x')
    assert github.asked == []
    moved = forgepr.pr_retarget(github, child, 'integrate/main', allowed={'integrate/main', 'main'}, reason='why')
    assert moved.base == 'integrate/main'
    assert [c['body'] for c in github.comments[child]] == ['retargeted onto `integrate/main`: why']


@pytest.mark.parametrize(('base', 'refused'), [('integrate/main', ''), ('main', ''), ('pr/a', 'refused')])
def test_the_cli_door_admits_only_the_integration_or_a_declared_base(tmp_path: Path, base: str, refused: str) -> None:
    (tmp_path / 'pyproject.toml').write_text(_MANIFEST, encoding='utf-8')
    args = argparse.Namespace(noun='pr', verb='retarget', number=7, base=base, reason='why')
    said = forgepr.retarget_refusal(args.number, args.base, forgepr.declared_bases(tmp_path))
    assert bool(said) is bool(refused)
    parsed = _forgecli_args.parser().parse_args(['pr', 'retarget', '7', '--base', base, '--reason', 'why'])
    assert (parsed.number, parsed.base, parsed.reason) == (7, base, 'why')
