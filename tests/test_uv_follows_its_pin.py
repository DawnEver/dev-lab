"""A STALE uv FOLLOWS ITS PIN before a lock is written (user ruling 2026-11-06, the host-G incident).

Host G ran uv 0.13.5 against a 0.13.7 pin and every relock failed for hours until a human ran winget. The door now
moves the host's uv to EXACTLY :func:`~dev_lab.dev.lockcheck.uv_version` through the route it was installed by, and
refuses only when that cannot land. No test reaches an installer: the runner is injected.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest

from dev_lab.dev import _dep_project, dep, uvfollow
from dev_lab.dev.lockcheck import uv_version
from dev_lab.dev.netverb import Attempt, Diagnosis, Report
from dev_lab.dev.uvfollow import WINGET_ID, Route, follow, route_of, update_argv

_STALE = '0.13.5'
_WINGET_UV = r'C:\Users\x\AppData\Local\Microsoft\WinGet\Links\uv.exe'
_WINGET_PACKAGE_UV = r'C:\Users\x\AppData\Local\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source\uv.exe'
_STANDALONE_UV = '/home/x/.local/bin/uv'


def _report(argv: Sequence[str], code: int) -> Report:
    diagnosis = Diagnosis.SUCCEEDED if code == 0 else Diagnosis.UNCLASSIFIED
    return Report(argv=tuple(argv), attempts=(Attempt(1, code, '', diagnosis),), allowed_attempts=1)


class _Host:
    """One host's uv: *version* until the injected installer runs, then what that installer installs."""

    def __init__(self, version: str, *, installs: str | None) -> None:
        self.version = version
        self.installs = installs
        self.ran: list[tuple[str, ...]] = []

    def version_of(self, _uv: str) -> str:
        return self.version

    def run(self, argv: Sequence[str], **_kwargs: object) -> Report:
        self.ran.append(tuple(argv))
        if self.installs is None:
            return _report(argv, 1)
        self.version = self.installs
        return _report(argv, 0)


@pytest.mark.parametrize(
    ('uv', 'route'),
    [(_WINGET_UV, Route.WINGET), (_WINGET_PACKAGE_UV, Route.WINGET), (_STANDALONE_UV, Route.STANDALONE)],
)
def test_the_route_is_read_from_where_the_binary_lives(uv: str, route: Route) -> None:
    assert route_of(uv) is route


def test_a_winget_uv_is_reinstalled_at_exactly_the_pinned_version() -> None:
    argv = update_argv(_WINGET_UV, '0.13.7')
    assert argv[:2] == ['winget', 'install']
    assert argv[argv.index('--id') + 1] == WINGET_ID
    assert argv[argv.index('--version') + 1] == '0.13.7'
    assert '--exact' in argv
    assert '--disable-interactivity' in argv


def test_a_standalone_uv_updates_itself_to_exactly_the_pinned_version() -> None:
    assert update_argv(_STANDALONE_UV, '0.13.7') == [_STANDALONE_UV, 'self', 'update', '0.13.7']


@pytest.mark.parametrize('uv', [_WINGET_UV, _STANDALONE_UV])
def test_a_stale_uv_is_detected_and_moved_through_its_own_route(uv: str) -> None:
    host = _Host(_STALE, installs=uv_version())
    assert follow(uv, uv_version(), version_of=host.version_of, run=host.run) == ''
    assert host.ran == [tuple(update_argv(uv, uv_version()))]
    assert host.version == uv_version()


def test_planted_control_the_pinned_uv_runs_no_installer() -> None:
    host = _Host(uv_version(), installs=uv_version())
    assert follow(_WINGET_UV, uv_version(), version_of=host.version_of, run=host.run) == ''
    assert host.ran == []


@pytest.mark.parametrize('installs', [None, '0.13.6'])
def test_a_uv_that_does_not_reach_the_pin_says_why(installs: str | None) -> None:
    """A failed installer, and an installer that lands another version, both leave the uv refused, by name."""
    host = _Host(_STALE, installs=installs)
    why = follow(_STANDALONE_UV, uv_version(), version_of=host.version_of, run=host.run)
    assert _STALE in why
    assert uv_version() in why
    assert 'self update' in why


def _project(root: Path) -> None:
    (root / 'pyproject.toml').write_text(
        '[project]\nname="empty"\nversion="0"\n[project.optional-dependencies]\ndev=[]\n', encoding='utf-8'
    )


def test_the_dependency_door_moves_a_stale_uv_then_writes_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The G incident, end to end: a stale uv on PATH no longer fails the lock -- it follows, then writes."""
    _project(tmp_path)
    host = _Host(_STALE, installs=uv_version())
    monkeypatch.setattr(_dep_project, 'installed_uv_version', host.version_of)
    monkeypatch.setattr(uvfollow, 'run_network_verb', host.run)
    calls: list[tuple[str, ...]] = []

    def run(argv: Sequence[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(tuple(argv))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    assert dep.main(['--lock-upgrade'], cwd=tmp_path, run=run) == 0
    assert len(host.ran) == 1
    assert uv_version() in host.ran[0]
    assert any('lock' in call for call in calls)
