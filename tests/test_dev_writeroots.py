"""WRITES-STAY-IN-THE-TREE: an agent writes only into the writable roots its machine ALLOWS (ruling R8, 2026-11-24).

The allowlist is ``[writeroots] allow`` (undeclared: the family checkouts of ``[repos]``), injected here so no test
reads the real machine file or touches the real temp dir. Planted controls on every judgment: a checkout, its
worktree and a declared place are admitted; its sibling, a drive root, the temp dir, OneDrive and the harness's
temp subtree are refused. The census half (:func:`dev_lab.dev.writeroots.write_prone_roots`) is tested first.
"""

# ruff: noqa: S108 -- /tmp and its kin are the SUBJECT: spelled paths a write must be refused into, never used

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest
from lab_commons.storage import Storage
from lab_commons.temp import TEMP_PREFIX

from dev_lab.dev import writeroots
from dev_lab.dev._deny_writeroots_row import WRITES_STAY_IN_THE_TREE
from dev_lab.dev.codeplace import main
from dev_lab.dev.famtests import tempprefix
from dev_lab.dev.writeroots import (
    Allowance,
    Root,
    allow_defects,
    allowed_roots,
    excluded_paths,
    judge,
    owned_globs,
    refuse_outside_tree,
    shell_targets,
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


@pytest.fixture
def family(tmp_path: Path) -> dict[str, Path]:
    """A planted machine: two family checkouts side by side, a sibling, a temp dir, a home and a OneDrive."""
    base = tmp_path / 'work'
    found = {
        'repo': base / 'repo-a',
        'other': base / 'repo-b',
        'sibling': base / 'not-a-checkout',
        'temp': tmp_path / 'temp',
        'home': tmp_path / 'home',
        'onedrive': tmp_path / 'home' / 'OneDrive',  # a created dir: '<org>' is no legal Windows name
    }
    for one in found.values():
        one.mkdir(parents=True, exist_ok=True)
    return found


def _fallback(family: dict[str, Path]) -> Allowance:
    return allowed_roots(machine={}, repos={'a': family['repo'], 'b': family['other']}, env={})


def test_undeclared_the_allowlist_is_the_family_checkouts(family: dict[str, Path]) -> None:
    allowed = _fallback(family)
    assert allowed == Allowance((family['repo'], family['other']), 'fallback')


def test_a_declared_allowlist_replaces_the_fallback_and_expands_its_tokens(family: dict[str, Path]) -> None:
    """Spelled paths, never created: pytest's tmp_path lies under the OS temp, which no allowlist may name."""
    extra = 'D:/Documents/lab'
    allowed = allowed_roots(
        machine={'allow': ['{repos}', '{lab_root}', extra]},
        repos={'a': family['repo']},
        env={'LAB_ROOT': str(family['other'])},
    )
    assert allowed == Allowance((family['repo'], family['other'], Path(extra)), 'declared')
    only = allowed_roots(machine={'allow': [extra]}, repos={'a': family['repo']}, env={})
    assert only.roots == (Path(extra),), 'a declaration without {repos} allows no checkout'


@pytest.mark.parametrize(
    'entry',
    [
        '/', 'C:/', 'D:\\', '/c/', '~', 'C:/Users/<user>', '/home/<user>', '/tmp', '/var/tmp/x', 'C:/temp',
        'C:/Users/<user>/AppData/Local/Temp', '~/src', 'D:/src/old', 'D:/OneDrive - <org>/Sync', 'relative/dir',
        '{nope}', '', 3,
    ],
)  # fmt: skip
def test_an_allow_entry_no_machine_may_declare_is_refused_by_name(entry: object) -> None:
    defects = allow_defects([entry])
    assert len(defects) == 1, (entry, defects)
    assert repr(entry) in defects[0]
    with pytest.raises(ValueError, match=r'hosts/<machine>\.toml \[writeroots\] allow'):
        allowed_roots(machine={'allow': [entry]}, repos={}, env={})


def test_an_ordinary_root_and_the_tokens_are_accepted() -> None:
    """The planted control of the refusals above."""
    assert allow_defects(['{repos}', '{lab_root}', 'D:/Documents/lab', '/gpfs01/home/me/lab', '~/work']) == []
    assert allow_defects('D:/lab') != []


@pytest.mark.parametrize(
    ('where', 'rel', 'refused'),
    [
        ('repo', 'src/x.py', False),
        ('repo', '.claude/worktrees/lane/x.py', False),
        ('other', 'scratch/26/11/24/probe/run.sh', False),
        ('sibling', 'x.py', True),
        ('temp', 'probe.py', True),
        ('temp', 'claude/abc/session/tasks/out.txt', True),  # the harness's subtree: $CLAUDE_JOB_DIR/tmp lives there
        ('home', 'loose.txt', True),
        ('home', '.bashrc', True),
        ('home', 'src/repo/x.py', True),
        ('onedrive', 'Sync/x.csv', True),
    ],
)
def test_a_write_outside_every_allowed_root_is_refused(
    family: dict[str, Path], where: str, rel: str, *, refused: bool
) -> None:
    reason = refuse_outside_tree(family[where] / rel, allowed=_fallback(family), admitted=())
    assert (reason is not None) is refused, rel
    if refused:
        assert reason.startswith('WRITES-STAY-IN-THE-TREE: ')
        assert 'the fallback' in reason
        assert family['repo'].as_posix() in reason
        assert 'hosts/<machine>.toml [writeroots] allow' in reason
        assert 'output/logs/<yy>/<mm>/<dd>/<kind>/' in reason


def test_a_drive_root_is_refused(family: dict[str, Path]) -> None:
    anchor = Path(family['repo'].anchor)
    assert refuse_outside_tree(anchor / 'x.txt', allowed=_fallback(family), admitted=()) is not None


def test_a_declared_place_is_admitted_and_a_declared_list_names_itself(family: dict[str, Path]) -> None:
    cache = family['temp'] / 'uv-cache'
    assert refuse_outside_tree(cache / 'x', allowed=_fallback(family), admitted=(cache,)) is None
    allowed = Allowance((family['sibling'],), 'declared')
    reason = refuse_outside_tree(family['repo'] / 'x', allowed=allowed, admitted=())
    assert reason is not None
    assert "this machine's [writeroots] allow" in reason


def test_the_admitted_places_are_caches_storage_excluded_and_the_harness_plans(tmp_path: Path) -> None:
    excluded, cache, config = tmp_path / 'vendor', tmp_path / 'uv', tmp_path / 'cfg'
    found = writeroots.admitted_paths(
        machine={'excluded': [str(excluded)]},
        env={'UV_CACHE_DIR': str(cache), 'CLAUDE_CONFIG_DIR': str(config)},
        storage=Storage(roots={}),
    )
    assert set(found) == {excluded, cache, config / 'plans'}


def test_an_unusable_declaration_refuses_by_name(monkeypatch: pytest.MonkeyPatch, family: dict[str, Path]) -> None:
    monkeypatch.setattr(writeroots, 'declared', lambda: {'allow': ['/tmp']})
    reason = refuse_outside_tree(family['repo'] / 'x', admitted=())
    assert reason is not None
    assert "'/tmp' is refused" in reason


@pytest.mark.parametrize(
    ('command', 'targets'),
    [
        ('echo x > /tmp/a.py', [('/tmp/a.py', '')]),
        ("cat <<'EOF' > /tmp/x\necho > not/a/target\nEOF", [('/tmp/x', '')]),
        ('cat > "/tmp/my file" <<EOF\nhi\nEOF', [('/tmp/my file', '')]),
        ('python a.py 2>> err.log 2>&1 | tee -a out.txt b.txt', [('err.log', ''), ('out.txt', ''), ('b.txt', '')]),
        ('cp -r a b /tmp/', [('/tmp/', '')]),
        ('cd /tmp && mkdir -p x y', [('x', '/tmp'), ('y', '/tmp')]),
        ('cd /tmp; cd sub && touch f', [('f', '/tmp/sub')]),
        ('dd if=a of=/c/x.bin', [('/c/x.bin', '')]),
        ('Set-Content -Path D:\\x.txt -Value 1', [('D:\\x.txt', '')]),
        ('New-Item -ItemType File D:\\var\\x.txt', [('D:\\var\\x.txt', '')]),
        ('echo x 2>/dev/null > $null', []),
        ('cat /tmp/a | grep b', []),
    ],
)
def test_the_shell_targets_are_every_place_a_line_writes(command: str, targets: list[tuple[str, str]]) -> None:
    assert shell_targets(command) == targets


@pytest.mark.parametrize('target', ['D:/var/x.txt', 'C:\\tmp\\out.csv'])
def test_a_drive_spelled_target_is_absolute_on_every_os(tmp_path: Path, target: str) -> None:
    """A drive letter names a root outside the call's cwd even where the OS has no drives (CI's POSIX runner)."""
    placed = writeroots.place(target, '', tmp_path)
    assert placed is not None
    assert placed.is_absolute()
    assert not placed.is_relative_to(tmp_path)


def _payload(command: str, cwd: Path) -> dict[str, object]:
    return {'tool_name': 'Bash', 'tool_input': {'command': command}, 'cwd': str(cwd)}


@pytest.mark.parametrize('command', WRITES_STAY_IN_THE_TREE['refuses'])
def test_every_refusal_of_the_row_is_prefiltered_and_refused_by_the_judge(
    family: dict[str, Path], monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    """The row's ``refuses`` are its planted cases: the prefilter must pass each to the judge, which must refuse it."""
    monkeypatch.delenv('CLAUDE_JOB_DIR', raising=False)
    assert re.search(WRITES_STAY_IN_THE_TREE['pattern'], command), command
    reason = judge(_payload(command, family['repo']), allowed=_fallback(family), admitted=())
    assert reason is not None, command
    assert reason.startswith('WRITES-STAY-IN-THE-TREE: ')


@pytest.mark.parametrize('command', WRITES_STAY_IN_THE_TREE['permits'])
def test_every_permit_of_the_row_is_admitted(family: dict[str, Path], command: str) -> None:
    assert judge(_payload(command, family['repo']), allowed=_fallback(family), admitted=()) is None, command


def test_the_prefilter_starts_no_judge_on_a_write_below_the_cwd() -> None:
    """The cheap half: a line writing only relative paths below its cwd spawns no interpreter."""
    for command in ('echo x > scratch/a.sh', 'pytest -q > output/logs/x.log 2>&1', 'echo x 2>/dev/null'):
        assert not re.search(WRITES_STAY_IN_THE_TREE['pattern'], command), command


def test_a_set_job_dir_is_placed_and_still_refused(family: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """``$CLAUDE_JOB_DIR/tmp`` is refused whether the variable is unset (unplaceable) or set (outside every root)."""
    monkeypatch.setenv('CLAUDE_JOB_DIR', str(family['temp'] / 'claude' / 'job'))
    reason = judge(_payload('echo x > $CLAUDE_JOB_DIR/tmp/a', family['repo']), allowed=_fallback(family), admitted=())
    assert reason is not None
    assert 'is outside every writable root' in reason


def test_the_judge_door_exits_one_with_the_refusal(family: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(writeroots, 'declared', dict)
    monkeypatch.setattr(writeroots.machine_home, 'repos', lambda: {'a': family['repo']})
    monkeypatch.setattr(writeroots, 'admitted_paths', lambda: ())
    out = io.BytesIO()
    bad = json.dumps(_payload(f'echo x > {family["sibling"].as_posix()}/a', family['repo'])).encode()
    assert writeroots.main(['--admit'], stdin=io.BytesIO(bad), stdout=out) == 1
    assert out.getvalue().decode().startswith('WRITES-STAY-IN-THE-TREE: ')
    good = json.dumps(_payload(f'echo x > {family["repo"].as_posix()}/a', family['repo'])).encode()
    assert writeroots.main(['--admit'], stdin=io.BytesIO(good), stdout=io.BytesIO()) == 0


def test_the_write_hook_denies_a_write_outside_the_allowlist(
    family: dict[str, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The Write/Edit/NotebookEdit half rides the ``codeplace`` write hook."""
    monkeypatch.setattr(writeroots, 'declared', dict)
    monkeypatch.setattr(writeroots.machine_home, 'repos', lambda: {'a': family['repo']})
    monkeypatch.setattr(writeroots, 'admitted_paths', lambda: ())
    for tool, key in (('Write', 'file_path'), ('NotebookEdit', 'notebook_path')):
        bad = json.dumps({'tool_name': tool, 'tool_input': {key: str(family['sibling'] / 'probe.ipynb')}})
        assert main(stdin=io.StringIO(bad)) == 0
        decision = json.loads(capsys.readouterr().out)['hookSpecificOutput']
        assert decision['permissionDecision'] == 'deny'
        assert 'WRITES-STAY-IN-THE-TREE' in decision['permissionDecisionReason']
    good = json.dumps({'tool_name': 'Write', 'tool_input': {'file_path': str(family['repo'] / 'notes.txt')}})
    assert main(stdin=io.StringIO(good)) == 0
    assert 'WRITES-STAY-IN-THE-TREE' not in capsys.readouterr().out


#: Measured 2026-11-11: 492 ``.py`` files under ``src/``; set below it with room for ordinary deletion.
_SRC_FLOOR = 400


def test_every_temp_entry_the_family_creates_carries_the_one_prefix() -> None:
    """ONLY OUR OWN IS SWEPT, so every temp entry we make must be recognizable as ours."""
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


def test_a_synced_folder_and_a_dir_beside_a_checkout_are_off_the_allowlist(tmp_path: Path) -> None:
    """User requirement 2026-11-23 (OneDrive, ``../<repo>-copy``), enforced by R8's allowlist; the checkout stays."""
    allowed = Allowance((tmp_path / 'repo',), 'declared')
    for path in (tmp_path / 'OneDrive-Org' / 'meeting' / 'fig.png', tmp_path / 'repo-copy' / 'x.py'):
        assert refuse_outside_tree(path, allowed=allowed, admitted=()) is not None
    assert refuse_outside_tree(tmp_path / 'repo' / 'onedrive_notes.md', allowed=allowed, admitted=()) is None


def test_the_job_temp_is_no_door(tmp_path: Path) -> None:
    # User ruling 2026-11-23: $CLAUDE_JOB_DIR/tmp is forbidden too; planted, it must not be excluded.
    job = tmp_path / 'jobs' / 'abc'
    found = excluded_paths((), machine={}, env={'CLAUDE_JOB_DIR': str(job)})
    assert job / 'tmp' not in found
