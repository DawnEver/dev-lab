"""``dev_lab.dev.scratch``: SCRATCH-IS-NEVER-COMMITTED on planted trees and real git checkouts."""

from __future__ import annotations

import io
import json
import os
import time

import pytest
from lab_commons import launch

from dev_lab.dev.codeplace import PlacementNotDeclared, declared_placement, stray_refusal
from dev_lab.dev.scratch import (
    SCRATCH_README,
    ScratchCommitted,
    assert_scratch_never_committed,
    discard_scratch,
    main,
    overdue_declared,
    overdue_scratch,
    pending_scratch,
    scratch_reminder,
    staged_scratch,
)

_DAY = 86400.0


def _plant(root, rel: str, *, age_days: float = 0.0) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('x\n', encoding='utf-8')
    stamp = time.time() - age_days * _DAY
    os.utime(path, (stamp, stamp))


def _declare(root, body: str) -> None:
    (root / '.git').mkdir(exist_ok=True)
    (root / 'pyproject.toml').write_text(f'[tool.lab_commons.placement]\n{body}', encoding='utf-8')


def _repo(root) -> None:
    launch.run(['git', 'init', '-q', str(root)], check=True)
    (root / 'pyproject.toml').write_text('[tool.lab_commons.placement]\n', encoding='utf-8')
    launch.run(['git', '-C', str(root), 'add', 'pyproject.toml'], check=True)


def test_only_a_file_older_than_the_limit_is_overdue(tmp_path) -> None:
    _plant(tmp_path, 'scratch/fresh.py', age_days=0.5)
    _plant(tmp_path, 'scratch/sub/old.py', age_days=4.0)
    scratch = tmp_path / 'scratch'
    assert overdue_scratch(scratch, root=tmp_path, max_age_days=3.0) == ['scratch/sub/old.py']
    assert [p for p, _ in pending_scratch(scratch, root=tmp_path)] == ['scratch/sub/old.py', 'scratch/fresh.py']
    assert pending_scratch(tmp_path / 'absent', root=tmp_path) == []


def test_the_readme_anchor_is_never_pending_and_the_rest_is_oldest_first(tmp_path) -> None:
    _plant(tmp_path, f'scratch/{SCRATCH_README}', age_days=30.0)
    _plant(tmp_path, 'scratch/fresh.py', age_days=0.5)
    _plant(tmp_path, 'scratch/sub/old.py', age_days=4.0)
    assert [p for p, _ in pending_scratch(tmp_path / 'scratch', root=tmp_path)] == [
        'scratch/sub/old.py',
        'scratch/fresh.py',
    ]


def test_a_repo_declares_its_scratch_and_its_age_and_both_have_the_family_default(tmp_path) -> None:
    _declare(tmp_path, '')
    assert (declared_placement(tmp_path).scratch, declared_placement(tmp_path).max_age_days) == ('scratch/', 3.0)
    _declare(tmp_path, "scratch = 'tmp/one-offs'\nmax_age_days = 1.5\n")
    placement = declared_placement(tmp_path)
    assert (placement.scratch, placement.max_age_days) == ('tmp/one-offs/', 1.5)
    assert placement.stray_roots[0] == 'tmp/one-offs/'


@pytest.mark.parametrize('body', ["scratch = ['scratch']\n", "max_age_days = 'three'\n", 'max_age_days = 0\n'])
def test_a_malformed_scratch_declaration_is_REFUSED(tmp_path, body) -> None:
    _declare(tmp_path, body)
    with pytest.raises(PlacementNotDeclared):
        declared_placement(tmp_path)


def test_staged_paths_under_scratch_are_refused_except_its_readme() -> None:
    staged = ('src/x.py', 'scratch/README.md', 'scratch/probe.py', 'scratch/sub/run.ps1', 'scratchpad/x.py')
    assert staged_scratch(staged, scratch='scratch/') == ['scratch/probe.py', 'scratch/sub/run.ps1']


def test_the_pre_commit_row_refuses_a_staged_one_off_naming_both_exits(tmp_path, monkeypatch, capsys) -> None:
    _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(['check', 'scratch/README.md', 'src/x.py']) == 0
    assert main(['check', 'scratch/probe.py']) == 1
    out = capsys.readouterr().out
    assert out.startswith('SCRATCH-IS-NEVER-COMMITTED: scratch/probe.py')
    assert 'src/' in out
    assert 'discard' in out


