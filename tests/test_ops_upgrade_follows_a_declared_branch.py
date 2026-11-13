"""``ops upgrade --follow``: a host declaring ``[ops.upgrade] follow`` upgrades itself to that branch's tip.

The declaration authorizes the install (user ruling 2026-11-13: no consent code per upgrade), so the guards are the
host's own: the step must walk the branch's first-parent line forward from the installed sha, the self-check must
pass or the old sha is restored, every attempt is one audit line, and no declaration means no auto-upgrade.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from _ops_fixtures import git
from test_ops_upgrade_installs_the_locked_family import LOCK, OLD, TIP, _config

from dev_lab.ops import __main__ as ops_main
from dev_lab.ops import configdoor, install, upgradefollow
from dev_lab.ops.upgradefollow import Line

FOLLOW = 'follow = "main"\n'


class Host:
    """An installed commit, a self-check that passes or fails per commit, and every install and alert recorded."""

    def __init__(self, *, failing: frozenset[str] = frozenset()) -> None:
        """A host at OLD whose self-check fails while any sha of *failing* is installed."""
        self.installed, self.failing, self.installs, self.alerts = OLD, failing, [], []

    def probe(self, argv: Sequence[str]) -> tuple[int, str]:
        if '-c' in argv and 'direct_url' in argv[-1]:
            return 0, self.installed
        if self.installed in self.failing and ('breakglass' in argv or 'load(' in ' '.join(argv)):
            return 1, 'ImportError: planted'
        return 0, ''

    def install(self, argv: Sequence[str]) -> tuple[int, str]:
        self.installs.append(argv[-1].rpartition('@')[2])
        self.installed = self.installs[-1]
        return 0, ''

    def alert(self, title: str, detail: str) -> bool:
        self.alerts.append(f'{title}: {detail}')
        return True


def _line(*, fast_forward: bool = True, on_line: bool = True, behind: bool = False) -> upgradefollow.LineReader:
    def read(_source: str, ref: str, installed: str) -> Line:
        assert (ref, installed) == ('main', OLD)
        return Line(tip=TIP, lock=LOCK, behind=behind, fast_forward=fast_forward, on_line=on_line)

    return read


def _follow(tmp: Path, host: Host, line: upgradefollow.LineReader, extra: str = FOLLOW) -> tuple[int, str]:
    return upgradefollow.follow(
        _config(tmp, extra), line=line, install=host.install, probe=host.probe, alert=host.alert,
        fetch=lambda _source, ref: (ref, LOCK), candidate=lambda _config: None,
    )  # fmt: skip


def _audit(tmp: Path) -> list[dict[str, str]]:
    path = tmp / 'home' / upgradefollow.AUDIT
    return [json.loads(row) for row in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []


def test_a_moved_tip_on_the_line_is_installed_and_audited(tmp_path: Path) -> None:
    """The planted control of every refusal below: the same host installs when the guards hold."""
    host = Host()
    code, said = _follow(tmp_path, host, _line())
    assert code == 0, said
    assert host.installs == [TIP]
    assert [(row['from'], row['to'], row['result']) for row in _audit(tmp_path)] == [(OLD, TIP, 'installed')]
    assert host.alerts == []


def test_a_non_fast_forward_target_is_refused_alerted_and_audited(tmp_path: Path) -> None:
    host = Host()
    code, said = _follow(tmp_path, host, _line(fast_forward=False, on_line=False))
    assert code == 2
    assert 'not a fast-forward' in said
    assert host.installs == []
    assert [row['result'] for row in _audit(tmp_path)] == ['refused']
    assert len(host.alerts) == 1


def test_a_target_off_the_first_parent_line_is_refused(tmp_path: Path) -> None:
    host = Host()
    code, said = _follow(tmp_path, host, _line(on_line=False))
    assert code == 2
    assert 'first-parent line' in said
    assert host.installs == []


def test_a_standing_refusal_alerts_and_audits_once(tmp_path: Path) -> None:
    host = Host()
    for _tick in range(3):
        _follow(tmp_path, host, _line(fast_forward=False, on_line=False))
    assert len(_audit(tmp_path)) == 1
    assert len(host.alerts) == 1


def test_a_failed_self_check_rolls_back_alerts_and_audits(tmp_path: Path) -> None:
    host = Host(failing=frozenset({TIP}))
    code, said = _follow(tmp_path, host, _line())
    assert code == 1
    assert host.installs == [TIP, OLD]
    assert host.installed == OLD
    assert 'restored' in said
    assert [row['result'] for row in _audit(tmp_path)] == ['rolled-back']
    assert len(host.alerts) == 1


def test_no_declaration_means_no_auto_upgrade(tmp_path: Path) -> None:
    host = Host()

    read: list[str] = []

    def unread(*args: str) -> Line:
        read.extend(args)
        return Line(tip=TIP, lock=LOCK, behind=False, fast_forward=True, on_line=True)

    code, said = _follow(tmp_path, host, unread, extra='')
    assert code == 2
    assert 'declares no follow' in said
    assert (host.installs, _audit(tmp_path), read) == ([], [], [])


def test_an_unmoved_or_ahead_install_is_a_quiet_no_op(tmp_path: Path) -> None:
    host = Host()
    code, said = _follow(tmp_path, host, _line(behind=True, fast_forward=False, on_line=False))
    assert code == 0
    assert 'nothing to do' in said
    assert (host.installs, _audit(tmp_path), host.alerts) == ([], [], [])


def test_the_line_is_read_from_git(tmp_path: Path) -> None:
    """The real reader: a first-parent step is on the line; a side-merged sha is a fast-forward OFF it."""
    work = tmp_path / 'work'
    work.mkdir()
    git(work, 'init', '-q', '-b', 'main')
    git(work, 'config', 'user.email', 't@t')
    git(work, 'config', 'user.name', 't')
    (work / 'uv.lock').write_text(LOCK, encoding='utf-8')
    git(work, 'add', '.')
    git(work, 'commit', '-qm', 'base')
    base = git(work, 'rev-parse', 'HEAD')
    git(work, 'checkout', '-qb', 'side')
    git(work, 'commit', '-q', '--allow-empty', '-m', 'side')
    side = git(work, 'rev-parse', 'HEAD')
    git(work, 'checkout', '-q', 'main')
    git(work, 'commit', '-q', '--allow-empty', '-m', 'trunk')
    git(work, 'merge', '-q', '--no-ff', '-m', 'merge side', 'side')
    tip = git(work, 'rev-parse', 'HEAD')
    source = work.as_uri()
    stepped = upgradefollow.read_line(source, 'main', base)
    assert (stepped.tip, stepped.lock, stepped.fast_forward, stepped.on_line) == (tip, LOCK, True, True)
    assert upgradefollow.read_line(source, 'main', side).on_line is False
    assert upgradefollow.read_line(source, 'main', side).fast_forward is True
    assert upgradefollow.read_line(source, 'main', tip).behind is True
    assert upgradefollow.read_line(source, 'main', 'e' * 40).fast_forward is False


def test_the_verb_refuses_without_a_declaration(tmp_path: Path) -> None:
    config = _config(tmp_path)
    assert ops_main.main(['--config', str(config.path), 'upgrade', '--follow']) == 2


def test_follow_is_boundary_and_its_schedule_routine() -> None:
    assert configdoor.boundary(('ops.upgrade.follow',)) == ('ops.upgrade.follow',)
    assert configdoor.boundary(('ops.upgrade.schedule',)) == ()


def test_a_follow_declaration_renders_a_root_timer(tmp_path: Path) -> None:
    rendered = install.files(_config(tmp_path, FOLLOW + 'schedule = "*:0/30"\n'))
    assert 'upgrade --follow' in rendered['etc/systemd/system/dev-lab-ops-upgrade-follow.service']
    assert 'OnCalendar=*:0/30' in rendered['etc/systemd/system/dev-lab-ops-upgrade-follow.timer']
    assert not any('upgrade-follow' in path for path in install.files(_config(tmp_path)))
