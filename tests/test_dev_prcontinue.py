"""LANDED-BRANCH-CONTINUES: a push onto a merged PR's branch is carried by a continuation PR the forge opens.

User-approved design 2026-11-07: the merged PR is never reused. Both forges run :func:`continue_landed` -- Gitea in
the serve tick's repo-wide pass, before any prune, GitHub in ``continue.yml`` -- and every behaviour has its planted
control.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from _branch_repos import advance, clone_pair
from _forge_fake import run_git
from _forge_state import StateForge

from dev_lab.dev import forgeservesteps, prcontinue
from dev_lab.dev.branchreview import read_record
from dev_lab.dev.ciworkflows import workflows
from dev_lab.dev.forge import Forge
from dev_lab.dev.prcontinue import candidates, continuation, continue_landed, continues_title

_ROOT = Path(__file__).resolve().parents[1]
_BASE = 'integrate/main'
_OLD = 'a' * 40
_TIP = 'b' * 40


def _merged(forge: StateForge, branch: str = 'pr/x', *, title: str = 'feat: x', sha: str = _OLD) -> int:
    number = forge.add_pull(branch, _BASE, title=title, sha=sha)
    forge._merge(number, {})
    return number


def _opened(forge: StateForge, branches: dict[str, str]) -> list[int]:
    said: list[str] = []
    return [pull.number for pull in continue_landed(forge, branches, integration=_BASE, say=said.append)]


# --- which branch continues ------------------------------------------------------------------------------


def test_only_a_merged_pr_whose_head_moved_is_continued() -> None:
    forge = StateForge()
    landed = _merged(forge)
    found = continuation(forge, 'pr/x', _BASE, _TIP)
    assert found is not None
    assert found.number == landed
    assert continuation(forge, 'pr/x', _BASE, _OLD) is None, 'PLANTED CONTROL: the landed head itself, nothing new'


@pytest.mark.parametrize('state', ['open', 'closed'])
def test_an_open_or_closed_unmerged_newest_pr_is_not_continued(state: str) -> None:
    forge = StateForge()
    _merged(forge)
    newest = forge.add_pull('pr/x', _BASE, sha=_OLD)
    forge._edit_pull(newest, {'state': state})
    assert continuation(forge, 'pr/x', _BASE, _TIP) is None


# --- what the forge opens ---------------------------------------------------------------------------------


@pytest.mark.parametrize('host', ['forge.example.org', 'github.com'])
def test_the_continuation_is_a_new_pr_saying_continues_and_chained_in_the_record(host: str) -> None:
    forge = StateForge(Forge(host, 'o', 'r'))
    landed = _merged(forge)
    [number] = _opened(forge, {'pr/x': _TIP})
    assert number != landed, 'the merged PR object is never reused'
    pull = forge.pr_view(number)
    assert (pull.head, pull.base, pull.state, pull.draft) == ('pr/x', _BASE, 'open', False)
    assert pull.title == f'feat: x (continues #{landed})'
    assert pull.body.startswith(f'Continues #{landed}')
    assert forge.pulls[landed]['merged'] is True, 'the landed PR stays as it was'
    assert read_record(forge, 'pr/x').prs == (landed, number)


def test_a_second_pass_opens_nothing_more() -> None:
    forge = StateForge()
    _merged(forge)
    assert len(_opened(forge, {'pr/x': _TIP})) == 1
    assert _opened(forge, {'pr/x': _TIP}) == [], 'its newest PR is the open continuation now'


def test_a_continuation_of_a_continuation_names_its_own_predecessor_alone() -> None:
    forge = StateForge()
    first = _merged(forge)
    [second] = _opened(forge, {'pr/x': _TIP})
    forge.pulls[second]['head']['sha'] = _TIP
    forge._merge(second, {})
    [third] = _opened(forge, {'pr/x': 'c' * 40})
    assert forge.pr_view(third).title == f'feat: x (continues #{second})'
    assert continues_title(forge.pr_view(first)) == f'feat: x (continues #{first})'
    assert read_record(forge, 'pr/x').prs == (first, second, third)


# --- the Gitea serve tick's candidates ----------------------------------------------------------------------


def test_candidates_are_unlanded_branches_without_an_open_pr(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    grown = advance(work, 'pr/grown', 'g.py', 'g\n')
    advance(work, 'pr/open', 'o.py', 'o\n')
    landed = advance(work, 'pr/landed', 'l.py', 'l\n')
    run_git(work, 'push', '-q', '--no-verify', 'origin', f'{landed}:refs/heads/{_BASE}')
    run_git(work, 'fetch', '-q', 'origin')
    found = candidates(work, integration=_BASE, trunk='main', open_heads=frozenset({'pr/open'}))
    assert found == {'pr/grown': grown}, 'PLANTED CONTROLS: an open PR`s head and a contained tip are not asked'


def test_the_serve_pass_opens_continuations_before_anything_prunes(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    for name in ('serve_close_landed', 'serve_sweep', 'serve_prune', 'serve_records_prune', 'hygiene', 'starved',
                 'prompt', 'relock', 'drift_step'):  # fmt: skip
        monkeypatch.setattr(forgeservesteps, name, lambda *_a, _n=name, **_k: order.append(_n))
    monkeypatch.setattr(forgeservesteps, 'serve_continue_landed', lambda *_a, **_k: order.append('continue'))
    monkeypatch.setattr(forgeservesteps, 'ci_merges', lambda _root: False)
    forgeservesteps.repo_wide(
        Path(), 'r', lambda _root: StateForge(), 'box', (), clock=lambda: None, say=lambda _s: None,
        alarm=lambda _a: None,
    )  # fmt: skip
    assert order[0] == 'continue'
    assert order.index('continue') < order.index('serve_prune') < order.index('relock')


def test_a_serve_pass_that_cannot_read_alarms_and_never_raises(tmp_path: Path) -> None:
    raised: list[object] = []
    forge = StateForge()
    forge.fail_lists = True
    prcontinue.serve_continue_landed(tmp_path, forge, say=lambda _s: None, alarm=raised.append)
    assert len(raised) == 1


# --- GitHub's continue.yml: the PR the job token opens gets its CI by dispatch -----------------------------


def _continue_job() -> dict[str, Any]:
    return workflows(_ROOT)['continue.yml']['jobs']['continue']


def _opened_says(tmp_path: Path, said: str) -> dict[str, str]:
    """Run the rendered ``continue`` step with a door that says *said*; the step outputs it wrote."""
    (step,) = [one for one in _continue_job()['steps'] if one.get('id') == 'continue']
    tmp_path.mkdir()
    door = tmp_path / 'door'
    door.write_bytes(b'#!/bin/sh\ncat "$SAID_FILE"\n')
    door.chmod(0o755)
    (tmp_path / 'said').write_text(said, encoding='utf-8')
    output = tmp_path / 'output'
    output.write_text('', encoding='utf-8')
    bash = shutil.which('bash')
    assert bash, 'the continue step is bash'
    env = {
        **os.environ, 'REVIEW_PYTHON': door.as_posix(), 'SAID_FILE': (tmp_path / 'said').as_posix(),
        'GITHUB_OUTPUT': output.as_posix(), 'GITHUB_REF_NAME': 'pr/x', 'GITHUB_SHA': _TIP,
    }  # fmt: skip
    subprocess.run([bash, '-c', step['run']], env=env, check=True, cwd=tmp_path)
    return dict(line.split('=', 1) for line in output.read_text(encoding='utf-8').splitlines())


def test_continue_yml_dispatches_ci_on_the_branch_for_the_pr_it_opened(tmp_path: Path) -> None:
    """A PR the job token opens starts no workflow: the same job dispatches ci.yml on its branch with its number.

    The door's own line (:func:`continue_landed`'s say) names the PR, and the dispatch step runs on that output.
    PLANTED CONTROL: no PR opened, no number, so the dispatch step's condition is false.
    """
    forge = StateForge()
    landed = _merged(forge)
    said: list[str] = []
    [pull] = continue_landed(forge, {'pr/x': _TIP}, integration=_BASE, say=said.append)
    assert _opened_says(tmp_path / 'opened', '\n'.join(said) + '\n') == {'pr': str(pull.number)}
    assert pull.number != landed
    steps = _continue_job()['steps']
    names = [one.get('name') for one in steps]
    dispatch = steps[names.index('Run CI on the continuation PR')]
    assert names.index('Open the continuation PR') < names.index('Run CI on the continuation PR')
    assert dispatch['if'] == "${{ steps.continue.outputs.pr != '' }}"
    assert dispatch['env']['PR'] == '${{ steps.continue.outputs.pr }}'
    assert dispatch['run'] == 'gh workflow run ci.yml --repo "$GITHUB_REPOSITORY" --ref "$GITHUB_REF_NAME" -f pr="$PR"'
    assert _continue_job()['permissions'] == {
        'contents': 'read',
        'pull-requests': 'write',
        'issues': 'write',
        'actions': 'write',
    }, 'actions: write dispatches; nothing more'
    nothing = _opened_says(tmp_path / 'none', '[forge] pr continue: no branch continues a merged PR\n')
    assert nothing == {'pr': ''}, 'PLANTED CONTROL: nothing opened, nothing dispatched'
