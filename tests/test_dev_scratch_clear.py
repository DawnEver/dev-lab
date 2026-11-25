"""``dev_lab.dev.scratch list|clear|claim|stop``: who made each scratch entry, the stop that names it, and the door.

Details: docs-src/dev/refusals.md#recursive-delete.
"""

from __future__ import annotations

import io
import json
import os
import stat
import sys
import time

import pytest
from lab_commons import home, launch

from dev_lab.dev import _scratch_clear, scratchorphans, walls
from dev_lab.dev._scratch_owners import CLAIM_WINDOW_S, LIVE_S, RECENT_S, beat, claim, named, owners
from dev_lab.dev.hpcaccount.session import INTEGRATOR
from dev_lab.dev.scratch import SCRATCH_README, ScratchEscape, ScratchInUse, clear_scratch, main, untracked_scratch

SESSION_ENV = 'CLAUDE_CODE_SESSION_ID'


@pytest.fixture(autouse=True)
def machine_home(tmp_path, monkeypatch) -> None:
    """Owner records live under a planted machine home; only ``integrator-session`` holds the integrator role."""
    monkeypatch.setenv(home.HOME_ENV, str(tmp_path / 'home'))
    monkeypatch.setenv(SESSION_ENV, 'this-session')
    monkeypatch.setattr(
        scratchorphans,
        'held',
        lambda session: frozenset({INTEGRATOR}) if session == 'integrator-session' else frozenset(),
    )


def _run(argv: list[str], payload: dict) -> int:
    return main(argv, stdin=io.StringIO(json.dumps(payload)))


def _stop(root, session: str = 'this-session') -> int:
    return _run(['stop'], {'session_id': session, 'cwd': str(root)})


def _report(root, session: str) -> int:
    """The detached ``Stop`` row reporting entries of no live session to the integrator."""
    return scratchorphans.main([], stdin=io.StringIO(json.dumps({'session_id': session, 'cwd': str(root)})))


def _shell(root, command: str, session: str = 'this-session') -> int:
    """The shell claim row after *session* ran *command* in *root*."""
    payload = {'session_id': session, 'cwd': str(root), 'tool_input': {'command': command}}
    return _run(['claim', 'shell'], payload)


def _write(root, rel: str, session: str = 'this-session') -> int:
    """The write claim row before *session* writes *rel*, then the write itself."""
    payload = {'session_id': session, 'cwd': str(root), 'tool_input': {'file_path': str(root / rel)}}
    code = _run(['claim', 'write'], payload)
    _plant(root, rel)
    return code


def _repo(root) -> None:
    """A MAIN checkout (a real ``.git`` directory) declaring the family scratch, its README tracked."""
    launch.run(['git', 'init', '-q', str(root)], check=True)
    (root / 'layout.toml').write_text('', encoding='utf-8')
    (root / 'scratch').mkdir()
    (root / 'scratch' / SCRATCH_README).write_text('anchor\n', encoding='utf-8')
    (root / 'scratch' / 'tracked.txt').write_text('kept\n', encoding='utf-8')
    launch.run(['git', '-C', str(root), 'add', 'layout.toml', 'scratch'], check=True)


def _plant(root, rel: str, text: str = 'x\n') -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _age(path, seconds: float) -> None:
    """Make every file and directory at or under *path* last touched *seconds* ago."""
    stamp = time.time() - seconds
    for each in [*path.rglob('*'), path] if path.is_dir() else [path]:
        os.utime(each, (stamp, stamp))


def _gone(session: str) -> None:
    """*session* was last heard past the live window."""
    beat(session, now=time.time() - 2 * LIVE_S)


def _nested_repo(root) -> None:
    """A one-off holding its own ``.git``, whose files are made read-only as git makes its objects."""
    nested = root / 'scratch' / 'clone'
    launch.run(['git', 'init', '-q', str(nested)], check=True)
    _plant(nested, 'f.txt')
    launch.run(['git', '-C', str(nested), 'add', 'f.txt'], check=True)
    for path in (nested / '.git').rglob('*'):
        if path.is_file():
            path.chmod(stat.S_IREAD)


def _reason(capsys) -> str:
    out = capsys.readouterr().out
    return json.loads(out)['reason'] if out else ''


def _message(capsys) -> str:
    out = capsys.readouterr().out
    return json.loads(out)['systemMessage'] if out else ''


def test_list_names_only_untracked_top_level_entries_with_sizes(tmp_path) -> None:
    _repo(tmp_path)
    _plant(tmp_path, 'scratch/probe.py', 'abc')
    _plant(tmp_path, 'scratch/run/a.txt', 'abcd')
    _plant(tmp_path, 'scratch/run/b.txt', 'ef')
    entries = {rel: size for rel, size, _ in untracked_scratch(tmp_path)}
    assert entries == {'scratch/probe.py': 3, 'scratch/run': 6}


