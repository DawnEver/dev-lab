"""FAMILY DRIFT: a pin left behind its dependency past the bound, or a host running what its lock does not pin, alarms.

The census reads git objects for real: a bare dependency repository with commits after the pin, and a bare
consumer whose ``integrate/main`` commits a lock pinning it. Only the clock and the alarm are planted.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NoReturn

import pytest

from dev_lab.dev import drift
from dev_lab.dev.forgealarm import DRIFT, Alarm
from dev_lab.dev.lockpins import Installed

_GIT = shutil.which('git') or 'git'
_NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)


def _git(root: Path, *argv: str, when: datetime | None = None) -> str:
    env = None
    if when is not None:
        stamp = when.isoformat()
        env = {**__import__('os').environ, 'GIT_COMMITTER_DATE': stamp, 'GIT_AUTHOR_DATE': stamp}
    done = subprocess.run(
        [_GIT, '-C', str(root), *argv], check=False, capture_output=True, text=True, encoding='utf-8', env=env,
        timeout=120,
    )  # fmt: skip
    assert done.returncode == 0, f'{argv}: {done.stderr}'
    return done.stdout.strip()


def _commit(repo: Path, name: str, when: datetime) -> str:
    (repo / name).write_text(name, encoding='utf-8')
    _git(repo, 'add', '-A')
    _git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', name, when=when)
    return _git(repo, 'rev-parse', 'HEAD')


#: The fixture's dependency is a local bare repo; production admits https only (drift.SCHEMES).
_LOCAL = ('https', 'file')


@pytest.fixture
def dependency(tmp_path: Path) -> tuple[str, str, str]:
    """``(url, pinned, head)``: a default branch two commits past the pin, the first of them 5 days ago."""
    work, bare = tmp_path / 'dep', tmp_path / 'dep.git'
    _git(tmp_path, 'init', '-q', '-b', 'integrate/main', str(work))
    pinned = _commit(work, 'a', _NOW - timedelta(days=9))
    _commit(work, 'b', _NOW - timedelta(days=5))
    head = _commit(work, 'c', _NOW - timedelta(days=1))
    _git(tmp_path, 'clone', '-q', '--bare', str(work), str(bare))
    return bare.as_uri(), pinned, head


def _lock(url: str, sha: str) -> str:
    return f'version = 1\n\n[[package]]\nname = "dev-lab"\nsource = {{ git = "{url}#{sha}" }}\n'


def test_the_lock_names_each_git_pin_with_its_url() -> None:
    text = _lock('https://github.com/DawnEver/dev-lab.git?rev=x', 'ab' * 20) + (
        '\n[[package]]\nname = "Lab_Commons"\nsource = { git = "https://h/lab-commons.git#cd" }\n'
        '\n[[package]]\nname = "pint"\nsource = { registry = "https://pypi.org/simple" }\n'
    )
    assert drift.sources(text) == {
        'dev-lab': ('https://github.com/DawnEver/dev-lab.git', 'ab' * 20),
        'lab-commons': ('https://h/lab-commons.git', 'cd'),
    }


def test_a_pin_behind_past_the_bound_is_a_finding_and_a_fresh_one_is_not(
    dependency: tuple[str, str, str], tmp_path: Path
) -> None:
    """PLANTED control: the same census with the pin AT the head finds nothing."""
    url, pinned, head = dependency
    cache = tmp_path / 'cache'
    lag = drift.lag('dev-lab', url, pinned, cache=cache, schemes=_LOCAL)
    assert (lag.behind, lag.head, lag.since) == (2, head, _NOW - timedelta(days=5))
    (found,) = drift.findings([lag], (), now=_NOW, bound=timedelta(days=2))
    assert found.about == 'dev-lab'
    assert '2 commits behind' in found.body
    assert pinned[:12] in found.body

    fresh = drift.lag('dev-lab', url, head, cache=cache, schemes=_LOCAL)
    assert fresh.behind == 0
    assert drift.findings([fresh], (), now=_NOW, bound=timedelta(days=2)) == ()


def test_a_pin_behind_inside_the_bound_waits_for_the_relock(dependency: tuple[str, str, str], tmp_path: Path) -> None:
    url, pinned, _ = dependency
    lag = drift.lag('dev-lab', url, pinned, cache=tmp_path / 'cache', schemes=_LOCAL)
    assert drift.findings([lag], (), now=_NOW, bound=timedelta(days=6)) == (), (
        'behind 5 days, bound 6: the relock has time'
    )


def test_a_host_running_what_its_lock_does_not_pin_is_a_finding() -> None:
    """PLANTED control: an install equal to the lock finds nothing."""
    pins = {'lab-commons': '82538656'}
    stale = (Installed('lab-commons', '0b352024'),)
    (found,) = drift.findings((), drift.host_mismatches(stale, pins), now=_NOW, bound=timedelta(days=2))
    assert '0b352024' in found.body
    assert '82538656' in found.body
    assert found.about == 'host:lab-commons'
    assert drift.host_mismatches((Installed('lab-commons', '82538656'),), pins) == ()


def test_each_finding_is_one_drift_alarm_naming_the_remedy(dependency: tuple[str, str, str], tmp_path: Path) -> None:
    url, pinned, _ = dependency
    (found,) = drift.findings(
        [drift.lag('dev-lab', url, pinned, cache=tmp_path / 'c', schemes=_LOCAL)], (), now=_NOW, bound=timedelta(0)
    )
    alarm = drift.alarm_of('https://forge/o/lab-commons', found)
    assert isinstance(alarm, Alarm)
    assert (alarm.kind, alarm.about) == (DRIFT, 'dev-lab')
    notice = alarm.as_notice()
    assert 'dev-lab' in notice.title
    assert 'relock' in notice.action


def test_the_bound_is_declared_and_defaults_to_two_days() -> None:
    assert drift.bound_of({}) == timedelta(days=2)
    assert drift.bound_of({'tool': {'dev_lab': {'drift': {'max_behind': '12 h'}}}}) == timedelta(hours=12)
    with pytest.raises(ValueError, match='unknown key'):
        drift.bound_of({'tool': {'dev_lab': {'drift': {'max_behnd': '1 d'}}}})


def test_the_serve_step_reads_integration_and_sounds_one_alarm_per_finding(
    dependency: tuple[str, str, str], tmp_path: Path
) -> None:
    url, pinned, _ = dependency
    seed, origin, clone = tmp_path / 'seed', tmp_path / 'o.git', tmp_path / 'clone'
    _git(tmp_path, 'init', '-q', '-b', 'integrate/main', str(seed))
    (seed / 'pyproject.toml').write_text(
        '[project]\nname = "x"\nversion = "0"\n[tool.dev_lab.integrator]\nintegration = "integrate/main"\n'
        '[tool.dev_lab.drift]\nmax_behind = "1 d"\n',
        encoding='utf-8',
    )
    (seed / 'uv.lock').write_text(_lock(url, pinned), encoding='utf-8')
    _git(seed, 'add', '-A')
    _git(seed, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'seed')
    _git(tmp_path, 'clone', '-q', '--bare', str(seed), str(origin))
    _git(tmp_path, 'clone', '-q', str(origin), str(clone))
    sounded: list[Alarm] = []
    said: list[str] = []
    drift.step(clone, 'o/x', say=said.append, alarm=sounded.append, now=_NOW, installed=(), schemes=('https', 'file'))
    assert [(a.kind, a.about) for a in sounded] == [(DRIFT, 'dev-lab')]
    said.clear()
    drift.step(clone, 'o/x', say=said.append, alarm=sounded.append, now=_NOW, installed=())
    assert any('refused' in line for line in said), 'a refused pin is said, and the step does not crash'
    assert _git(clone, 'status', '--porcelain') == '', 'the serving checkout is never written'


def test_the_repo_wide_pass_runs_the_census_after_the_relock_and_a_failure_is_said(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The census rides the elected poller's repo-wide pass; one that cannot run is said, never a crash."""
    from dev_lab.dev import forgeservesteps  # noqa: PLC0415 -- the serve steps import the whole forge

    order: list[str] = []
    for name in ('serve_close_landed', 'serve_sweep', 'serve_prune', 'serve_records_prune', 'hygiene', 'starved',
                 'prompt'):  # fmt: skip
        monkeypatch.setattr(forgeservesteps, name, lambda *_a, **_k: None)
    monkeypatch.setattr(forgeservesteps, 'ci_merges', lambda _root: False)
    monkeypatch.setattr(forgeservesteps, 'relock', lambda *_a, **_k: order.append('relock'))

    def census(*_a: object, **_k: object) -> None:
        order.append('drift')
        msg = 'git show failed'
        raise OSError(msg)

    monkeypatch.setattr(forgeservesteps, 'drift_step', census)
    said: list[str] = []
    forgeservesteps.repo_wide(
        tmp_path, 'r', lambda _r: None, 'h', (), clock=lambda: _NOW, say=said.append, alarm=lambda _a: None
    )  # fmt: skip
    assert order == ['relock', 'drift']
    assert said == ['[serve] the drift census did not run: git show failed']


