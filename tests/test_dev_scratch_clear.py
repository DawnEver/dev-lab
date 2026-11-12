"""``dev_lab.dev.scratch list|clear|snapshot|stop``: THIS session's scratch leftovers, the stop and the door for them.

Details: docs-src/dev/refusals.md#recursive-delete.
"""

from __future__ import annotations

import io
import json
import stat
import sys

import pytest
from lab_commons import home, launch

from dev_lab.dev.scratch import SCRATCH_README, ScratchEscape, clear_scratch, main, untracked_scratch
from dev_lab.dev.sessionprs import SESSION_ENV


@pytest.fixture(autouse=True)
def machine_home(tmp_path, monkeypatch) -> None:
    """The session snapshots live under a planted machine home, never the real one."""
    monkeypatch.setenv(home.HOME_ENV, str(tmp_path / 'home'))
    monkeypatch.setenv(SESSION_ENV, 'this-session')


def _hook(verb: str, root, session: str = 'this-session') -> int:
    payload = {'session_id': session, 'cwd': str(root)}
    return main([verb], stdin=io.StringIO(json.dumps(payload)))


def _repo(root) -> None:
    """A MAIN checkout (a real ``.git`` directory) declaring the family scratch, its README tracked."""
    launch.run(['git', 'init', '-q', str(root)], check=True)
    (root / 'pyproject.toml').write_text('[tool.dev_lab.placement]\n', encoding='utf-8')
    (root / 'scratch').mkdir()
    (root / 'scratch' / SCRATCH_README).write_text('anchor\n', encoding='utf-8')
    (root / 'scratch' / 'tracked.txt').write_text('kept\n', encoding='utf-8')
    launch.run(['git', '-C', str(root), 'add', 'pyproject.toml', 'scratch'], check=True)


def _plant(root, rel: str, text: str = 'x\n') -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _nested_repo(root) -> None:
    """A one-off holding its own ``.git``, whose files are made read-only as git makes its objects."""
    nested = root / 'scratch' / 'clone'
    launch.run(['git', 'init', '-q', str(nested)], check=True)
    _plant(nested, 'f.txt')
    launch.run(['git', '-C', str(nested), 'add', 'f.txt'], check=True)
    for path in (nested / '.git').rglob('*'):
        if path.is_file():
            path.chmod(stat.S_IREAD)


def test_list_names_only_untracked_top_level_entries_with_sizes(tmp_path) -> None:
    _repo(tmp_path)
    _plant(tmp_path, 'scratch/probe.py', 'abc')
    _plant(tmp_path, 'scratch/run/a.txt', 'abcd')
    _plant(tmp_path, 'scratch/run/b.txt', 'ef')
    entries = {rel: size for rel, size, _ in untracked_scratch(tmp_path)}
    assert entries == {'scratch/probe.py': 3, 'scratch/run': 6}


def test_the_stop_blocks_only_on_what_this_session_left(tmp_path, capsys) -> None:
    """PLANTED CONTROL: an entry from before the session and another session's entry never block; ours does."""
    _repo(tmp_path)
    _plant(tmp_path, 'scratch/before.py')
    assert _hook('snapshot', tmp_path) == 0
    assert _hook('snapshot', tmp_path, session='other-session') == 0
    _plant(tmp_path, 'scratch/theirs.py')
    assert _hook('snapshot', tmp_path, session='later-session') == 0  # theirs.py predates this one's start
    assert _hook('stop', tmp_path, session='later-session') == 0
    assert capsys.readouterr().out == ''
    _plant(tmp_path, 'scratch/ours/x.txt')
    assert _hook('stop', tmp_path, session='later-session') == 0
    decision = json.loads(capsys.readouterr().out)
    assert decision['decision'] == 'block'
    assert 'scratch/ours' in decision['reason']
    assert 'before.py' not in decision['reason']
    assert 'theirs.py' not in decision['reason']
    assert 'dev_lab.dev.scratch clear' in decision['reason']
    assert '--keep' in decision['reason']


