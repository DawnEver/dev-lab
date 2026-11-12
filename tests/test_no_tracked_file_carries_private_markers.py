"""A published repo: no tracked file may name a machine, a person, a home path or a chat id.

The scan is the kit's `dev_lab.dev.privatemarkers`; it runs under `make verify` (and so in CI) because verify
runs this suite. The machine-local denylist `~/.claude/private-markers` adds this host's private
values without committing them.
"""

from __future__ import annotations

import io
from pathlib import Path

import lab_commons.launch as _door
import pytest

from dev_lab.dev import forgecli, privatemarkers
from dev_lab.dev.forgecli import issue_and_pr
from dev_lab.dev.privatemarkers import load_markers, scan_text, scan_tree

_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    'planted',
    [
        # Assembled from halves so this file does not plant a hit in the tree scan below.
        'see C:' + r'\Users\someone\repo',
        'cd /' + 'Users/someone/src',
        'cd /' + 'home/someone/src',
        'mail person' + '@university.ac.uk now',
        'chat -100' + '1234567890',
        'D:' + r'\OneDrive' + ' - Some Org',
    ],
)
def test_a_planted_private_value_is_found(planted: str) -> None:
    assert scan_text(planted), planted


@pytest.mark.parametrize(
    'clean',
    [
        r'C:\Users\<user>\repo',
        '/Users/<user>/src and $HOME/x',
        'user@example.com, git@forge.example.org, a@b.invalid, 1+x@users.noreply.github.com',
        r"'import pytest\n@pytest.mark.xfail'",
        'OneDrive - <Org>',
        'chat -100 or -100123',
    ],
)
def test_a_neutral_value_is_not_found(clean: str) -> None:
    assert scan_text(clean) == [], clean


def test_the_private_denylist_reads_literals_regexes_and_comments(tmp_path: Path) -> None:
    markers = tmp_path / 'private-markers'
    markers.write_text('# a comment\n\nSecretHost\n/proj-\\d+/\n', encoding='utf-8')
    compiled = load_markers(markers)
    assert len(compiled) == 2
    assert scan_text('on secrethost today', compiled) == [(1, 'private marker', '<redacted>')]
    assert scan_text('see PROJ-42', compiled) == [(1, 'private marker', '<redacted>')]
    assert scan_text('a comment, proj-x', compiled) == []


def test_an_absent_denylist_is_silent(tmp_path: Path) -> None:
    assert load_markers(tmp_path / 'missing') == ()


def test_no_tracked_file_carries_a_private_marker() -> None:
    hits = scan_tree(_ROOT, load_markers())
    assert hits == [], 'private values in tracked files:\n' + '\n'.join(hits)


def test_only_the_declared_authorship_lines_may_name_the_author(tmp_path: Path) -> None:
    """The author is named on purpose in LICENSE and pyproject; the same name anywhere else still reds."""
    markers = tmp_path / 'private-markers'
    markers.write_text('Jane Author\n', encoding='utf-8')
    compiled = load_markers(markers)
    assert scan_text('Copyright (c) 2026 Jane Author', compiled, path='LICENSE') == []
    assert scan_text('authors = [{ name = "Jane Author" }]', compiled, path='pyproject.toml') == []
    assert scan_text('Copyright (c) 2026 Jane Author', compiled, path='README.md')
    assert scan_text('# by Jane Author', compiled, path='pyproject.toml')
    assert scan_text('authors = [{ name = "J", email = "j' + '@uni.ac.uk" }]', (), path='pyproject.toml')


def test_the_apache_appendix_copyright_line_is_an_authorship_line(tmp_path: Path) -> None:
    """Apache-2.0's appendix indents the notice; the shape is the same line, and only in LICENSE."""
    markers = tmp_path / 'private-markers'
    markers.write_text('Jane Author\n', encoding='utf-8')
    compiled = load_markers(markers)
    assert scan_text('   Copyright (c) 2026 Jane Author', compiled, path='LICENSE') == []
    assert scan_text('   Copyright (c) 2026 Jane Author', compiled, path='NOTICE.md')


def test_a_name_the_repo_publishes_on_purpose_is_masked_and_nothing_else_is(tmp_path: Path) -> None:
    """A published repo's OWN name cannot be private to it; a marker inside that name still fires elsewhere."""
    markers = tmp_path / 'private-markers'
    markers.write_text('some\n/other[-_]repo/\nSecretHost\n', encoding='utf-8')
    compiled = load_markers(markers)
    public = ('some-repo', 'other_repo')
    assert scan_text('some-repo and OTHER_REPO', compiled, public=public) == []
    assert scan_text('some-repo by some person', compiled, public=public) == [(1, 'private marker', '<redacted>')]
    assert scan_text('other-repo', compiled, public=public) == [(1, 'private marker', '<redacted>')]