@pytest.mark.parametrize(
    ('url', 'sha'),
    [
        ('ext::sh -c touch% /tmp/pwned', 'ab' * 20),
        ('--upload-pack=touch /tmp/pwned', 'ab' * 20),
        ('ssh://host/repo.git', 'ab' * 20),
        ('file:///srv/repo.git', 'ab' * 20),
        ('https://github.com/DawnEver/dev-lab.git', '--output=/tmp/x'),
    ],
)
def test_a_lock_url_that_is_not_https_or_an_option_is_refused_before_any_fetch(
    url: str, sha: str, tmp_path: Path
) -> None:
    """F-a1b33b2b8004: a ``source.git`` from uv.lock reaches ``git fetch`` only as an https URL, never an option."""
    with pytest.raises(ValueError, match='refused'):
        drift.lag('dev-lab', url, sha, cache=tmp_path / 'cache')
    assert not (tmp_path / 'cache').exists(), 'refused before anything is created'


def test_planted_control_an_https_url_passes_the_admission() -> None:
    drift.admit('https://github.com/DawnEver/dev-lab.git', 'ab' * 20, drift.SCHEMES)


def test_the_fetch_puts_the_url_after_a_double_dash_and_allows_only_the_declared_protocols() -> None:
    argv = drift.fetch_argv(Path('repo.git'), 'dev-lab', 'https://h/x.git', ('https',))
    assert argv[argv.index('--') + 1] == 'https://h/x.git'
    assert argv[3:7] == ['-c', 'protocol.allow=never', '-c', 'protocol.https.allow=always']