def test_keep_acks_an_entry_so_the_stop_lets_it_stand(tmp_path, monkeypatch, capsys) -> None:
    _repo(tmp_path)
    assert _hook('snapshot', tmp_path) == 0
    _plant(tmp_path, 'scratch/evidence.txt')
    monkeypatch.chdir(tmp_path)
    assert main(['clear', '--keep', 'evidence.txt']) == 0
    capsys.readouterr()
    assert _hook('stop', tmp_path) == 0
    assert capsys.readouterr().out == ''
    assert (tmp_path / 'scratch/evidence.txt').exists()


def test_a_session_with_no_snapshot_takes_one_at_stop_and_is_not_blocked(tmp_path, capsys) -> None:
    _repo(tmp_path)
    _plant(tmp_path, 'scratch/unknown.py')
    assert _hook('stop', tmp_path) == 0
    assert capsys.readouterr().out == ''
    _plant(tmp_path, 'scratch/new.py')
    assert _hook('stop', tmp_path) == 0
    assert 'scratch/new.py' in json.loads(capsys.readouterr().out)['reason']


def test_clear_defaults_to_this_sessions_entries_and_needs_names_for_anything_else(
    tmp_path, monkeypatch, capsys
) -> None:
    _repo(tmp_path)
    _plant(tmp_path, 'scratch/before.py')
    assert _hook('snapshot', tmp_path) == 0
    _plant(tmp_path, 'scratch/probe.py')
    _plant(tmp_path, 'scratch/keepme/x.txt')
    _nested_repo(tmp_path)
    _plant(tmp_path, 'src/outside.py')
    monkeypatch.chdir(tmp_path)
    assert main(['clear']) == 2  # no --yes: it names what would go and deletes nothing
    assert 'scratch/probe.py' in capsys.readouterr().out
    assert (tmp_path / 'scratch/probe.py').exists()
    assert main(['clear', '--keep', 'keepme', '--yes']) == 0
    names = sorted(p.name for p in (tmp_path / 'scratch').iterdir())
    assert names == [SCRATCH_README, 'before.py', 'keepme', 'tracked.txt']
    assert (tmp_path / 'src/outside.py').exists()
    assert 'scratch/clone' in capsys.readouterr().out
    assert main(['clear', 'before.py', '--yes']) == 0  # another's entry goes only by name
    assert not (tmp_path / 'scratch/before.py').exists()
    assert main(['clear', 'tracked.txt', '--yes']) == 2  # a tracked file is never an entry
    assert (tmp_path / 'scratch/tracked.txt').exists()


def test_clear_with_no_session_snapshot_refuses_without_names(tmp_path, monkeypatch, capsys) -> None:
    _repo(tmp_path)
    _plant(tmp_path, 'scratch/probe.py')
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(SESSION_ENV)
    assert main(['clear', '--yes']) == 2
    assert (tmp_path / 'scratch/probe.py').exists()
    assert 'name' in capsys.readouterr().out


@pytest.mark.windows
def test_clear_strips_windows_attributes_so_a_nested_git_deletes(tmp_path) -> None:
    _repo(tmp_path)
    _nested_repo(tmp_path)
    launch.run(['attrib', '+H', '+R', str(tmp_path / 'scratch' / 'clone' / '.git')], check=True)
    assert clear_scratch(tmp_path, ['clone']) == ['scratch/clone']
    assert not (tmp_path / 'scratch' / 'clone').exists()


def test_a_link_escaping_scratch_refuses_the_whole_clear(tmp_path) -> None:
    _repo(tmp_path)
    outside = tmp_path / 'precious'
    _plant(outside, 'data.txt')
    _plant(tmp_path, 'scratch/probe.py')
    (tmp_path / 'scratch' / 'run').mkdir()
    link = tmp_path / 'scratch' / 'run' / 'link'
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if sys.platform != 'win32':
            raise
        launch.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)], check=True, capture_output=True)
    with pytest.raises(ScratchEscape, match='scratch/run/link'):
        clear_scratch(tmp_path, ['probe.py', 'run'])
    assert (tmp_path / 'scratch/probe.py').exists()
    assert (outside / 'data.txt').exists()