def test_a_home_named_after_a_public_name_is_a_service_account_and_not_a_person() -> None:
    """``/home/<repo>`` is a deploy user named after the published repo; any other home still reds."""
    assert scan_text('cd /' + 'home/some-repo/lib', public=('some-repo',)) == []
    assert scan_text('cd /' + 'home/someone/lib', public=('some-repo',))


def test_a_diff_marker_before_a_decorator_is_not_an_address() -> None:
    """A local part needs a letter or digit first: ``+@pytest.mark`` is a diff line, not an e-mail."""
    assert scan_text('+@pytest' + '.mark.parametrize') == []
    assert scan_text('x+tag@' + 'uni.ac.uk')


def _staged_repo(root: Path, committed: str, staged: str) -> list[str]:
    """A repo whose `note.md` holds *committed* at HEAD and *staged* in the index; returns the entry's argv."""

    def git(*args: str) -> None:
        _door.run(['git', *args], cwd=root, check=True, capture_output=True)

    git('init', '-q')
    git('config', 'user.email', 'a@example.com')
    git('config', 'user.name', 'a')
    (root / 'note.md').write_text(committed, encoding='utf-8')
    git('add', 'note.md')
    git('commit', '-q', '-m', 'base')
    (root / 'note.md').write_text(staged, encoding='utf-8')
    git('add', 'note.md')
    denylist = root / 'private-markers'
    denylist.write_text('SecretHost\n', encoding='utf-8')
    return ['--root', str(root), '--markers', str(denylist), 'note.md']


def test_the_pre_commit_entry_refuses_an_added_marker_without_echoing_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """PRIVATE-MARKERS at commit time: the forge has no denylist, so only this machine can refuse the commit."""
    argv = _staged_repo(tmp_path, 'clean\n', 'clean\nreached secrethost today\n')
    assert privatemarkers.main(argv) == 1
    out = capsys.readouterr()
    assert 'note.md:2: private marker' in out.err
    assert 'secrethost' not in (out.err + out.out).lower()


def test_the_pre_commit_entry_judges_only_the_added_lines(tmp_path: Path) -> None:
    """A legacy hit on an untouched line is not this commit's: refusing it would block every edit to that file."""
    argv = _staged_repo(tmp_path, 'old secrethost line\nclean\n', 'old secrethost line\nclean, edited\n')
    assert privatemarkers.main(argv) == 0


def test_the_pre_commit_entry_passes_when_the_denylist_is_absent(tmp_path: Path) -> None:
    """The forge and every other machine have no denylist: the row must then judge the generic layer only."""
    argv = _staged_repo(tmp_path, 'clean\n', 'reached secrethost today\n')
    argv[3] = str(tmp_path / 'missing')
    assert privatemarkers.main(argv) == 0


def _committed_repo(root: Path, message: str) -> tuple[str, str]:
    """A repo with a clean base commit and one commit carrying *message*; the two shas."""

    def git(*args: str) -> str:
        return _door.run(['git', *args], cwd=root, check=True, capture_output=True).stdout.decode().strip()

    git('init', '-q')
    git('config', 'user.email', 'a@example.com')
    git('config', 'user.name', 'a')
    git('commit', '-q', '--allow-empty', '-m', 'base')
    base = git('rev-parse', 'HEAD')
    git('commit', '-q', '--allow-empty', '-m', message)
    return base, git('rev-parse', 'HEAD')


@pytest.mark.parametrize(('message', 'refused'), [('fix: reached secrethost today', True), ('fix: clean', False)])
def test_the_pre_push_entry_refuses_a_pushed_commit_message_with_a_marker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], message: str, *, refused: bool
) -> None:
    """A commit message is published with the push: the clean message is the PLANTED CONTROL."""
    base, head = _committed_repo(tmp_path, message)
    denylist = tmp_path / 'private-markers'
    denylist.write_text('SecretHost\n', encoding='utf-8')
    lines = io.StringIO(f'refs/heads/x {head} refs/heads/x {base}\n')
    argv = ['--root', str(tmp_path), '--markers', str(denylist), '--push']
    assert privatemarkers.main(argv, stdin=lines) == (1 if refused else 0)
    out = capsys.readouterr()
    assert ('message' in out.err) is refused
    assert 'secrethost' not in (out.err + out.out).lower()


def test_a_new_branch_push_judges_only_the_commits_no_remote_holds(tmp_path: Path) -> None:
    """A new ref's remote sha is all zeros: the range is the local head minus what any remote already has."""
    _, head = _committed_repo(tmp_path, 'fix: reached secrethost today')
    assert privatemarkers.pushed_messages(tmp_path, f'refs/heads/x {head} refs/heads/x {"0" * 40}\n')


