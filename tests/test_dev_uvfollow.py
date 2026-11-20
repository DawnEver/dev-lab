"""UV ON A HOST FOLLOWS THE PIN wherever dev-lab installs or ticks a host -- not only where a lock is written.

Measured 2026-11-09: the pin was 0.13.7, the newest release; a cloud host ran 0.12.5, a cluster account's was
unknown -- the serve relock moved the pin and nothing moved those hosts. Each place now calls the one follower
(:func:`dev_lab.dev._dep_project.follow_pin`, through :mod:`dev_lab.dev.uvfollow`), and ``family check`` names a
pin lagging the newest release.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest

from dev_lab.dev import lockcheck, uvfollow
from dev_lab.dev.family import watch
from dev_lab.dev.hpcaccount import checks, tick
from dev_lab.dev.netverb import Attempt, Diagnosis, Report, classify, is_retryable
from dev_lab.dev.uvfollow import follow
from dev_lab.ops import upgrade


def _recorder(said: str) -> tuple[list[tuple[str, str]], object]:
    calls: list[tuple[str, str]] = []

    def follow(uv: str, version: str) -> str:
        calls.append((uv, version))
        return said

    return calls, follow


def test_a_cluster_tick_moves_the_hosts_uv_to_the_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    """On the kit's tick only (the host checkout's one writer). PLANTED CONTROL: another repo's tick never does."""
    calls, follow = _recorder('')
    monkeypatch.setattr(tick, 'follow_pin', follow)
    monkeypatch.setattr(tick.shutil, 'which', lambda _name: '/opt/tools/uv')
    assert tick.follow_uv('dev-lab') == ''
    assert calls == [('/opt/tools/uv', tick.uv_version())]
    assert tick.follow_uv('some-repo') == ''
    assert len(calls) == 1


def test_a_cluster_deploy_moves_a_present_uv_to_the_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    calls, follow = _recorder('uv 0.12.5 at /u/uv did not follow to 0.13.7')
    monkeypatch.setattr(checks, 'follow_pin', follow)
    monkeypatch.setattr(checks.shutil, 'which', lambda _name: '/u/uv')
    assert checks.follow_uv() == 'uv 0.12.5 at /u/uv did not follow to 0.13.7'
    monkeypatch.setattr(checks.shutil, 'which', lambda _name: None)
    assert checks.follow_uv() == '', 'PLANTED CONTROL: no uv yet is the installer step, not a follow'
    assert len(calls) == 1


def test_an_ops_upgrade_moves_the_hosts_uv_to_the_new_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pin is the NEWLY installed dev-lab's, read in a fresh ``[ops] python``; a refused probe follows nothing."""
    calls, follow = _recorder('')
    monkeypatch.setattr(upgrade, 'follow_pin', follow)
    config = SimpleNamespace(python='/py', upgrade=SimpleNamespace(uv='/opt/uv'))
    assert upgrade.follow_uv(config, lambda _argv: (0, '0.13.7\n')) == ''
    assert calls == [('/opt/uv', '0.13.7')]
    assert upgrade.follow_uv(config, lambda _argv: (1, '')) == 'the new pin is unreadable; uv left as it is'
    assert len(calls) == 1, 'PLANTED CONTROL'


def test_the_pin_lagging_the_newest_release_is_named_under_its_policy() -> None:
    """D101 (2026-11-20): ``minor`` names only a newer minor. PLANTED CONTROL: ``patch`` names the patch it skips."""
    assert (
        uvfollow.lag('0.12.5', '0.13.7', 'minor') == 'the uv pin 0.12.5 lags the newest release 0.13.7 (minor policy)'
    )
    assert uvfollow.lag('0.13.7', '0.13.9', 'minor') == ''
    assert (
        uvfollow.lag('0.13.7', '0.13.9', 'patch') == 'the uv pin 0.13.7 lags the newest release 0.13.9 (patch policy)'
    )
    assert uvfollow.lag('0.13.7', '0.13.7', 'patch') == ''


