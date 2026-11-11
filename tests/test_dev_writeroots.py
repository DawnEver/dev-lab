"""WRITES-STAY-IN-THE-TREE: an agent may not write into a write-prone root outside every checkout.

User requirement 2026-11-05: an agent session left scripts in the OS temp dir (Git Bash ``/tmp``). The roots are
declared once (:func:`dev_lab.dev.writeroots.write_prone_roots`), injected here so no test touches the real temp
dir. Planted controls on both halves: reading a root, writing into the harness ``claude/`` subtree and writing
into a checkout outside every root are admitted; a checkout INSIDE a root is no exemption (user ruling 2026-11-06).
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from lab_commons.temp import TEMP_PREFIX

from dev_lab.dev import agenthooks
from dev_lab.dev.codeplace import main
from dev_lab.dev.famtests import tempprefix
from dev_lab.dev.hook_adoption import HookAdoption, render
from dev_lab.dev.writeroots import (
    Root,
    excluded_paths,
    owned_globs,
    refuse_outside_tree,
    write_prone_roots,
)


@pytest.fixture
def machine(tmp_path: Path) -> dict[str, Path]:
    """A planted machine: a temp dir, a home, and one fixed drive, all under *tmp_path*."""
    temp, home, drive = tmp_path / 'temp', tmp_path / 'home', tmp_path / 'D'
    for one in (temp, home, drive):
        one.mkdir()
    return {'temp': temp, 'home': home, 'drive': drive}


def _roots(machine: dict[str, Path]) -> tuple[Root, ...]:
    return write_prone_roots(
        temp_dirs=[machine['temp']], home=machine['home'], drives=[machine['drive']], posix=False, machine={}
    )


def test_the_roots_are_temp_the_drive_and_home_names_and_the_home_itself(machine: dict[str, Path]) -> None:
    by_path = {root.path: root.kind for root in _roots(machine)}
    assert by_path[machine['temp']] == 'temp'
    for name in ('tmp', 'temp'):
        assert by_path[machine['drive'] / name] == 'temp'
        assert by_path[machine['home'] / name] == 'temp'
    for name in ('var', 'src'):
        assert by_path[machine['drive'] / name] == 'census'
        assert by_path[machine['home'] / name] == 'census'
    assert by_path[machine['home']] == 'home'


def test_posix_adds_tmp_and_var_tmp(machine: dict[str, Path]) -> None:
    roots = write_prone_roots(temp_dirs=[], home=machine['home'], drives=[], posix=True, machine={})
    assert {Path('/') / 'tmp', Path('/') / 'var' / 'tmp'} <= {root.path for root in roots}


def test_the_machine_file_extends_the_roots_and_the_exclusions(machine: dict[str, Path], tmp_path: Path) -> None:
    extra, cache = tmp_path / 'jmtmp', machine['temp'] / 'vendor-cache'
    declared = {'temp': [str(extra)], 'census': [], 'excluded': [str(cache)]}
    roots = write_prone_roots(
        temp_dirs=[machine['temp']], home=machine['home'], drives=[], posix=False, machine=declared
    )
    assert Root(extra, 'temp') in roots
    assert cache in excluded_paths(roots, machine=declared, env={})


def test_the_harness_subtree_and_a_declared_cache_are_excluded(machine: dict[str, Path]) -> None:
    roots = _roots(machine)
    cache = machine['temp'] / 'uv-cache'
    excluded = excluded_paths(roots, machine={}, env={'UV_CACHE_DIR': str(cache)})
    assert machine['temp'] / 'claude' in excluded
    assert cache in excluded


@pytest.mark.parametrize(
    ('where', 'rel', 'refused'),
    [
        ('temp', 'probe.py', True),
        ('temp', 'a/b/notes.md', True),
        ('drive', 'tmp/x.sh', True),
        ('drive', 'src/thing.py', True),
        ('home', 'temp/x.txt', True),
        ('home', 'loose.py', True),
        ('home', '.bashrc', False),
        ('home', 'Documents/x.txt', False),
        ('temp', 'claude/abc/session/tasks/out.txt', False),
        ('drive', 'work/x.py', False),
    ],
)
def test_a_write_into_a_root_is_refused_and_its_near_misses_are_not(
    machine: dict[str, Path], where: str, rel: str, *, refused: bool
) -> None:
    roots = _roots(machine)
    reason = refuse_outside_tree(machine[where] / rel, roots=roots, excluded=excluded_paths(roots, machine={}, env={}))
    assert (reason is not None) is refused, rel
    if refused:
        assert reason.startswith('WRITES-STAY-IN-THE-TREE: ')
        assert 'output/logs/<yy>/<mm>/<dd>/<kind>/' in reason
        assert 'scratch/' in reason


def test_a_checkout_inside_a_root_is_refused_too(machine: dict[str, Path]) -> None:
    """User ruling 2026-11-06: a checkout under the home ``src`` is an abandoned old version; both halves refuse."""
    repo = machine['home'] / 'src' / 'repo'
    (repo / '.git').mkdir(parents=True)
    reason = refuse_outside_tree(repo / 'x.py', roots=_roots(machine), excluded=())
    assert reason is not None
    assert reason.startswith('WRITES-STAY-IN-THE-TREE: ')


def test_the_write_hook_denies_a_write_into_temp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    """The Write/Edit/NotebookEdit half rides the ``codeplace`` write hook, which reads the real roots."""
    temp = tmp_path / 'temp'
    temp.mkdir()
    monkeypatch.setenv('TEMP', str(temp))
    monkeypatch.setenv('TMP', str(temp))
    monkeypatch.setenv('TMPDIR', str(temp))
    monkeypatch.setattr('tempfile.tempdir', str(temp))
    home = tmp_path / 'home'
    (home / 'src' / 'repo' / '.git').mkdir(parents=True)
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('USERPROFILE', str(home))
    for tool, key in (('Write', 'file_path'), ('NotebookEdit', 'notebook_path')):
        bad = json.dumps({'tool_name': tool, 'tool_input': {key: str(temp / 'probe.ipynb')}})
        assert main(stdin=io.StringIO(bad)) == 0
        decision = json.loads(capsys.readouterr().out)['hookSpecificOutput']
        assert decision['permissionDecision'] == 'deny'
        assert 'WRITES-STAY-IN-THE-TREE' in decision['permissionDecisionReason']
    old = json.dumps({'tool_name': 'Write', 'tool_input': {'file_path': str(home / 'src' / 'repo' / 'x.py')}})
    assert main(stdin=io.StringIO(old)) == 0
    decision = json.loads(capsys.readouterr().out)['hookSpecificOutput']
    assert 'WRITES-STAY-IN-THE-TREE' in decision['permissionDecisionReason']
    harness = json.dumps({'tool_name': 'Write', 'tool_input': {'file_path': str(temp / 'claude' / 'x' / 'o.txt')}})
    assert main(stdin=io.StringIO(harness)) == 0
    assert capsys.readouterr().out == ''


@pytest.fixture(scope='module')
def rules(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp('rules') / 'deny-rules.json'
    path.write_text(render(HookAdoption(app_name='suite', remedies={})), encoding='utf-8')
    return path


@pytest.mark.parametrize(
    'command',
    [
        'echo x > /tmp/probe.py',
        "cat > /tmp/run.sh <<'EOF'\necho hi\nEOF",
        'python a.py 2>> /var/tmp/err.log',
        'git log | tee -a $TEMP/log.txt',
        'cp a.py /tmp/',
        'mv out.csv "C:/tmp/out.csv"',
        'mkdir -p /c/temp/probe',
        'touch $HOME/src/x.py',
        'touch $HOME/src/repo/x',
        'touch ~/src/repo/x',
        'echo x > D:/src/repo/a.txt',
        'Get-Content a | Out-File -FilePath $env:TEMP\\x.txt',
        'Set-Content -Path D:\\work\\AppData\\Local\\Temp\\x.ps1 -Value 1',
        'New-Item -ItemType File D:\\var\\x.txt',
        'Copy-Item a.py %TEMP%\\a.py',
        'echo x > ~/loose.txt',
    ],
)
def test_a_shell_write_into_a_root_is_refused(rules: Path, command: str) -> None:
    reason = agenthooks.decide(command, rules)
    assert reason is not None, command
    assert 'WRITES-STAY-IN-THE-TREE' in reason
    assert 'output/logs/<yy>/<mm>/<dd>/<kind>/' in reason


@pytest.mark.parametrize(
    'command',
    [
        'cat /tmp/probe.py',
        'ls $TEMP',
        'cp /tmp/x.csv output/logs/26/11/05/probe/x.csv',
        'echo x > /tmp/claude/abc/tasks/out.txt',
        'echo x > scratch/26/11/05/probe/run.sh',
        'python -m pkg.run > output/logs/26/11/05/run/log.txt',
        'echo x > ~/.bashrc',
        'rm /tmp/probe.py',
        'echo x 2>/dev/null',
    ],
)
def test_reads_the_harness_dir_and_the_checkout_are_unaffected(rules: Path, command: str) -> None:
    reason = agenthooks.decide(command, rules)
    assert reason is None or 'WRITES-STAY-IN-THE-TREE' not in reason, (command, reason)


#: Measured 2026-11-11: 492 ``.py`` files under ``src/``; set below it with room for ordinary deletion.
_SRC_FLOOR = 400


def test_every_temp_entry_the_family_creates_carries_the_one_prefix() -> None:
    """ONLY OUR OWN IS SWEPT, so every temp entry we make must be recognisable as ours."""
    root = Path(__file__).resolve().parents[1]
    tempprefix.assert_every_temp_entry_carries_the_prefix(base=root, roots=[root / 'src'], floor=_SRC_FLOOR)


def test_an_unprefixed_temp_call_is_found(tmp_path: Path) -> None:
    """The planted control of the scan above."""
    tempprefix.assert_the_scan_finds_a_planted_call(tmp_path=tmp_path)


def test_owned_globs_are_the_prefix_plus_the_declared_ones() -> None:
    assert owned_globs({}) == (f'{TEMP_PREFIX}*',)
    assert owned_globs({'owned': ['pytest-of-*']}) == (f'{TEMP_PREFIX}*', 'pytest-of-*')
    with pytest.raises(ValueError, match='owned'):
        owned_globs({'owned': 'pytest-of-*'})
