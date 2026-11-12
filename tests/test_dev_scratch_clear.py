"""``dev_lab.dev.scratch list|clear|stop``: the door that empties a checkout's scratch, and the stop that asks for it.

Details: docs-src/dev/refusals.md#recursive-delete.
"""

from __future__ import annotations

import io
import json
import stat
import sys

import pytest
from lab_commons import launch

from dev_lab.dev.scratch import SCRATCH_README, ScratchEscape, clear_scratch, main, untracked_scratch


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


def test_clear_deletes_every_untracked_entry_and_keeps_tracked_and_kept_ones(tmp_path, monkeypatch, capsys) -> None:
    _repo(tmp_path)
    _plant(tmp_path, 'scratch/probe.py')
    _plant(tmp_path, 'scratch/keepme/x.txt')
    _nested_repo(tmp_path)
    _plant(tmp_path, 'src/outside.py')
    monkeypatch.chdir(tmp_path)
    assert main(['clear', '--keep', 'keepme', '--yes']) == 0
    assert sorted(p.name for p in (tmp_path / 'scratch').iterdir()) == [SCRATCH_README, 'keepme', 'tracked.txt']
    assert (tmp_path / 'src/outside.py').exists()
    assert 'scratch/clone' in capsys.readouterr().out


def test_clear_without_yes_deletes_nothing_and_says_what_it_would(tmp_path, monkeypatch, capsys) -> None:
    _repo(tmp_path)
    _plant(tmp_path, 'scratch/probe.py')
    monkeypatch.chdir(tmp_path)
    assert main(['clear']) == 2
    assert (tmp_path / 'scratch/probe.py').exists()
    out = capsys.readouterr().out
    assert 'scratch/probe.py' in out
    assert '--yes' in out


@pytest.mark.skipif(sys.platform != 'win32', reason='hidden and read-only attributes are Windows file attributes')
def test_clear_strips_windows_attributes_so_a_nested_git_deletes(tmp_path) -> None:
    _repo(tmp_path)
    _nested_repo(tmp_path)
    launch.run(['attrib', '+H', '+R', str(tmp_path / 'scratch' / 'clone' / '.git')], check=True)
    assert clear_scratch(tmp_path, keep=()) == ['scratch/clone']
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
        clear_scratch(tmp_path, keep=())
    assert (tmp_path / 'scratch/probe.py').exists()
    assert (outside / 'data.txt').exists()


def test_the_stop_blocks_once_while_scratch_holds_an_untracked_entry(tmp_path, capsys) -> None:
    _repo(tmp_path)
    payload = {'hook_event_name': 'Stop', 'cwd': str(tmp_path)}
    assert main(['stop'], stdin=io.StringIO(json.dumps(payload))) == 0
    assert capsys.readouterr().out == ''
    _plant(tmp_path, 'scratch/probe.py')
    assert main(['stop'], stdin=io.StringIO(json.dumps(payload))) == 0
    decision = json.loads(capsys.readouterr().out)
    assert decision['decision'] == 'block'
    assert 'scratch/probe.py' in decision['reason']
    assert 'dev_lab.dev.scratch clear' in decision['reason']
    assert '--keep' in decision['reason']
    assert main(['stop'], stdin=io.StringIO(json.dumps({**payload, 'stop_hook_active': True}))) == 0
    assert capsys.readouterr().out == ''