def test_the_policy_decides_where_the_pin_moves_and_an_unknown_one_is_refused_by_name() -> None:
    assert uvfollow.due('0.13.7', '0.13.9', 'minor') == '0.13.7'
    assert uvfollow.due('0.13.7', '0.14.2', 'minor') == '0.14.2'
    assert uvfollow.due('0.13.7', '1.0.0', 'minor') == '1.0.0'
    assert uvfollow.due('0.13.7', '0.13.9', 'patch') == '0.13.9'
    with pytest.raises(ValueError, match='none of minor, patch'):
        uvfollow.due('0.13.7', '0.13.9', 'nightly')


def test_dev_labs_own_pin_declares_the_minor_policy() -> None:
    assert lockcheck.uv_policy() == 'minor'


def test_family_check_names_the_kits_pin_lagging_the_newest_release() -> None:
    """PLANTED CONTROLS: a pin at the newest says nothing; an unreadable release list is named, never silent."""

    def offline() -> str:
        msg = 'offline'
        raise OSError(msg)

    assert [f.what for f in watch.uv_pin('0.12.5', lambda: '0.13.7', 'minor')] == [
        'uv pin: the uv pin 0.12.5 lags the newest release 0.13.7 (minor policy) -- the serve relock raises it; run it'
    ]
    assert watch.uv_pin('0.13.7', lambda: '0.13.7', 'minor') == []
    assert watch.uv_pin('0.13.7', offline, 'minor')[0].what.startswith('unread:')


#: The refusal measured 2026-11-20, shaped as winget printed it.
_HELD = 'Starting package install...\nremove: Access is denied.: "{package}\\uv.exe"\nInstaller failed: 1\n'


def _held_report(argv: Sequence[str], output: str, code: int = 1) -> Report:
    diagnosis = classify(output) if code else Diagnosis.SUCCEEDED
    return Report(argv=tuple(argv), attempts=(Attempt(1, code, output, diagnosis),), allowed_attempts=3)


def test_a_held_winget_uv_is_classified_by_name_moved_aside_and_installed_again(tmp_path: Path) -> None:
    """A running uv.exe that winget cannot remove is ``file-held``, moved aside and installed over.

    2026-11-20: ``remove: Access is denied`` was "unclassified" 3/3. Now the executables are renamed aside and
    winget runs once more; a later follow deletes what nothing holds.

    PLANTED CONTROL: an unrelated failure moves nothing and installs once.
    """
    package = tmp_path / 'WinGet' / 'Packages' / 'astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe'
    package.mkdir(parents=True)
    for name in ('uv.exe', 'uvx.exe', 'uvw.exe'):
        (package / name).write_text('old', encoding='utf-8')
    (package / f'uv.exe{uvfollow.ASIDE}').write_text('older', encoding='utf-8')  # left by an earlier follow
    output = _HELD.format(package=str(package))
    assert classify(output) is Diagnosis.FILE_HELD
    assert not is_retryable(Diagnosis.FILE_HELD)
    version = {'now': '0.14.0'}
    calls: list[tuple[str, ...]] = []

    def run(argv: Sequence[str], **_kw: object) -> Report:
        calls.append(tuple(argv))
        if len(calls) == 1:
            return _held_report(argv, output)
        version['now'] = '0.13.9'
        return _held_report(argv, '', 0)

    uv = str(package / 'uv.exe')
    assert follow(uv, '0.13.9', version_of=lambda _uv: version['now'], run=run) == ''
    assert len(calls) == 2
    aside = sorted(p.name for p in package.iterdir())
    assert aside == [f'{n}{uvfollow.ASIDE}' for n in ('uv.exe', 'uvw.exe', 'uvx.exe')]
    assert (package / f'uv.exe{uvfollow.ASIDE}').read_text(encoding='utf-8') == 'old', 'the older aside was swept'
    assert uvfollow.sweep(package) == ()
    assert list(package.iterdir()) == []

    other: list[tuple[str, ...]] = []

    def refused(argv: Sequence[str], **_kw: object) -> Report:
        other.append(tuple(argv))
        return _held_report(argv, 'No applicable installer found')

    (package / 'uv.exe').write_text('old', encoding='utf-8')
    assert follow(uv, '0.13.9', version_of=lambda _uv: '0.14.0', run=refused).startswith('uv 0.14.0 at ')
    assert len(other) == 1
    assert [p.name for p in package.iterdir()] == ['uv.exe']
