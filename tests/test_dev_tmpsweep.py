"""``dev_lab.dev.tmpsweep``: the WRITES-STAY-IN-THE-TREE census and sweep, over planted roots only.

The roots are injected (:class:`dev_lab.dev.writeroots.Root`), never the real temp dir. Planted controls: a fresh
entry, the harness ``claude/`` subtree, a declared cache, a checkout, a link and a census-only root all survive
``--apply``; an old entry in a temp root does not.
"""

from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path

import pytest

from dev_lab.dev.tmpsweep import census, main, session_report, sweep
from dev_lab.dev.writeroots import Root

_DAY = 86400.0


def _age(path: Path, days: float) -> None:
    then = time.time() - days * _DAY
    for current, _dirs, files in os.walk(path):
        for name in files:
            os.utime(Path(current) / name, (then, then))
        os.utime(current, (then, then))
    if path.is_file():
        os.utime(path, (then, then))


@pytest.fixture
def planted(tmp_path: Path) -> dict[str, Path]:
    temp, src, home = tmp_path / 'temp', tmp_path / 'src', tmp_path / 'home'
    for one in (temp, src, home):
        one.mkdir()
    (temp / 'old.py').write_text('x', encoding='utf-8')
    (temp / 'olddir').mkdir()
    (temp / 'olddir' / 'a.txt').write_text('x', encoding='utf-8')
    (temp / 'fresh.py').write_text('x', encoding='utf-8')
    (temp / 'claude' / 'h' / 's').mkdir(parents=True)
    (temp / 'cache').mkdir()
    (temp / 'repo' / '.git').mkdir(parents=True)
    (src / 'old.py').write_text('x', encoding='utf-8')
    (home / 'loose.py').write_text('x', encoding='utf-8')
    (home / '.config').mkdir()
    (home / 'Documents').mkdir()
    for name in ('old.py', 'olddir', 'claude', 'cache', 'repo'):
        _age(temp / name, 30)
    _age(src / 'old.py', 30)
    return {'temp': temp, 'src': src, 'home': home}


def _roots(planted: dict[str, Path]) -> tuple[Root, ...]:
    return (Root(planted['temp'], 'temp'), Root(planted['src'], 'census'), Root(planted['home'], 'home'))


def _excluded(planted: dict[str, Path]) -> tuple[Path, ...]:
    return (planted['temp'] / 'claude', planted['temp'] / 'cache')


def test_the_census_lists_direct_entries_minus_exclusions_and_home_dot_and_dirs(planted: dict[str, Path]) -> None:
    found = {entry.path for entry in census(_roots(planted), _excluded(planted))}
    temp = planted['temp']
    assert found == {
        temp / 'old.py', temp / 'olddir', temp / 'fresh.py', temp / 'repo', planted['src'] / 'old.py',
        planted['home'] / 'loose.py',
    }  # fmt: skip


def test_the_sweep_removes_only_old_entries_of_a_temp_root(planted: dict[str, Path]) -> None:
    entries = census(_roots(planted), _excluded(planted))
    removed, kept = sweep(entries, max_age_days=7.0)
    temp = planted['temp']
    assert set(removed) == {temp / 'old.py', temp / 'olddir'}
    assert not (temp / 'old.py').exists()
    assert not (temp / 'olddir').exists()
    for survivor in ('fresh.py', 'claude', 'cache', 'repo'):
        assert (temp / survivor).exists(), survivor
    assert (planted['src'] / 'old.py').exists()
    assert (planted['home'] / 'loose.py').exists()
    assert {path for path, _why in kept} >= {temp / 'repo', temp / 'fresh.py'}


def test_a_directory_with_one_fresh_file_is_in_use_and_kept(planted: dict[str, Path]) -> None:
    (planted['temp'] / 'olddir' / 'live.log').write_text('x', encoding='utf-8')
    removed, _kept = sweep(census(_roots(planted), _excluded(planted)), max_age_days=7.0)
    assert planted['temp'] / 'olddir' not in removed
    assert (planted['temp'] / 'olddir' / 'a.txt').exists()


def test_a_link_is_never_followed_or_removed(planted: dict[str, Path], tmp_path: Path) -> None:
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'keep.txt').write_text('x', encoding='utf-8')
    link = planted['temp'] / 'link'
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('this host refuses symlink creation without privilege')
    removed, _kept = sweep(census(_roots(planted), _excluded(planted)), max_age_days=0.0)
    assert link not in removed
    assert (outside / 'keep.txt').exists()


def test_the_session_report_names_scripts_written_since_the_session_began(planted: dict[str, Path]) -> None:
    reason = session_report(_roots(planted), _excluded(planted), since=time.time() - 3600)
    assert reason is not None
    assert reason.startswith('WRITES-STAY-IN-THE-TREE: ')
    assert 'fresh.py' in reason
    assert 'loose.py' in reason
    assert 'old.py' not in reason
    assert session_report(_roots(planted), _excluded(planted), since=time.time() + 60) is None


def test_the_stop_hook_blocks_once(planted: dict[str, Path], monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr('dev_lab.dev.tmpsweep._declared', lambda: (_roots(planted), _excluded(planted)))
    payload = {'hook_event_name': 'Stop', 'transcript_path': str(planted['home'] / 'nothing.jsonl')}
    assert main(['stop'], stdin=io.StringIO(json.dumps(payload))) == 0
    assert json.loads(capsys.readouterr().out)['decision'] == 'block'
    payload['stop_hook_active'] = True
    assert main(['stop'], stdin=io.StringIO(json.dumps(payload))) == 0
    assert capsys.readouterr().out == ''


def test_the_command_is_read_only_without_apply(planted: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('dev_lab.dev.tmpsweep._declared', lambda: (_roots(planted), _excluded(planted)))
    assert main([]) == 0
    assert (planted['temp'] / 'old.py').exists()
    assert main(['--apply', '--max-age-days', '7']) == 0
    assert not (planted['temp'] / 'old.py').exists()
