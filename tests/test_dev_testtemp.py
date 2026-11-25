"""Controls for :mod:`dev_lab.dev.testtemp`: a test temp dir is an owned system-temp entry, never output/."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from lab_commons.temp import TEMP_PREFIX

from dev_lab.dev import testtemp
from dev_lab.dev.writeroots import owned_globs

pytest_plugins = ['pytester']


def _config(root: Path, basetemp: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(option=SimpleNamespace(basetemp=basetemp), rootpath=root)


def _owned_temp_entry(path: Path, kind: str) -> bool:
    system = Path(tempfile.gettempdir()).resolve()
    entry = path.resolve()
    return entry.parent == system and entry.name.startswith(f'{TEMP_PREFIX}{kind}-')


def test_this_sessions_tmp_path_lives_in_an_owned_system_temp_entry(tmp_path: Path) -> None:
    """D104: the session's base temp is a direct, prefixed entry of system temp -- the sweep's to age out."""
    system = Path(tempfile.gettempdir()).resolve()
    base = next(p for p in tmp_path.resolve().parents if p.parent == system)
    assert _owned_temp_entry(base, testtemp.KIND)


def test_an_unset_basetemp_becomes_a_fresh_owned_temp_entry(tmp_path: Path) -> None:
    config = _config(tmp_path)
    testtemp.configure(config)
    chosen = Path(config.option.basetemp)
    assert chosen.is_dir()
    assert _owned_temp_entry(chosen, testtemp.KIND)
    assert any(Path(chosen.name).match(glob) for glob in owned_globs({})), 'tmpsweep must own it'


def test_two_sessions_never_share_a_base_temp(tmp_path: Path) -> None:
    first, second = _config(tmp_path), _config(tmp_path)
    testtemp.configure(first)
    testtemp.configure(second)
    assert first.option.basetemp != second.option.basetemp


@pytest.mark.parametrize('under', ['output/logs/26/11/20/pytest/x', 'output/x', 'out/logs/x'])
def test_planted_a_basetemp_under_output_is_refused(tmp_path: Path, under: str) -> None:
    """PLANTED (OUTPUT-HOLDS-NO-CODE, D104): a test-temp root under output/ holds planted code; refused by name."""
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.parts]\noutput = "out/logs"\n', encoding='utf-8')
    with pytest.raises(pytest.UsageError, match=r'OUTPUT-HOLDS-NO-CODE.*dev_lab\.dev\.testtemp'):
        testtemp.configure(_config(tmp_path, basetemp=str(tmp_path / under)))


def test_a_basetemp_outside_output_is_kept(tmp_path: Path) -> None:
    """The control beside the refusal: the same call with a path outside every output tree passes."""
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.parts]\noutput = "out/logs"\n', encoding='utf-8')
    config = _config(tmp_path, basetemp=str(tmp_path / 'inner'))
    testtemp.configure(config)
    assert config.option.basetemp == str(tmp_path / 'inner')


def test_a_script_suite_s_temp_env_points_every_temp_variable_at_one_owned_entry() -> None:
    """``os.tmpdir()`` reads TMPDIR (POSIX) or TEMP/TMP (Windows), so all three name one fresh owned entry."""
    with testtemp.script_temp_env({'PATH': 'p', 'TEMP': 'C:/elsewhere'}) as env:
        temp = Path(env['TMPDIR'])
        assert env['TEMP'] == env['TMP'] == env['TMPDIR']
        assert temp.is_dir()
        assert _owned_temp_entry(temp, testtemp.SCRIPT_KIND)
        assert env['PATH'] == 'p', 'the rest of the environment is kept'
        (temp / 'left.txt').write_text('x', encoding='utf-8')
    assert not temp.exists(), 'the block reclaims its entry, contents and all'


def test_a_script_suite_s_temp_is_reclaimed_when_the_block_raises() -> None:
    seen: list[Path] = []

    def cut_short() -> None:
        with testtemp.script_temp_env({}) as env:
            seen.append(Path(env['TMPDIR']))
            raise RuntimeError

    with pytest.raises(RuntimeError):
        cut_short()
    assert not seen[0].exists()


@pytest.mark.parametrize(
    ('passed', 'policy', 'kept'),
    [
        (True, 'all', False),
        (True, 'failed', False),
        (False, 'none', False),
        (False, 'failed', True),
        (False, 'all', True),
    ],
)
def test_release_reclaims_a_made_entry_unless_a_failure_is_kept(
    tmp_path: Path, *, passed: bool, policy: str, kept: bool
) -> None:
    """A pass never leaves its entry; a failure's stays as evidence unless the policy is ``none`` (PLANTED: kept)."""
    made = tmp_path / 'made'
    (made / 'deep').mkdir(parents=True)
    (made / 'deep' / 'ro.txt').write_text('x', encoding='utf-8')
    (made / 'deep' / 'ro.txt').chmod(0o444)  # a git object's bits: the removal must still go through
    testtemp.release(made, passed=passed, policy=policy)
    assert made.exists() is kept


def test_release_never_touches_a_basetemp_it_was_handed(tmp_path: Path) -> None:
    """A ``--basetemp`` an xdist controller or a caller chose is theirs: :func:`configure` returns ``None`` for it."""
    config = _config(tmp_path, basetemp=str(tmp_path / 'given'))
    (tmp_path / 'given').mkdir()
    made = testtemp.configure(config)
    testtemp.release(made, passed=True, policy='none')
    assert made is None
    assert (tmp_path / 'given').is_dir()


@pytest.mark.parametrize(('body', 'left'), [('pass', 0), ('assert False', 1)])
def test_a_session_leaves_nothing_in_the_system_temp_dir_unless_it_failed(tmp_path: Path, body: str, left: int) -> None:
    """END TO END: a real pytest process with TEMP/TMP/TMPDIR on an empty dir; a pass leaves it empty.

    PLANTED CONTROL: the failing session keeps exactly its one owned entry, so an assertion of "empty" is one
    the scan can fail.
    """
    sandbox, temp = tmp_path / 'sandbox', tmp_path / 'temp'
    sandbox.mkdir()
    temp.mkdir()
    (sandbox / '.pytest.ini').write_text('', encoding='utf-8')
    (sandbox / 'test_one.py').write_text(
        f'def test_one(tmp_path):\n    (tmp_path / "f.txt").write_text("x")\n    {body}\n', encoding='utf-8'
    )
    env = os.environ | dict.fromkeys(('TEMP', 'TMP', 'TMPDIR'), str(temp))
    run = subprocess.run(
        [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-p', 'no:randomly', 'test_one.py'],
        cwd=sandbox,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (run.returncode == 0) is (left == 0), run.stdout + run.stderr
    entries = sorted(temp.iterdir())
    assert len(entries) == left, entries
    assert all(entry.name.startswith(f'{TEMP_PREFIX}{testtemp.KIND}-') for entry in entries)


def test_a_pytester_run_roots_at_its_sandbox(pytester: pytest.Pytester) -> None:
    """PLANTED: without the sandbox bound, the inner run would root at whatever config sits above system temp."""
    pytester.makepyfile('def test_x():\n    pass\n')
    result = pytester.runpytest_subprocess()
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines([f'rootdir: {pytester.path}'])