def _commit_all(root) -> None:
    launch.run(['git', '-C', str(root), 'add', '-A'], check=True)
    launch.run(
        ['git', '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'x', '--no-verify'],
        check=True,
    )


def test_the_forge_body_holds_tracked_scratch_to_exactly_its_readme(tmp_path) -> None:
    _repo(tmp_path)
    with pytest.raises(ScratchCommitted, match=r'README.md'):
        assert_scratch_never_committed(tmp_path)  # the anchor is missing: an empty scratch is no green
    _plant(tmp_path, f'scratch/{SCRATCH_README}')
    _commit_all(tmp_path)
    assert_scratch_never_committed(tmp_path)
    _plant(tmp_path, 'scratch/probe.py')  # the planted control: one committed one-off
    _commit_all(tmp_path)
    with pytest.raises(ScratchCommitted, match=r'scratch/probe.py'):
        assert_scratch_never_committed(tmp_path)


def test_an_untracked_scratch_file_is_visible_to_git_and_no_stray(tmp_path) -> None:
    _repo(tmp_path)
    _plant(tmp_path, 'scratch/probe.py')
    status = launch.run(
        ['git', '-C', str(tmp_path), 'status', '--porcelain', '-uall'], capture_output=True, text=True, encoding='utf-8'
    )
    assert '?? scratch/probe.py' in status.stdout
    assert stray_refusal(tmp_path) is None


def test_the_reminder_names_each_overdue_file_and_both_exits_and_is_silent_otherwise(tmp_path, capsys) -> None:
    _repo(tmp_path)
    _plant(tmp_path, 'scratch/fresh.py', age_days=0.5)
    assert scratch_reminder(tmp_path) is None
    payload = json.dumps({'hook_event_name': 'SessionStart', 'cwd': str(tmp_path)})
    assert main(['remind'], stdin=io.StringIO(payload)) == 0
    assert capsys.readouterr().out == ''
    _plant(tmp_path, 'scratch/old.py', age_days=4.0)
    assert overdue_declared(tmp_path) == ['scratch/old.py']
    assert main(['remind'], stdin=io.StringIO(payload)) == 0
    out = capsys.readouterr().out
    assert 'scratch/old.py' in out
    assert 'fresh.py' not in out
    assert 'src/' in out
    assert 'discard' in out


def test_pending_lists_oldest_first_and_discard_deletes_only_scratch_one_offs(tmp_path, monkeypatch, capsys) -> None:
    _repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    _plant(tmp_path, f'scratch/{SCRATCH_README}', age_days=9.0)
    _plant(tmp_path, 'scratch/a.py', age_days=1.0)
    _plant(tmp_path, 'scratch/b.py', age_days=5.0)
    _plant(tmp_path, 'src/keep.py')
    assert main(['pending']) == 0
    rows = capsys.readouterr().out.splitlines()
    assert [row.split()[-1] for row in rows] == ['scratch/b.py', 'scratch/a.py']
    with pytest.raises(ValueError, match=r'src/keep.py'):
        discard_scratch(['src/keep.py'], root=tmp_path)
    with pytest.raises(ValueError, match='README'):
        discard_scratch([f'scratch/{SCRATCH_README}'], root=tmp_path)
    assert main(['discard', 'scratch/b.py', str(tmp_path / 'scratch' / 'a.py')]) == 0
    assert not (tmp_path / 'scratch/a.py').exists()
    assert not (tmp_path / 'scratch/b.py').exists()
    assert (tmp_path / 'src/keep.py').exists()
    assert main(['discard', 'src/keep.py']) == 2
    assert (tmp_path / 'src/keep.py').exists()


def test_an_undeclared_checkout_is_not_judged_by_the_row_and_a_verb_says_why(tmp_path, monkeypatch, capsys) -> None:
    (tmp_path / '.git').mkdir()
    monkeypatch.chdir(tmp_path)
    assert main(['check', 'scratch/probe.py']) == 0
    assert main(['pending']) == 2
    assert 'pyproject.toml' in capsys.readouterr().out
    assert main(['bogus']) == 2