def test_a_command_names_entries_by_either_slash_and_never_a_lookalike() -> None:
    command = (
        'git clone u D:\\w\\repo\\scratch\\salvage1125 && mkdir -p scratch/a/b; cat "scratch/q.txt" myscratch/no '
        'ls scratch/ scratch/*.py'
    )
    assert named(command, 'scratch/') == {'salvage1125', 'a', 'q.txt'}
    assert named('touch tmp/one-offs/x.txt', 'tmp/one-offs/') == {'x.txt'}


def test_the_stop_names_only_what_this_session_made(tmp_path, capsys) -> None:
    """PLANTED CONTROL: another live session's entry and one nobody named never block this session; its own does.

    The 2026-11-25 wall: a stop named another agent's in-progress ``scratch/salvage1125`` as this session's.
    """
    _repo(tmp_path)
    _plant(tmp_path, 'scratch/salvage1125/f.txt')
    assert _shell(tmp_path, 'git clone url scratch/salvage1125', session='other-session') == 0
    _plant(tmp_path, 'scratch/unnamed.json')
    assert _stop(tmp_path) == 0
    assert capsys.readouterr().out == ''
    assert _write(tmp_path, 'scratch/ours/x.txt') == 0
    assert _stop(tmp_path) == 0
    reason = _reason(capsys)
    assert 'scratch/ours' in reason
    assert 'salvage1125' not in reason
    assert 'unnamed' not in reason
    assert 'dev_lab.dev.scratch clear' in reason
    assert '--keep' in reason
    assert _stop(tmp_path, session='other-session') == 0
    reason = _reason(capsys)
    assert 'scratch/salvage1125' in reason
    assert 'ours' not in reason


def test_the_first_claim_wins_and_a_named_old_entry_is_never_adopted(tmp_path, monkeypatch) -> None:
    _repo(tmp_path)
    _write(tmp_path, 'scratch/mine.txt', session='other-session')
    _write(tmp_path, 'scratch/mine.txt')  # a later write into it never steals it
    _shell(tmp_path, 'cat scratch/mine.txt')
    assert owners(tmp_path)['mine.txt'].session == 'other-session'
    _plant(tmp_path, 'scratch/old.txt')
    fresh = _scratch_clear.born
    monkeypatch.setattr(_scratch_clear, 'born', lambda _path: time.time() - 2 * CLAIM_WINDOW_S)
    _shell(tmp_path, 'cat scratch/old.txt')  # PLANTED CONTROL: reading an old ownerless entry adopts nothing
    assert 'old.txt' not in owners(tmp_path)
    monkeypatch.setattr(_scratch_clear, 'born', fresh)
    _plant(tmp_path, 'scratch/new.txt')
    _shell(tmp_path, 'python probe.py > scratch/new.txt')
    assert owners(tmp_path)['new.txt'].session == 'this-session'


def test_the_record_of_a_former_entry_never_captures_a_new_one_of_the_same_name(tmp_path) -> None:
    """A deleted entry's record (or a write that never landed) is replaced; a fresh one is never stolen."""
    _repo(tmp_path)
    long_ago = time.time() - 2 * CLAIM_WINDOW_S
    assert claim(tmp_path, 'probe.py', 'gone-session', now=long_ago)
    _plant(tmp_path, 'scratch/probe.py')
    _shell(tmp_path, 'python scratch/probe.py')
    assert owners(tmp_path)['probe.py'].session == 'this-session'
    _write(tmp_path, 'scratch/probe.py', session='other-session')  # PLANTED CONTROL: a live claim is never replaced
    assert owners(tmp_path)['probe.py'].session == 'this-session'
    assert claim(tmp_path, 'never.txt', 'gone-session', now=long_ago)
    _write(tmp_path, 'scratch/never.txt')
    assert owners(tmp_path)['never.txt'].session == 'this-session'


