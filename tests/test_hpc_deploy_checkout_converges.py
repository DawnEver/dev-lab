"""The deploy's ``checkouts`` step converges a checkout on its declared ref, whatever an interrupted deploy left.

MEASURED 2026-11-22: a first deploy's clone hit the file quota mid-checkout, leaving a ``.git`` and a partial work
tree git saw as untracked; every later ``git checkout -B`` exited 1 ("untracked working tree files would be
overwritten") and the repo was skipped by every later step, forever. PLANTED CONTROLS: a commit the ref does not
have, and a modified tracked file, are the account's own -- kept, and refused by name.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from _forge_fake import git_out, run_git

from dev_lab.dev.hpcaccount import steps
from dev_lab.dev.hpcaccount.steps import Step, Tools

_WHO = ('-c', 'user.name=Example', '-c', 'user.email=example@example.org')
REF = 'trunk'


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    """An origin whose ``trunk`` holds ``a.txt`` and ``pkg/b.txt``."""
    made = tmp_path / 'origin'
    (made / 'pkg').mkdir(parents=True)
    run_git(made, 'init', '-q', '-b', REF)
    (made / 'a.txt').write_text('declared a\n', encoding='utf-8')
    (made / 'pkg' / 'b.txt').write_text('declared b\n', encoding='utf-8')
    run_git(made, 'add', '.')
    run_git(made, *_WHO, 'commit', '-q', '-m', 'the declared ref')
    return made


def _update(tmp_path: Path, origin: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[int, Path]:
    checkout = tmp_path / 'root' / 'repos' / 'example'
    monkeypatch.setattr(steps, 'checkout_of', lambda _spec, _repo: checkout)
    repo = SimpleNamespace(name='example', url=origin.as_uri(), ref=REF)
    return steps.update(Step(Tools(), dry=False), None, tmp_path, repo), checkout  # type: ignore[arg-type]


def _cloned(tmp_path: Path, origin: Path, *flags: str) -> Path:
    checkout = tmp_path / 'root' / 'repos' / 'example'
    checkout.parent.mkdir(parents=True)
    run_git(tmp_path, 'clone', '-q', *flags, '-b', REF, origin.as_uri(), str(checkout))
    return checkout


def _is_the_ref(checkout: Path, origin: Path) -> None:
    assert git_out(checkout, 'rev-parse', 'HEAD') == git_out(origin, 'rev-parse', REF)
    assert (checkout / 'a.txt').read_text(encoding='utf-8') == 'declared a\n'
    assert (checkout / 'pkg' / 'b.txt').read_text(encoding='utf-8') == 'declared b\n'
    assert git_out(checkout, 'status', '--porcelain', '--untracked-files=no') == ''


def test_a_clone_that_died_mid_checkout_is_made_the_declared_ref(
    tmp_path: Path, origin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = _cloned(tmp_path, origin, '--no-checkout')  # a .git, no index, no work tree: the measured shape
    (checkout / 'a.txt').write_text('half-written', encoding='utf-8')  # what the dying checkout left: untracked
    (checkout / 'output').mkdir()  # PLANTED CONTROL: an untracked entry that is in nothing's way stays
    assert git_out(checkout, 'ls-files') == ''
    code, _ = _update(tmp_path, origin, monkeypatch)
    assert code == 0
    _is_the_ref(checkout, origin)
    assert (checkout / 'output').is_dir()


def test_a_git_directory_git_cannot_read_is_cloned_again(
    tmp_path: Path, origin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / 'root' / 'repos' / 'example'
    (checkout / '.git').mkdir(parents=True)
    (checkout / '.git' / 'HEAD').write_text('', encoding='utf-8')
    code, _ = _update(tmp_path, origin, monkeypatch)
    assert code == 0
    _is_the_ref(checkout, origin)


def test_a_checkout_behind_its_ref_follows_it(tmp_path: Path, origin: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    checkout = _cloned(tmp_path, origin)
    (origin / 'a.txt').write_text('declared a, moved\n', encoding='utf-8')
    run_git(origin, *_WHO, 'commit', '-q', '-am', 'the ref moves')
    code, _ = _update(tmp_path, origin, monkeypatch)
    assert code == 0
    assert git_out(checkout, 'rev-parse', 'HEAD') == git_out(origin, 'rev-parse', REF)
    assert (checkout / 'a.txt').read_text(encoding='utf-8') == 'declared a, moved\n'


def test_a_local_commit_ahead_of_the_ref_is_kept_and_refused_by_name(
    tmp_path: Path, origin: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    checkout = _cloned(tmp_path, origin)
    (checkout / 'mine.txt').write_text('mine\n', encoding='utf-8')
    run_git(checkout, 'add', 'mine.txt')
    run_git(checkout, *_WHO, 'commit', '-q', '-m', 'a commit of the account')
    mine = git_out(checkout, 'rev-parse', 'HEAD')
    code, _ = _update(tmp_path, origin, monkeypatch)
    assert code == 2
    assert git_out(checkout, 'rev-parse', 'HEAD') == mine, 'the commit is kept'
    said = capsys.readouterr().err
    assert 'example: refused -- ' in said
    assert 'holds 1 commit(s) no origin branch has' in said


def test_a_modified_tracked_file_is_kept_and_refused_by_name(
    tmp_path: Path, origin: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    checkout = _cloned(tmp_path, origin)
    (checkout / 'a.txt').write_text('edited on the account\n', encoding='utf-8')
    code, _ = _update(tmp_path, origin, monkeypatch)
    assert code == 2
    assert (checkout / 'a.txt').read_text(encoding='utf-8') == 'edited on the account\n'
    assert 'holds 1 modified tracked file(s) (a.txt)' in capsys.readouterr().err
