"""FAMILY DRIFT: a lock left behind its dependencies, or a host running what its lock does not pin, ALARMS.

THE INCIDENT (2026-11-03). lab-commons and numerics-lab pinned a dev-lab 224 commits old. Their rendered review
job could not import the review method, concluded success and posted nothing, so no PR there was reviewed for
days -- and nothing said so. The relock (:mod:`dev_lab.dev.relock`) is the CAUSE fix and now carries the rendered
workflows with the lock; this module is the WATCH that says when the relock did not happen.

ONE READING PER TICK, NO NEW POLLER. The serve tick's repo-wide pass (:func:`dev_lab.dev.forgeservesteps.drift`)
runs :func:`step`; the CLI (``python -m dev_lab.dev.drift``) runs the same census for a repo no host serves. It reads

* every git pin of ``origin/<integration>:uv.lock`` (:func:`sources`) against that dependency's default branch:
  how many commits it is behind, and since when (:func:`lag` -- the commit time of the first commit after the
  pin, read from a commits-only fetch, ``--filter=tree:0``, cached under the repo's git directory);
* this host's installed git distributions against its checkout's lock (:func:`host_mismatches`, the reading
  :mod:`dev_lab.dev.lockpins` already makes for a run).

A pin is a FINDING when it has been behind longer than the declared bound (:func:`bound_of`,
``[tool.dev_lab.drift] max_behind``, default :data:`DEFAULT_BOUND`): inside it the relock has time to land. A
host mismatch is always a finding. Each finding is ONE alarm of kind :data:`dev_lab.dev.forgealarm.DRIFT`,
``about`` the dependency, so it repeats on its own and no oftener than the alarm path's repeat window.

The rendered files are not read separately: each repo's suite already refuses a render that differs from its
PINNED dev-lab (``ciworkflows check``), so a stale render is a stale pin, and the pin is what this reads.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.family import declared_table
from dev_lab.dev.forge import _GIT, _GIT_TIMEOUT_S
from dev_lab.dev.forgealarm import DRIFT, Alarm, sound
from dev_lab.dev.forgenotice import duration
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.lockpins import Installed, installed_git, locked_git, sync_door
from dev_lab.dev.netverb import run_network_verb

__all__ = [
    'DEFAULT_BOUND',
    'Finding',
    'Lag',
    'Mismatch',
    'alarm_of',
    'bound_of',
    'findings',
    'host_mismatches',
    'lag',
    'sources',
    'step',
]

#: How long a pin may sit behind its dependency before it alarms: the relock lands well inside it.
DEFAULT_BOUND: Final = timedelta(days=2)
_TABLE: Final = 'drift'
_KEYS: Final = frozenset({'max_behind'})
_SHORT: Final = 12
_RELOCK_REMEDY: Final = (
    'Merge the open `pr/relock-*` pull request; if none is open, relock on a lane: '
    '`python -m dev_lab.dev.dep --lock-upgrade .` then `python -m dev_lab.dev.ciworkflows render`.'
)


@dataclass(frozen=True)
class Lag:
    """One git pin read against its dependency's default branch."""

    dist: str
    url: str
    pinned: str
    head: str
    behind: int
    since: datetime | None  # when the first commit after the pin was made; None when not behind


@dataclass(frozen=True)
class Finding:
    """One drift past its bound: what it is about, a one-line subject, the detail lines and the remedy."""

    about: str
    subject: str
    body: str
    action: str


def _canonical(name: str) -> str:
    return name.lower().replace('_', '-')


#: A canonical PEP 503 name: the only shape a lock's package name may take before it names a cache directory.
_PEP503: Final = re.compile(r'^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$')

#: The URL schemes a lock pin may be fetched over. A lock is repository content, so its URL is untrusted input.
SCHEMES: Final = ('https',)


def sources(lock: str) -> dict[str, tuple[str, str]]:
    """Package name -> ``(repository url, pinned commit)`` for every package *lock* sources from git.

    Raises ValueError for a name that is not a canonical PEP 503 name: it becomes a cache directory.
    """
    pins: dict[str, tuple[str, str]] = {}
    for package in tomllib.loads(lock).get('package', []):
        git = package.get('source', {}).get('git')
        if isinstance(git, str) and '#' in git:
            name = _canonical(package['name'])
            if not _PEP503.match(name):
                msg = f'uv.lock package {name!r} is not a package name (PEP 503); drift refused'
                raise ValueError(msg)
            url, _, sha = git.rpartition('#')
            pins[name] = (url.partition('?')[0], sha)
    return pins


