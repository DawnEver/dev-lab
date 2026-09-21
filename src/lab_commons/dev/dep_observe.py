"""LATEST-DEPENDENCIES, the OUT-OF-BAND half -- the ONE module in this family that calls the network.

WHAT THE CONSUMER'S FILE ASSERTS. A shared baseline that nobody refreshes is a declaration that stops
being about the world, and the failure is silent in both directions. MEASURED 2026-09-21 by reading
three consumer checkouts' untracked ``uv.lock`` files: this library resolved at ``0.1.1 @ 5127b6d8``
with its remote **174 commits** ahead of that very revision, and the two other libraries the family
vendors **85** and **688** behind theirs -- every one of them declaring floating git URLs
throughout, so nothing textual ever moved. And the second direction is worse, because it is
invisible: a refresher that answers for four of five packages and
writes what it got produces a file that reads as a complete baseline, and the missing package is
then compared against nothing for as long as the file lives.

WHY THIS IS A SEPARATE MODULE AND NOT A FUNCTION IN :mod:`lab_commons.dev.depversions`. The split is
forced by line count and then justified by the split's own claim, which is the honest order to state
it in: written whole the pair measured past the 300-code-line band, and where the cut falls is
where it had to. It falls on the network. Everything in ``depversions`` answers about files and
imports no transport; everything here talks to a source. That makes "the verdict never calls the
network" a fact about an IMPORT GRAPH rather than a promise in a docstring --
:mod:`lab_commons.dev.famtests.latestversions` and ``depversions`` both have a guard asserting they
import nothing from this module, ``netverb``, ``urllib``, ``http``, ``socket`` or ``subprocess``, with
a planted control that proves the assertion can still fail. A claim that can only be checked by
reading is the declaration that lies.

EVERY VERB GOES THROUGH :mod:`lab_commons.dev.netverb`, WHICH IS WHY NETWORK-RETRY-THEN-REPORT IS
ENFORCED HERE RATHER THAN DECLARED ABSENT. MEASURED 2026-09-21: that rule stood in this repo's
adoption with the reason "nothing here calls a network verb, so a retry wrapper would guard nothing",
and the reason was true of the kit for exactly as long as this module did not exist. It is false the
moment a refresh runs, so both transports below are ``run_network_verb`` calls -- a bounded attempt
count, a wall that kills the process TREE, a diagnosis per attempt, and a remedy sentence a caller
branches on. :mod:`lab_commons.dev.netverb`'s own docstring names the two shell fetchers this
replaces, and both exit on the first failed fetch -- so one DNS blip skips a deploy.

THE TWO TRANSPORTS ANSWER DIFFERENT QUESTIONS AND NEITHER IS DERIVED FROM THE OTHER. An ``'index'``
row is a PEP 440 version from the PyPI JSON API; a ``'remote'`` row is the forty-character revision
``git ls-remote`` reports for the remote's HEAD. HEAD rather than a named branch, because that is
what an unref'd ``git+https://...`` requirement resolves to and therefore what a lock pinned -- a
ref would be a second opinion about which branch a floating requirement tracks.

WHY THE VERSION IS READ FROM A SUBPROCESS RATHER THAN FROM THIS INTERPRETER. The retry has to wrap
the network verb, and ``run_network_verb`` wraps a COMMAND. So ``--pypi PROJECT`` is this module's
own second entry point, run through the wall and the attempt loop like any other verb, and it prints
one line. That also keeps the rule's own subject intact: there is exactly one place in this family
where an HTTP request is spelled, it is inside an argv, and it is retried.

``write_observed`` IS STRICT IN ONE DIRECTION ONLY, ON PURPOSE. It refuses to write an EMPTY file --
a refresh that observed nothing would otherwise commit a baseline that reads as complete over an
empty set -- and it writes what it is given otherwise, because judging completeness is what the
command line and the verdict each do in their own terms. Both callers refuse a short answer before
they write or conclude anything.

WHAT THIS DOES NOT PROVE. It does not make the fetch reliable: a bounded retry around a verb that is
down reports a diagnosis instead of hanging, and the caller's remedies here are "run it again" or
"look at the committed baseline", never "it worked". It does not check that the answer is SENSIBLE --
``info.version`` is whatever PyPI calls the latest release, an unpublished yanked version included,
and ``git ls-remote`` reports a revision with no opinion about whether it is good. Nor does it prove
the answer arrived over a channel that was not intercepted; nothing here verifies a signature and no
claim in this family rests on one.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date
from http.client import HTTPSConnection
from pathlib import Path
from typing import Final
from urllib.parse import quote

import rtoml

from lab_commons.dev import depversions
from lab_commons.dev.depversions import KINDS, Observation, Observed, UnreadableState
from lab_commons.dev.netverb import run_network_verb
from lab_commons.log import emit

__all__ = [
    'TRANSPORT_WALL_S',
    'ObservationRefused',
    'main',
    'observe',
    'refresh',
    'write_observed',
]

#: Seconds one ATTEMPT may take, for both transports. A wall rather than an expectation: the family's
#: measured failure is a network verb with no ceiling parking a deploy timer, and 60s is generous for
#: one HTTPS GET or one ``ls-remote`` on a box that is also running a gate.
TRANSPORT_WALL_S: Final = 60.0

#: The one host this module speaks to, and it is a constant rather than a parameter so that "where
#: does an observation come from" has exactly one answer in this tree.
_PYPI_HOST: Final = 'pypi.org'

#: The one status that carries an answer. Anything else -- a redirect, a 404 for a project that was
#: renamed, a 5xx from a mirror mid-deploy -- is no answer, and no answer is never a version.
_HTTP_OK: Final = 200


class ObservationRefused(RuntimeError):
    """A transport could not answer for a locator, so nothing may be recorded for it.

    Carries the transport's OWN remedy sentence when there is one -- ``run_network_verb`` classifies
    every failure and reports what to do about it -- because "the fetch failed" sends its reader to a
    network log while "EXHAUSTED after 3 attempts, last diagnosis transient" tells them to re-run.
    """


def _pypi_latest(locator: str) -> str | None:
    """The latest version PyPI publishes for ``locator``, or ``None`` when the answer is unreadable.

    A CONNECTION RATHER THAN ``urllib.request`` deliberately: ``urlopen`` carries no verification and
    this module would have to waive a security lint to use it, which is the shape this family treats
    as a waiver nothing uses. The host is pinned and the path is percent-quoted, so the locator cannot
    move the request off ``pypi.org``.
    """
    connection = HTTPSConnection(_PYPI_HOST, timeout=TRANSPORT_WALL_S)
    try:
        connection.request('GET', f'/pypi/{quote(locator, safe="")}/json', headers={'Accept': 'application/json'})
        answer = connection.getresponse()
        if answer.status != _HTTP_OK:
            return None
        payload = json.loads(answer.read().decode('utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    finally:
        connection.close()
    version = (payload.get('info') or {}).get('version') if isinstance(payload, dict) else None
    return version if isinstance(version, str) and version.strip() else None


def _index_verb(locator: str) -> str | None:
    """``'index'``: one ``--pypi`` run of this module, through the shared retry wrapper."""
    argv = (sys.executable, '-m', 'lab_commons.dev.dep_observe', '--pypi', locator)
    report = run_network_verb(argv, timeout=TRANSPORT_WALL_S)
    if not report.ok:
        raise ObservationRefused(report.remedy)
    lines = [line.strip() for line in report.attempts[-1].output.splitlines() if line.strip()]
    return lines[-1] if lines else None


def _remote_verb(locator: str) -> str | None:
    """``'remote'``: the revision of the remote's HEAD, through the shared retry wrapper.

    ``--exit-code`` so that a remote which answers with no matching ref is a FAILED attempt rather
    than an empty answer nobody distinguishes from a remote that is gone.
    """
    argv = ('git', 'ls-remote', '--exit-code', locator, 'HEAD')
    report = run_network_verb(argv, timeout=TRANSPORT_WALL_S)
    if not report.ok:
        raise ObservationRefused(report.remedy)
    fields = report.attempts[-1].output.split()
    return fields[0] if fields else None


#: One transport per :data:`lab_commons.dev.depversions.KINDS` member. A dict rather than an if, so a
#: kind added to the set without a transport REFUSES in :func:`observe` rather than silently reading
#: the wrong source.
_TRANSPORTS: Final[dict[str, Callable[[str], str | None]]] = {'index': _index_verb, 'remote': _remote_verb}


def observe(
    names: Mapping[str, str],
    *,
    kind: str,
    transport: Callable[[str], str | None] | None = None,
    today: date | None = None,
) -> Observation:
    """Ask *kind*'s source about every ``{name: locator}``, and report what answered.

    Never raises on a transport that could not answer: the failure is one half of the returned
    :class:`~lab_commons.dev.depversions.Observation`, because the two callers act on it differently
    and neither of them may read it as a pass.

    Args:
        names: distribution name to the LOCATOR the transport reads -- the PyPI project name for
            ``'index'``, the git URL for ``'remote'``. NO DEFAULT and never derived from the name:
            a distribution's own name and its PyPI project's name are the same string by accident,
            and one that is not is a silent wrong answer.
        kind: a member of :data:`lab_commons.dev.depversions.KINDS`.
        transport: overrides the shipped transport for *kind*. The seam a control drives, so an arm
            about an unanswered fetch never needs a network.
        today: the date the rows are stamped with, or ``None`` for the clock.

    Raises:
        ValueError: *kind* is not a declared member, or *names* is empty -- a refresh that asks about
            nothing returns an empty answer that is indistinguishable from a total failure.

    """
    if kind not in KINDS:
        msg = f'{kind!r} is not one of {sorted(KINDS)}; a source nobody declared cannot be asked about.'
        raise ValueError(msg)
    if not names:
        msg = (
            'a refresh with no names observes nothing, and "nothing observed" is one keystroke from '
            '"everything is up to date". Name the packages to ask about.'
        )
        raise ValueError(msg)
    read = transport or _TRANSPORTS[kind]
    stamp = today or depversions.today()
    answered: dict[str, Observed] = {}
    failed: dict[str, str] = {}
    for name, locator in sorted(names.items()):
        try:
            latest = read(locator)
        except ObservationRefused as refusal:
            failed[name] = str(refusal)
            continue
        if latest is None or not latest.strip():
            failed[name] = (
                f'{kind} transport {locator!r} answered nothing. An empty answer is not a version: '
                f'the package may be unpublished, renamed, or behind a URL that no longer exists.'
            )
            continue
        answered[name] = Observed(name=name, latest=latest.strip(), observed_on=stamp, kind=kind, source=locator)
    return Observation(answered=answered, failed=failed)


def refresh(
    baseline: Mapping[str, Observed],
    *,
    transports: Mapping[str, Callable[[str], str | None]] | None = None,
    today: date | None = None,
) -> Observation:
    """Re-observe every row of *baseline*, each through the transport its OWN kind names.

    THE SEAM THE VERDICT TAKES, and the reason it takes it rather than an import: a caller hands this
    function in, so nothing about the verdict's own tree reaches the network by construction. A
    baseline with rows of both kinds is one call, because a reader asking "is anything up to date"
    wants one answer and two error shapes would be two.

    Args:
        baseline: what the committed observation declares, as
            :func:`lab_commons.dev.depversions.read_observed` returns it.
        transports: per-kind overrides; ``None`` uses the shipped pair.
        today: the date the rows are stamped with, or ``None`` for the clock.

    """
    groups: dict[str, dict[str, str]] = {}
    for name, row in sorted(baseline.items()):
        groups.setdefault(row.kind, {})[name] = row.source
    return _ask(groups, transports=transports, today=today)


def _ask(
    groups: Mapping[str, Mapping[str, str]],
    *,
    transports: Mapping[str, Callable[[str], str | None]] | None,
    today: date | None,
) -> Observation:
    """One :func:`observe` per kind, merged. The one place a group of locators becomes a fetch."""
    answered: dict[str, Observed] = {}
    failed: dict[str, str] = {}
    for kind in sorted(groups):
        got = observe(groups[kind], kind=kind, transport=(transports or {}).get(kind), today=today)
        answered.update(got.answered)
        failed.update(got.failed)
    return Observation(answered=answered, failed=failed)


def write_observed(path: Path, rows: Iterable[Observed]) -> int:
    """Rewrite *path* with *rows*, sorted by name, and return how many were written.

    Args:
        path: where the baseline goes. It is a COMMITTED declaration, so it belongs in the repo it
            describes rather than in a cache directory.
        rows: what to write.

    Raises:
        ObservationRefused: *rows* is empty. The file would then declare no package, and a baseline
            that declares nothing reads exactly like one whose every package is up to date.

    """
    by_name = {row.name: row for row in rows}
    if not by_name:
        msg = (
            'a refresh that observed nothing would write a baseline declaring no package, which reads '
            'as an answer rather than as a hole. Fix the fetch, or delete the file instead of '
            'replacing it with an empty one.'
        )
        raise ObservationRefused(msg)
    document = {
        'observed': {
            name: {
                'latest': by_name[name].latest,
                'observed_on': by_name[name].observed_on.isoformat(),
                'kind': by_name[name].kind,
                'source': by_name[name].source,
            }
            for name in sorted(by_name)
        }
    }
    path.write_text(rtoml.dumps(document), encoding='utf-8')
    return len(by_name)


def _pairs(entries: Sequence[str]) -> dict[str, str]:
    """``NAME=LOCATOR`` command-line entries as a mapping, refusing anything else."""
    out: dict[str, str] = {}
    for entry in entries:
        name, sep, locator = entry.partition('=')
        if not (sep and name.strip() and locator.strip()):
            msg = f'{entry!r} is not NAME=LOCATOR. A named row is how a baseline is seeded by hand.'
            raise ValueError(msg)
        out[name.strip()] = locator.strip()
    return out


def _requested_groups(path: Path, *, index: Sequence[str], remote: Sequence[str]) -> dict[str, dict[str, str]]:
    """What this run is asked to observe: the named rows, else every row the file already declares."""
    groups = {kind: _pairs(entries) for kind, entries in (('index', index), ('remote', remote))}
    named = {kind: names for kind, names in groups.items() if names}
    if named:
        return named
    declared: dict[str, dict[str, str]] = {}
    for name, row in sorted(depversions.read_observed(path).items()):
        declared.setdefault(row.kind, {})[name] = row.source
    return declared


def _rewrite(path: Path, *, index: Sequence[str], remote: Sequence[str]) -> int:
    """THE REFRESH: observe, refuse a short answer, and only then write."""
    try:
        groups = _requested_groups(path, index=index, remote=remote)
        got = _ask(groups, transports=None, today=None) if groups else None
    except (ValueError, ObservationRefused, UnreadableState) as refusal:
        emit(f'dep_observe: {refusal}', err=True)
        return 1
    if got is None:
        emit(
            f'dep_observe: {path} declares no package and no --index/--remote row was named, so this '
            f'refresh has nothing to ask about. Seed it: --index NAME=PROJECT, --remote NAME=URL.',
            err=True,
        )
        return 1
    wanted = sorted({name for names in groups.values() for name in names})
    missing = sorted(set(wanted) - set(got.answered))
    if missing:
        reasons = '; '.join(f'{name}: {got.failed.get(name, "no answer")}' for name in missing)
        emit(
            f'dep_observe: {len(missing)} of {len(wanted)} did not answer, so {path} was NOT written '
            f'-- a short file reads as a complete baseline and would be compared against as one. {reasons}',
            err=True,
        )
        return 1
    written = write_observed(path, got.answered.values())
    emit(f'dep_observe: {path} now declares {written} package(s); commit it with this run.')
    return 0


def _answer_one(project: str) -> int:
    """``--pypi PROJECT``: print the latest version, or report why there is none."""
    try:
        latest = _pypi_latest(project)
    except OSError as broken:
        emit(f'dep_observe: could not reach {_PYPI_HOST} for {project!r}: {broken}', err=True)
        return 1
    if latest is None:
        emit(
            f'dep_observe: {_PYPI_HOST} answers nothing for {project!r}. Check the spelling, and note '
            f'that an observation is keyed by the PyPI PROJECT name, which is not always the name the '
            f'distribution installs under.',
            err=True,
        )
        return 1
    emit(latest)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m lab_commons.dev.dep_observe`` -- the refresher's door, and the transport's.

    Two modes, because they are two callers rather than two features. ``--pypi PROJECT`` answers one
    project and is what :func:`_index_verb` runs through the retry wrapper. ``--refresh PATH``
    re-observes a whole baseline and rewrites it -- the human's or the script's entry point, never a
    test's, and the only mode that writes anything.
    """
    parser = argparse.ArgumentParser(
        prog='python -m lab_commons.dev.dep_observe',
        description='Observe the latest of every dependency a repo tracks, out of band.',
    )
    parser.add_argument('--pypi', metavar='PROJECT', help='print the latest version PyPI publishes, and exit')
    parser.add_argument('--refresh', metavar='PATH', help='re-observe a committed baseline and rewrite it')
    parser.add_argument('--index', action='append', default=[], metavar='NAME=PROJECT', help='seed an index row')
    parser.add_argument('--remote', action='append', default=[], metavar='NAME=URL', help='seed a remote row')
    parsed = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    if not (parsed.pypi or parsed.refresh):
        parser.error('nothing to do: pass --pypi PROJECT, or --refresh PATH with --index/--remote to seed one')
    if parsed.pypi:
        return _answer_one(parsed.pypi)
    return _rewrite(Path(parsed.refresh), index=parsed.index, remote=parsed.remote)


if __name__ == '__main__':
    raise SystemExit(main())