def test_clear_with_no_names_takes_only_this_sessions_entries(tmp_path, monkeypatch, capsys) -> None:
    _repo(tmp_path)
    _write(tmp_path, 'scratch/probe.py')
    _write(tmp_path, 'scratch/keepme/x.txt')
    _plant(tmp_path, 'scratch/clone/x.txt')
    _shell(tmp_path, 'git init scratch/clone')
    _nested_repo(tmp_path)
    _write(tmp_path, 'scratch/theirs.py', session='other-session')
    _plant(tmp_path, 'scratch/unnamed.py')
    _plant(tmp_path, 'src/outside.py')
    monkeypatch.chdir(tmp_path)
    assert main(['clear']) == 2  # no --yes: it names what would go and deletes nothing
    assert 'scratch/probe.py' in capsys.readouterr().out
    assert (tmp_path / 'scratch/probe.py').exists()
    assert main(['clear', '--keep', 'keepme', '--yes']) == 0
    names = sorted(p.name for p in (tmp_path / 'scratch').iterdir())
    assert names == [SCRATCH_README, 'keepme', 'theirs.py', 'tracked.txt', 'unnamed.py']
    assert (tmp_path / 'src/outside.py').exists()
    assert 'scratch/clone' in capsys.readouterr().out
    assert main(['clear', 'tracked.txt', '--yes']) == 2  # a tracked file is never an entry
    assert (tmp_path / 'scratch/tracked.txt').exists()


def test_clear_REFUSES_another_live_sessions_entry_naming_its_owner_and_the_door(tmp_path, monkeypatch, capsys) -> None:
    """PLANTED CONTROL: by name, another live session's entry is refused -- however quiet -- until the user approves."""
    _repo(tmp_path)
    _write(tmp_path, 'scratch/salvage1125/f.txt', session='other-session')
    _age(tmp_path / 'scratch/salvage1125', 2 * RECENT_S)
    _write(tmp_path, 'scratch/mine.txt')
    monkeypatch.chdir(tmp_path)
    assert main(['clear', 'salvage1125', 'mine.txt', '--yes']) == 2
    out = capsys.readouterr().out
    assert 'scratch/salvage1125 belongs to live session other-session' in out
    assert '--approved' in out
    assert (tmp_path / 'scratch/salvage1125/f.txt').exists()
    assert (tmp_path / 'scratch/mine.txt').exists()  # the whole clear is refused
    assert main(['clear', 'salvage1125', '--approved', ' ', '--yes']) == 2  # an empty approval approves nothing
    assert main(['clear', 'salvage1125', '--approved', 'the user: drop salvage1125', '--yes']) == 0
    assert not (tmp_path / 'scratch/salvage1125').exists()
    assert 'salvage1125' not in owners(tmp_path)


def test_clear_REFUSES_a_freshly_touched_entry_of_no_live_session_until_it_is_quiet(tmp_path) -> None:
    _repo(tmp_path)
    _plant(tmp_path, 'scratch/unnamed/out.json')
    with pytest.raises(ScratchInUse, match=r'scratch/unnamed was touched 0 min ago'):
        clear_scratch(tmp_path, ['unnamed'], session='this-session')
    assert (tmp_path / 'scratch/unnamed/out.json').exists()
    _age(tmp_path / 'scratch/unnamed', 2 * RECENT_S)
    _write(tmp_path, 'scratch/gone.txt', session='gone-session')
    _age(tmp_path / 'scratch/gone.txt', 2 * RECENT_S)
    _gone('gone-session')
    assert clear_scratch(tmp_path, ['unnamed', 'gone.txt'], session='this-session') == [
        'scratch/unnamed',
        'scratch/gone.txt',
    ]


def test_a_gone_sessions_entry_is_reported_to_the_integrator_only(tmp_path, capsys) -> None:
    """PLANTED CONTROL: the same tree is reported to the integrator and no other session; a live owner's never is."""
    _repo(tmp_path)
    _write(tmp_path, 'scratch/left/x.txt', session='gone-session')
    _write(tmp_path, 'scratch/working.txt', session='other-session')
    _plant(tmp_path, 'scratch/unnamed.txt')
    _plant(tmp_path, 'scratch/fresh.txt')
    for rel in ('left', 'working.txt', 'unnamed.txt'):
        _age(tmp_path / 'scratch' / rel, 2 * RECENT_S)
    _gone('gone-session')
    assert _stop(tmp_path) == 0
    assert _report(tmp_path, 'this-session') == 0
    assert capsys.readouterr().out == ''
    assert _stop(tmp_path, session='integrator-session') == 0
    assert capsys.readouterr().out == ''  # never a block: the integrator's inline stop names only its own
    assert _report(tmp_path, 'integrator-session') == 0
    reason = _message(capsys)
    assert 'scratch/left (gone session gone-session)' in reason
    assert 'scratch/unnamed.txt (no recorded owner)' in reason
    assert 'working.txt' not in reason
    assert 'fresh.txt' not in reason
    assert 'integrator' in reason