def admit(url: str, sha: str, schemes: tuple[str, ...]) -> None:
    """Refuse a lock pin that is not a URL over *schemes*, or whose URL or commit could be read as an option."""
    scheme = url.partition('://')[0] if '://' in url else ''
    if scheme not in schemes or url.startswith('-') or sha.startswith('-'):
        msg = f'lock pin {url}#{sha} refused: only {", ".join(schemes)} URLs are fetched'
        raise ValueError(msg)


def fetch_argv(repo: Path, dist: str, url: str, schemes: tuple[str, ...]) -> list[str]:
    """The commits-only fetch of *url*: only *schemes* allowed, the URL after ``--`` so it is never an option."""
    allow = [arg for scheme in schemes for arg in ('-c', f'protocol.{scheme}.allow=always')]
    return [
        _GIT, '-C', str(repo), '-c', 'protocol.allow=never', *allow,
        'fetch', '-q', '--filter=tree:0', '--no-tags', '--', url, f'+HEAD:refs/drift/{dist}',
    ]  # fmt: skip


def _git(cwd: Path, *argv: str) -> str:
    try:
        done = _door.run(
            [_GIT, '-C', str(cwd), *argv], capture_output=True, text=True, encoding='utf-8', errors='replace',
            check=False, timeout=_GIT_TIMEOUT_S,
        )  # fmt: skip
    except subprocess.TimeoutExpired as why:
        msg = f'git {" ".join(argv[:2])} timed out after {why.timeout} s in {cwd}'
        raise OSError(msg) from why
    if done.returncode != 0:
        msg = f'git {" ".join(argv[:2])} failed in {cwd}: {(done.stdout + done.stderr).strip()}'
        raise OSError(msg)
    return done.stdout.strip()


def lag(dist: str, url: str, pinned: str, *, cache: Path, schemes: tuple[str, ...] = SCHEMES) -> Lag:
    """*pinned* read against the default branch of *url*: commits behind and since when.

    The dependency is fetched commits-only (``--filter=tree:0``) into ``cache/<dist>.git``, kept across ticks.
    A pin that :func:`admit` refuses raises ValueError before anything is created or fetched.
    """
    admit(url, pinned, schemes)
    repo = cache / f'{dist}.git'
    if not repo.is_dir():
        repo.mkdir(parents=True)
        _git(repo, 'init', '-q', '--bare')
    report = run_network_verb(fetch_argv(repo, dist, url, schemes), cwd=repo, timeout=300)
    if not report.ok:
        msg = f'the fetch of {url} failed: {report.remedy}'
        raise OSError(msg)
    head = _git(repo, 'rev-parse', f'refs/drift/{dist}')
    after = _git(repo, 'rev-list', '--reverse', '--format=%ct', '--no-commit-header', f'{pinned}..{head}').split()
    since = datetime.fromtimestamp(int(after[0]), UTC) if after else None
    return Lag(dist, url, pinned, head, len(after), since)


@dataclass(frozen=True)
class Mismatch:
    """One distribution this host runs at another commit than its lock pins."""

    name: str
    running: str
    pinned: str


def host_mismatches(installed: Iterable[Installed], pins: Mapping[str, str]) -> tuple[Mismatch, ...]:
    """Each installed git distribution whose commit is not the one the lock pins."""
    return tuple(
        Mismatch(one.name, one.commit, pins[one.name])
        for one in installed
        if one.name in pins and pins[one.name] != one.commit
    )