def test_a_pr_body_with_a_marker_is_refused_by_the_create_door(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The PR body is published the moment the door opens it; the forge call is never made."""
    denylist = tmp_path / 'private-markers'
    denylist.write_text('SecretHost\n', encoding='utf-8')
    monkeypatch.setattr(privatemarkers, 'MARKERS_FILE', denylist)
    argv = ['pr', 'create', '--title', 't', '--body', 'ran on secrethost', '--head', 'x', '--base', 'y']
    assert issue_and_pr(argv, cwd=tmp_path, env={}) == 1
    err = capsys.readouterr().err
    assert 'PRIVATE-MARKERS' in err
    assert 'secrethost' not in err.lower()
    assert privatemarkers.text_refusal('a clean body', 'PR body') is None, 'PLANTED CONTROL'


class _Repo:
    """The forge's answer for one repository: its ``private`` flag, or a read that fails."""

    repo = '/repos/o/r'

    def __init__(self, *, private: bool | None) -> None:
        self.private = private

    def call(self, method: str, path: str) -> dict[str, bool]:
        assert (method, path) == ('GET', self.repo)
        if self.private is None:
            msg = 'forge unreachable'
            raise OSError(msg)
        return {'private': self.private}


def _visible_as(monkeypatch: pytest.MonkeyPatch, *, private: bool | None) -> None:
    monkeypatch.setattr(privatemarkers, '_VISIBILITY', {})
    monkeypatch.setattr(privatemarkers, 'client_for', lambda *_a, **_k: _Repo(private=private))


#: Each visibility the forge can answer, and whether a marker is then refused: public refused, private allowed
#: (that is what a private repo is for), unreadable scanned -- fail closed.
_VISIBILITIES = pytest.mark.parametrize(('private', 'refused'), [(False, True), (True, False), (None, True)])


@_VISIBILITIES
def test_a_pushed_message_is_scanned_unless_the_pushed_to_repo_is_private(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    private: bool | None,
    refused: bool,
) -> None:
    _visible_as(monkeypatch, private=private)
    base, head = _committed_repo(tmp_path, 'fix: reached secrethost today')
    denylist = tmp_path / 'private-markers'
    denylist.write_text('SecretHost\n', encoding='utf-8')
    argv = ['--root', str(tmp_path), '--markers', str(denylist), '--push', '--url', 'https://example.com/o/r.git']
    assert privatemarkers.main(argv, stdin=io.StringIO(f'refs/heads/x {head} refs/heads/x {base}\n')) == int(refused)
    assert ('unreadable' in capsys.readouterr().err) is (private is None)


def test_the_visibility_is_read_once_per_repository(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[bool] = []

    def client(*_a: object, **_k: object) -> _Repo:
        calls.append(True)
        return _Repo(private=True)

    monkeypatch.setattr(privatemarkers, '_VISIBILITY', {})
    monkeypatch.setattr(privatemarkers, 'client_for', client)
    url = 'https://example.com/o/r.git'
    assert privatemarkers.repo_is_private(tmp_path, url=url) == (True, '')
    assert privatemarkers.repo_is_private(tmp_path, url=url) == (True, '')
    assert calls == [True]


@_VISIBILITIES
def test_a_pr_body_with_a_marker_is_refused_only_for_a_public_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    private: bool | None,
    refused: bool,
) -> None:
    """The create door asks the forge first; a private repo's PR may name its private host."""
    _door.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    _door.run(['git', 'remote', 'add', 'origin', 'https://example.com/o/r.git'], cwd=tmp_path, check=True)
    denylist = tmp_path / 'private-markers'
    denylist.write_text('SecretHost\n', encoding='utf-8')
    monkeypatch.setattr(privatemarkers, 'MARKERS_FILE', denylist)
    _visible_as(monkeypatch, private=private)
    if refused:
        argv = ['pr', 'create', '--title', 't', '--body', 'ran on secrethost', '--head', 'x', '--base', 'y']
        assert issue_and_pr(argv, cwd=tmp_path, env={}) == 1
    else:  # past the scan the door opens the PR: stop at the first forge write
        monkeypatch.setattr(forgecli, 'client_for', lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError('opened')))
        argv = ['pr', 'create', '--title', 't', '--body', 'ran on secrethost', '--head', 'x', '--base', 'y']
        with pytest.raises(RuntimeError, match='opened'):
            issue_and_pr(argv, cwd=tmp_path, env={})
    err = capsys.readouterr().err
    assert ('PRIVATE-MARKERS' in err) is refused
    assert ('unreadable' in err) is (private is None)