def test_keep_acks_an_entry_so_no_stop_names_it_and_refuses_another_live_sessions(
    tmp_path, monkeypatch, capsys
) -> None:
    _repo(tmp_path)
    _write(tmp_path, 'scratch/evidence.txt')
    _write(tmp_path, 'scratch/theirs.txt', session='other-session')
    _write(tmp_path, 'scratch/left.txt', session='gone-session')
    _age(tmp_path / 'scratch/left.txt', 2 * RECENT_S)
    _gone('gone-session')
    monkeypatch.chdir(tmp_path)
    assert main(['clear', '--keep', 'evidence.txt']) == 0
    assert main(['clear', '--keep', 'theirs.txt']) == 2
    assert 'other-session' in capsys.readouterr().out
    assert _stop(tmp_path) == 0
    assert capsys.readouterr().out == ''
    assert (tmp_path / 'scratch/evidence.txt').exists()
    monkeypatch.setenv(SESSION_ENV, 'integrator-session')
    assert _report(tmp_path, 'integrator-session') == 0
    assert 'scratch/left.txt' in _message(capsys)
    assert main(['clear', '--keep', 'left.txt']) == 0
    capsys.readouterr()
    assert _stop(tmp_path, session='integrator-session') == 0
    assert _report(tmp_path, 'integrator-session') == 0
    assert capsys.readouterr().out == ''
    assert _stop(tmp_path, session='other-session') == 0
    assert 'scratch/theirs.txt' in _reason(capsys)


def test_clear_with_no_native_session_refuses_without_names(tmp_path, monkeypatch, capsys) -> None:
    _repo(tmp_path)
    _plant(tmp_path, 'scratch/probe.py')
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(SESSION_ENV)
    assert main(['clear', '--yes']) == 2
    assert (tmp_path / 'scratch/probe.py').exists()
    assert 'name' in capsys.readouterr().out


def test_list_says_whose_each_entry_is(tmp_path, monkeypatch, capsys) -> None:
    _repo(tmp_path)
    _write(tmp_path, 'scratch/mine.txt')
    _write(tmp_path, 'scratch/theirs.txt', session='other-session')
    _plant(tmp_path, 'scratch/unnamed.txt')
    monkeypatch.chdir(tmp_path)
    assert main(['list']) == 0
    rows = {row.split()[-1]: row for row in capsys.readouterr().out.splitlines()}
    assert ' this ' in rows['scratch/mine.txt']
    assert 'live other-session' in rows['scratch/theirs.txt']
    assert ' - ' in rows['scratch/unnamed.txt']


def test_clear_deletes_a_nested_git_whose_files_are_read_only(tmp_path) -> None:
    """Git marks its object files read-only; on Windows that alone stops a tree delete until the hook clears it."""
    _repo(tmp_path)
    _nested_repo(tmp_path)
    claim(tmp_path, 'clone', 'this-session')
    git_dir = tmp_path / 'scratch' / 'clone' / '.git'
    locked = git_dir / 'locked-object'
    locked.write_text('x', encoding='utf-8')
    locked.chmod(stat.S_IREAD)
    assert clear_scratch(tmp_path, ['clone'], session='this-session') == ['scratch/clone']
    assert not (tmp_path / 'scratch' / 'clone').exists()


def test_a_link_escaping_scratch_refuses_the_whole_clear(tmp_path) -> None:
    _repo(tmp_path)
    outside = tmp_path / 'precious'
    _plant(outside, 'data.txt')
    _plant(tmp_path, 'scratch/probe.py')
    (tmp_path / 'scratch' / 'run').mkdir()
    for name in ('probe.py', 'run'):
        claim(tmp_path, name, 'this-session')
    link = tmp_path / 'scratch' / 'run' / 'link'
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if sys.platform != 'win32':
            raise
        launch.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)], check=True, capture_output=True)
    with pytest.raises(ScratchEscape, match='scratch/run/link'):
        clear_scratch(tmp_path, ['probe.py', 'run'], session='this-session')
    assert (tmp_path / 'scratch/probe.py').exists()
    assert (outside / 'data.txt').exists()


def test_a_blocked_stop_is_this_sessions_wall_with_its_remedy(tmp_path, capsys) -> None:
    """WALLS-ARE-RECORDED: the scratch block reaches the ledger through the one choke point."""
    _repo(tmp_path)
    assert _stop(tmp_path) == 0
    assert not walls.ledger(tmp_path).exists()
    _write(tmp_path, 'scratch/ours.py')
    assert _stop(tmp_path) == 0
    capsys.readouterr()
    [line] = [json.loads(raw) for raw in walls.ledger(tmp_path).read_text(encoding='utf-8').splitlines()]
    assert (line['rule'], line['remedy_present'], line['session']) == (
        'SCRATCH-IS-NEVER-COMMITTED',
        True,
        'this-session',
    )