def findings(
    lags: Iterable[Lag], hosts: Sequence[Mismatch], *, now: datetime, bound: timedelta, door: str = ''
) -> tuple[Finding, ...]:
    """The lags behind past *bound* and every host mismatch, each as one :class:`Finding`."""
    found: list[Finding] = []
    for one in lags:
        if one.since is None or now - one.since <= bound:
            continue
        days = (now - one.since).total_seconds() / 86400
        found.append(
            Finding(
                one.dist,
                f'{one.dist} pin is {one.behind} commits behind for {days:.1f} days',
                f'Dependency: {one.dist} ({one.url})\nPinned: {one.pinned[:_SHORT]}\nHead: {one.head[:_SHORT]}\n'
                f'Behind: {one.behind} commits behind, since {one.since:%Y-%m-%d %H:%M} UTC '
                f'(bound {bound.total_seconds() / 86400:g} days)',
                _RELOCK_REMEDY,
            )
        )
    found.extend(
        Finding(
            f'host:{host.name}',
            f'this host runs {host.name} {host.running[:_SHORT]}, its lock pins {host.pinned[:_SHORT]}',
            f'Installed: {host.name} {host.running}\nLocked: {host.name} {host.pinned}',
            f'Sync this host to its lock: `{door or "python -m dev_lab.dev.dep --bootstrap"}`.',
        )
        for host in hosts
    )
    return tuple(found)


def alarm_of(repo: str, finding: Finding) -> Alarm:
    """*finding* as one :data:`~dev_lab.dev.forgealarm.DRIFT` alarm on *repo*, its remedy as the notice's action."""
    alarm = Alarm(DRIFT, repo, f'Version drift: {finding.subject}', finding.body, about=finding.about)
    return replace(alarm, notice=replace(alarm.as_notice(), action=finding.action))


def bound_of(data: Mapping[str, Any]) -> timedelta:
    """``[tool.dev_lab.drift] max_behind`` of parsed pyproject *data*, else :data:`DEFAULT_BOUND`."""
    table = declared_table(data, _TABLE, {})
    if unknown := sorted(set(table) - _KEYS):
        msg = f'[tool.dev_lab.{_TABLE}] has unknown key(s) {unknown}; the keys are {sorted(_KEYS)}'
        raise ValueError(msg)
    text = table.get('max_behind')
    return DEFAULT_BOUND if text is None else duration('max_behind', str(text))


def _census(
    root: Path, *, now: datetime, installed: Sequence[Installed] | None
) -> tuple[tuple[Finding, ...], list[str]]:
    integration = load_policy(root).integration
    lock = _git(root, 'show', f'origin/{integration}:uv.lock')
    data = tomllib.loads(_git(root, 'show', f'origin/{integration}:pyproject.toml'))
    cache = Path(_git(root, 'rev-parse', '--path-format=absolute', '--git-common-dir')) / 'drift'
    failed: list[str] = []
    lags: list[Lag] = []
    for dist, (url, pinned) in sources(lock).items():
        try:
            lags.append(lag(dist, url, pinned, cache=cache))
        except OSError as why:
            failed.append(f'{dist}: {why}')
    here = installed_git() if installed is None else installed
    hosts = host_mismatches(here, locked_git(root / 'uv.lock'))
    return findings(lags, hosts, now=now, bound=bound_of(data), door=sync_door(root)), failed


def step(
    root: Path,
    repo: str,
    *,
    say: Callable[[str], None],
    alarm: Callable[[Alarm], object],
    now: datetime | None = None,
    installed: Sequence[Installed] | None = None,
) -> None:
    """The serve tick's census of *root*: one alarm per finding; a dependency that could not be read is said."""
    found, failed = _census(root, now=now or datetime.now(UTC), installed=installed)
    for line in failed:
        say(f'[serve] drift: could not read {line}')
    for finding in found:
        alarm(alarm_of(repo, finding))
    say(f'[serve] drift: {len(found)} finding(s)' if found else '[serve] drift: every pin within its bound')


def main(argv: Sequence[str] | None = None) -> int:
    """``[--root R] [--alarm]``: print the census of R; ``--alarm`` sounds each finding; exit 1 on any."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.drift', description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--alarm', action='store_true')
    args = parser.parse_args(argv)
    found, failed = _census(args.root, now=datetime.now(UTC), installed=None)
    for line in failed:
        emit(f'[drift] could not read {line}', err=True)
    repo = _git(args.root, 'remote', 'get-url', 'origin')
    for finding in found:
        emit(f'[drift] {finding.subject} -- {finding.action}')
        if args.alarm:
            sound(alarm_of(repo, finding))
    return 1 if found or failed else 0


if __name__ == '__main__':
    sys.exit(main())
