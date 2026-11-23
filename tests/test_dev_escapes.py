"""``dev_lab.dev.escapes`` -- a write that escaped the allowed roots is found on the tick and alarmed once.

User ruling 2026-11-03: every write lands in a repo's ``output/``/``scratch/`` or the machine home. The refusal
hook stops a write it can read; this census is the backstop for one it cannot (a target spelled through a
variable, a vendor tool's own temp). PLANTED CONTROLS: a new file under a watched root is found once, an old one
and an allowed root's entry never; the home's top level is watched one level deep, never walked.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from lab_commons.home import HOME_ENV
from lab_commons.hpc.layout import ROOT_VAR

from dev_lab.dev import escapes
from dev_lab.dev.forgealarm import ESCAPE, Alarm


def _touch(path: Path, age_s: float = 0.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('x', encoding='utf-8')
    stamp = time.time() - age_s
    os.utime(path, (stamp, stamp))
    return path


def test_a_new_entry_under_a_watched_root_is_found_and_an_old_one_is_not(tmp_path: Path) -> None:
    watched = tmp_path / 'tmp'
    _touch(watched / 'old.txt', age_s=3600)
    fresh = _touch(watched / 'pr_full.json')
    found = escapes.scan((watched,), home=tmp_path / 'home', allowed=(), since=time.time() - 60)
    assert found == [fresh]


def test_the_home_top_level_is_watched_one_level_deep_and_an_allowed_root_never(tmp_path: Path) -> None:
    home = tmp_path / 'home'
    stray = _touch(home / 'output' / 'run.log')
    _touch(home / '.acme-home' / 'state' / 'x.json')
    _touch(home / 'Documents' / 'org-x' / 'repo' / 'output' / 'a.txt')
    found = escapes.scan((), home=home, allowed=(home / '.acme-home', home / 'Documents'), since=time.time() - 60)
    assert found == [stray.parent]


def test_a_tick_alarms_each_escape_once_and_remembers_where_it_stopped(tmp_path: Path) -> None:
    watched = tmp_path / 'tmp'
    _touch(watched / 'old.txt', age_s=3600)
    state = tmp_path / 'escapes.json'
    raised: list[Alarm] = []
    escapes.step('o/r', alarm=raised.append, roots=(watched,), home=tmp_path / 'home', allowed=(), state=state)
    assert raised == [], 'the first scan is a baseline: what already sits there is not news'
    state.write_text(json.dumps({'scanned': time.time() - 30, 'home': []}), encoding='utf-8')  # the baseline, 30 s ago
    _touch(watched / 'probe.py', age_s=10)
    for _tick in range(2):
        escapes.step('o/r', alarm=raised.append, roots=(watched,), home=tmp_path / 'home', allowed=(), state=state)
    assert [(a.kind, Path(a.about).name) for a in raised] == [(ESCAPE, 'probe.py')]
    (only,) = raised
    assert 'output/' in only.body
    assert 'scratch/' in only.body


def _machine(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    """The user home *home*, its machine home ``.acme-home``, no repos: ``lab_commons.home`` judges against it."""
    monkeypatch.setattr(Path, 'home', classmethod(lambda _cls: home))
    monkeypatch.setenv(HOME_ENV, str(home / '.acme-home'))
    monkeypatch.delenv('XDG_CONFIG_HOME', raising=False)


def test_the_home_judges_its_entries_through_the_machine_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / 'home'
    _machine(monkeypatch, home)
    _touch(home / '.git-credentials')
    _touch(home / '.claude' / 'settings.json')
    _touch(home / '.claude-evans' / 'settings.json')
    _touch(home / '.acme-home' / 'state' / 'x.json')
    stray = _touch(home / '.foo')
    found = escapes.scan((), home=home, allowed=escapes.allowed_roots(), since=time.time() - 60)
    assert found == [stray], "git's credential store, Claude's homes and the machine home are not escapes; .foo is"


def _tick(home: Path, state: Path, raised: list[Alarm]) -> None:
    escapes.step('o/r', alarm=raised.append, roots=(), home=home, state=state)


def _rewind(state: Path, by_s: float = 30.0) -> None:
    """Move the recorded scan time *by_s* back, the home's names kept: the next tick sees what changed since."""
    record = json.loads(state.read_text(encoding='utf-8'))
    state.write_text(json.dumps(record | {'scanned': time.time() - by_s}), encoding='utf-8')


def test_a_served_account_alarms_neither_its_declared_root_nor_its_login_dotfiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MEASURED 2026-11-22: every tick alarmed ``~/.bashrc``, ``~/.cache``, ``~/.config`` and ``~/lab`` itself.

    PLANTED CONTROL, both ways: beside them a file a run writes into the home, and a NEW dotfile, still alarm.
    """
    home = tmp_path / 'home'
    _machine(monkeypatch, home)
    monkeypatch.setenv(ROOT_VAR, str(home / 'lab'))
    state = tmp_path / 'escapes.json'
    raised: list[Alarm] = []
    for name in ('.bashrc', '.bash_profile', '.cache/uv/x', '.config/git/ignore', '.cargo/env', 'lab/runs/x'):
        _touch(home / name, age_s=3600)
    _tick(home, state, raised)  # the baseline: it records which entries the home already held
    _rewind(state)
    for name in ('.bashrc', '.cache/new', '.config/new', '.cargo/new', 'lab/serve', '.git-credentials.reader'):
        _touch(home / name)  # the login profile's export line, a cache, the credential door, the run tree
    _touch(home / '.git-credentials.bak-20261122T000000Z')
    stray, hidden = _touch(home / 'run.log'), _touch(home / '.probe')
    _tick(home, state, raised)
    assert sorted(Path(a.about).name for a in raised) == sorted([stray.name, hidden.name])
    _tick(home, state, raised)
    assert len(raised) == 2, 'an escape is sounded once: the scan time moved past it'


def test_the_declared_root_is_allowed_only_where_one_is_declared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / 'home'
    _machine(monkeypatch, home)
    monkeypatch.delenv(ROOT_VAR, raising=False)
    assert home / 'lab' not in escapes.allowed_roots()
    monkeypatch.setenv(ROOT_VAR, str(home / 'lab'))
    assert home / 'lab' in escapes.allowed_roots()


def test_a_state_that_names_no_home_entries_is_a_baseline_again(tmp_path: Path) -> None:
    home, state = tmp_path / 'home', tmp_path / 'escapes.json'
    _touch(home / '.bashrc')
    state.write_text(json.dumps({'scanned': time.time() - 30}), encoding='utf-8')
    raised: list[Alarm] = []
    escapes.step('o/r', alarm=raised.append, roots=(), home=home, allowed=(), state=state)
    assert raised == []
    assert json.loads(state.read_text(encoding='utf-8'))['home'] == ['.bashrc']