@pytest.mark.parametrize('name', ['../../etc', 'a/b', '..', '-x', 'Dev Lab', 'x/'])
def test_a_lock_package_name_that_is_not_a_pep503_name_is_refused(name: str) -> None:
    """F-59acfb5c7833: the name becomes a cache directory, so it must be a canonical PEP 503 name."""
    text = f'version = 1\n\n[[package]]\nname = "{name}"\nsource = {{ git = "https://h/x.git#ab" }}\n'
    with pytest.raises(ValueError, match='not a package name'):
        drift.sources(text)


@pytest.mark.parametrize('name', ['../../etc', '..', 'a/b'])
def test_lag_refuses_a_traversal_name_before_it_creates_anything(name: str, tmp_path: Path) -> None:
    """F-59acfb5c7833 round 2: ``lag`` builds the path itself, so the name check sits there too."""
    cache = tmp_path / 'cache'
    with pytest.raises(ValueError, match='not a package name'):
        drift.lag(name, 'https://h/x.git', 'ab', cache=cache)
    assert not cache.exists()


def test_planted_control_a_canonical_name_with_dots_and_dashes_is_kept() -> None:
    text = 'version = 1\n\n[[package]]\nname = "zope.interface-x"\nsource = { git = "https://h/x.git#ab" }\n'
    assert drift.sources(text) == {'zope.interface-x': ('https://h/x.git', 'ab')}


def test_a_git_timeout_is_an_oserror_so_the_drift_step_stays_contained(monkeypatch, tmp_path: Path) -> None:
    def hang(*_a: object, **_k: object) -> NoReturn:
        cmd = 'git'
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(drift._door, 'run', hang)
    with pytest.raises(OSError, match='timed out'):
        drift._git(tmp_path, 'status')
