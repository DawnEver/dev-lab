"""A REQUEST IS A JOB ON THE PART PATH -- compute a person or agent asks for, run by a ``forge serve`` host.

Design: one admission for the distributed compute system, migration step 7 (2026-10-13). A test part and a
request are the SAME noun, a :class:`~lab_commons.compute.model.Job` ``(repo, sha, producer, needs)``: they
differ only in who created it (a push, or a person or agent) and in their status context. A part's is
``tests/<part>``; a request's is ``request/<issue number>`` (:func:`request_context`). Both are ranked,
ADMITTED by the one admission (:func:`lab_commons.compute.admission.admit`: its need-set present, its size
free), claimed, leased, renewed and released by the one path (:mod:`dev_lab.dev.forgetake`,
:mod:`dev_lab.dev.forgeproduce`).

A REQUEST IS AN OPEN ISSUE labelled ``forge:request`` whose body names a producer and a sha::

    producer = "femm_goldens"
    sha = "<40-hex commit>"

The repo is the issue's, the requester its author. The body NEVER carries a command: the producer is a
NAME the repository declares at that sha, ONCE, beside its tests' producer, so a request cannot run
anything its repository did not commit (an undeclared name is refused, never run)::

    [tool.dev_lab.requests.femm_goldens]
    argv = ["-m", "solver", "golden", "regenerate", "--reference", "femm"]   # after the tree's python
    needs = ["femm", "windows"]   # its NEED-SET: resource names, an OS among them, like a part's
    cpu = 2                       # its SIZE: what the box admits it at until a run of it is measured
    mem_gb = 6.0                  # (learned per producer NAME); an unsized row is refused, never the whole host
    wall_h = 48                   # past it the box kills the run: a long solve declares its own

THE ONE PRODUCER THAT TAKES ARGUMENTS IS THE REPOSITORY'S OWN TEST PRODUCER (D5, ruling 2026-10-17), named
:data:`TESTS`: a box that cannot admit a selection offers it to a host that can. Its body adds
``paths = ["tests/test_a.py", ...]`` and NOTHING else: each must be a test file (``.py``) that exists at the
sha under the repository's declared test roots (``[tool.pytest.ini_options] testpaths``) -- no glob, no
option, nothing argv-looking -- and it runs as the declared ``[tool.lab_commons.tests] produce`` door over
exactly those files, sized as a selection (:func:`dev_lab.dev.verifybox.selection_mem_gb`), and PLACED by the
resource markers its files carry
(:func:`~dev_lab.dev.forgerequestpaths.placement`, user ruling 2026-10-21): on Linux for anything Linux can
run, on Windows only for a selection holding a ``jmag`` test; any other resource is refused by name. Every
other rule above (trusted sha and author, lock, reachability) applies unchanged. The one other
built-in is :data:`UNIT`: one compute unit, its bundle and size carried in ``paths``
(:func:`dev_lab.dev.forgeunit.unit_request`).

A request is pinned to its sha, so nothing supersedes it. Its producer knows nothing of the forge, so
serve SETTLES it from the exit code (:mod:`dev_lab.dev.forgerequesthost`): 0 posts ``success`` and labels the
issue ``request:done``, 1 posts ``failure``, every other code is released as a part's would be
(:func:`dev_lab.dev.producer.release_reason`). The issue gets a comment naming the outcome, the host,
where the record is kept there, each file's sha256 and the log's tail -- a failure is on record, never
silent. Nothing closes it: the REQUESTER closes it to sign off on what was made.

A DEADLINE (``deadline = "<ISO 8601>"``, :func:`parse_deadline`) bounds how long a request may wait to be
claimed: past it, an unclaimed request is refused on its own context as ``no room`` -- an answer, never a wait
(``forge try``, :mod:`dev_lab.dev.forgetry`).
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Final

from lab_commons.box.machine import RESOURCE_NAME
from lab_commons.hpc.declared import OutdatedKit, kit_tables, pyproject_at
from lab_commons.hpc.needsets import part_name, read_vocabulary

from dev_lab.dev._forgesource import (
    LOCK_FILE,
    git_sources,
    unreachable_source,
    unreproducible,
    unserved,
)
from dev_lab.dev.family import declared_in
from dev_lab.dev.forgerequestpaths import NOT_A_PATH, blobs, path_refusal, placement, test_roots
from dev_lab.dev.platformparts import origin_url
from dev_lab.dev.treedirt import status_paths
from dev_lab.dev.venvpath import running_interpreter
from dev_lab.dev.verifybox import SELECTION_CPU, SELECTION_WALL_S, selection_files, selection_mem_gb

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

__all__ = [
    'CONTEXT_PREFIX',
    'LOCK_FILE',
    'TESTS',
    'UNIT',
    'Declared',
    'UndeclaredRequest',
    'declared_request',
    'git_sources',
    'offer_line',
    'parse_body',
    'parse_deadline',
    'parse_paths',
    'request_body',
    'request_context',
    'unreachable_source',
    'unreproducible',
    'unserved',
]

#: The status context prefix of a request job; a part's is ``tests/``.
CONTEXT_PREFIX: Final = 'request/'

_LINE: Final = re.compile(r'^\s*(?P<key>producer|sha)\s*=\s*["\'](?P<value>[^"\']*)["\']\s*$', re.MULTILINE)
_SHA: Final = re.compile(r'^[0-9a-f]{40}$')
_PATHS: Final = re.compile(r'^\s*paths\s*=\s*(?P<value>\[.*\])\s*$', re.MULTILINE)
_DEADLINE: Final = re.compile(r'^\s*deadline\s*=\s*["\'](?P<value>[^"\'\n]*)["\']\s*$', re.MULTILINE)

#: The reserved producer name of the repository's own test producer over named test files (D5).
TESTS: Final = 'tests'
#: The producer that runs ONE compute unit a box offered because it could not run it (:mod:`dev_lab.dev.forgeunit`).
UNIT: Final = 'unit'


class UndeclaredRequest(ValueError):
    """A request names a producer its sha does not declare (or declares malformed); the message names the key."""


@dataclass(frozen=True)
class Declared:
    """One declared request producer, as its sha declares it."""

    name: str
    argv: tuple[str, ...]
    needs: frozenset[str]
    cpu: float
    mem_gb: float
    wall_h: float

    @property
    def part(self) -> str:
        """Its need-set spelled as a part is (``femm+windows``): how the queue names it."""
        return part_name(self.needs)


def request_context(number: int) -> str:
    """``request/<number>`` -- the one status context a request (and a claim on it) uses."""
    return f'{CONTEXT_PREFIX}{number}'


def request_body(producer: str, sha: str, paths: Sequence[str] = (), *, deadline: datetime | None = None) -> str:
    """The issue body that IS a request for *producer* at *sha* (for :data:`TESTS`, its *paths*), until *deadline*."""
    listed = f'paths = [{", ".join(f"{p!r}".replace(chr(39), chr(34)) for p in paths)}]\n' if paths else ''
    until = f'deadline = "{deadline.isoformat(timespec="seconds")}"\n' if deadline is not None else ''
    return f'producer = "{producer}"\nsha = "{sha}"\n{listed}{until}'


def parse_deadline(body: str) -> datetime | None:
    """The ``deadline`` a request body names; ``None`` when it names none or none readable as an aware time."""
    found = _DEADLINE.search(body or '')
    if found is None:
        return None
    try:
        when = datetime.fromisoformat(found['value'])
    except ValueError:
        return None
    return when if when.tzinfo is not None else None


def parse_body(body: str) -> tuple[str, str]:
    """``(producer, sha)`` a request body names; ``''`` for one it does not name well."""
    found = {match['key']: match['value'] for match in _LINE.finditer(body or '')}
    producer, sha = found.get('producer', ''), found.get('sha', '').lower()
    return (producer if RESOURCE_NAME.match(producer) else '', sha if _SHA.match(sha) else '')


def parse_paths(body: str) -> tuple[str, ...]:
    """The ``paths = [...]`` a request body names, as given; ``()`` when it names none or not as strings."""
    found = _PATHS.search(body or '')
    if found is None:
        return ()
    try:
        value = tomllib.loads(f'paths = {found["value"]}')['paths']
    except tomllib.TOMLDecodeError:
        return ('<an unreadable paths list>',)
    return tuple(str(one) for one in value) if isinstance(value, list) else ()


def _tests_request(root: Path, sha: str, paths: Sequence[str]) -> Declared:
    """The repository's test producer over *paths*, each validated at *sha* (D5)."""
    if not paths:
        msg = f'producer {TESTS!r} runs named test files: the body names `paths = ["tests/test_x.py", ...]`'
        raise UndeclaredRequest(msg)
    try:
        text = pyproject_at(root, sha)
        produce = kit_tables(text).get('tests', {}).get('produce')
    except OutdatedKit:  # the READER is older than the sha: this host's defect, never the commit's
        raise
    except (ValueError, OSError) as why:  # unreadable, or a retired table at a sha older than its move
        msg = f'pyproject.toml unreadable at {sha[:12]}: {why}'
        raise UndeclaredRequest(msg) from why
    roots = test_roots(text)
    if not isinstance(produce, list) or '--part' not in produce or not roots:
        msg = f'{sha[:12]} declares no [tool.lab_commons.tests] produce door with --part, or no pytest testpaths'
        raise UndeclaredRequest(msg)
    files = blobs(root, sha, [path for path in paths if not NOT_A_PATH & set(path)])
    if refused := [why for path in paths if (why := path_refusal(path, roots, files, sha))]:
        msg = f'producer {TESTS!r} refused: ' + '; '.join(refused)
        raise UndeclaredRequest(msg)
    door = [str(one) for one in produce[: produce.index('--part')]]
    try:
        repo = origin_url(root)
    except OSError:  # no origin: no learned peaks, so the per-task floor prices it
        repo = ''
    try:
        resources = read_vocabulary(text).resources
    except ValueError as why:
        msg = f'[tool.lab_commons.tests] resources refused at {sha[:12]}: {why}'
        raise UndeclaredRequest(msg) from why
    try:
        needs = placement(files, sha, resources)
    except ValueError as why:
        raise UndeclaredRequest(str(why)) from why
    mem_gb = selection_mem_gb(repo, paths, SELECTION_CPU)
    return Declared(TESTS, (*door, '--', *paths), needs, float(SELECTION_CPU), mem_gb, SELECTION_WALL_S / 3600)


def _unit_request(_root: Path, _sha: str, paths: Sequence[str]) -> Declared:
    from dev_lab.dev.forgeunit import unit_request  # noqa: PLC0415 -- forgeunit publishes through this module

    return unit_request(paths)


#: The producers every repository has without declaring them: they take ``paths``.
_BUILT_IN: Final = {TESTS: _tests_request, UNIT: _unit_request}


def declared_request(root: Path, sha: str, name: str, paths: Sequence[str] = ()) -> Declared:
    """The producer *name* as commit *sha* declares it under ``[tool.dev_lab.requests.<name>]``.

    :data:`TESTS` is the repository's test producer over *paths* (validated; the module docstring).

    Raises:
        UndeclaredRequest: absent, malformed, or the sha unreadable; the message names the key.
        OutdatedKit: the sha declares a table this kit does not know.

    """
    table = f'[tool.dev_lab.requests.{name}]'
    if sha and name in _BUILT_IN:
        return _BUILT_IN[name](root, sha, paths)
    if paths:
        msg = f'only producers {TESTS!r} and {UNIT!r} take paths; {name!r} runs exactly what its row declares'
        raise UndeclaredRequest(msg)
    if not name or not sha:
        msg = f'a request body names `producer = "<declared name>"` and `sha = "<40-hex>"`; got {name!r} at {sha!r}'
        raise UndeclaredRequest(msg)
    try:
        row = declared_in(pyproject_at(root, sha), 'requests').get(name)
    except OutdatedKit:  # the READER is older than the sha: this host's defect, never the commit's
        raise
    except (ValueError, OSError) as why:  # an unknown sha, an unreadable or retired declaration
        msg = f'{table} unreadable at {sha[:12]}: {why}'
        raise UndeclaredRequest(msg) from why
    if not isinstance(row, dict):
        msg = f'{sha[:12]} declares no {table}: a request runs only a producer its repository commits'
        raise UndeclaredRequest(msg)
    argv, needs = row.get('argv'), row.get('needs', [])
    if not isinstance(argv, list) or not argv or not all(isinstance(one, str) and one for one in argv):
        msg = f'{table} argv must be a non-empty array of strings (what follows the tree python)'
        raise UndeclaredRequest(msg)
    if not isinstance(needs, list) or not all(isinstance(one, str) and RESOURCE_NAME.match(one) for one in needs):
        msg = f'{table} needs must be an array of resource names'
        raise UndeclaredRequest(msg)
    unsized = [key for key in ('cpu', 'mem_gb', 'wall_h') if not _positive(row.get(key))]
    if unsized:
        msg = f'{table} is unsized: declare {" and ".join(unsized)} positive (never the whole host)'
        raise UndeclaredRequest(msg)
    return Declared(name, tuple(argv), frozenset(needs), float(row['cpu']), float(row['mem_gb']), float(row['wall_h']))


def _positive(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def offer_line(root: Path, head: str, arguments: tuple[str, ...]) -> str:
    """The OFFER of this selection to a host that can admit it (D5), or why it cannot be offered.

    Only committed test files at a pushed sha can run elsewhere: a dirty tree is this box's alone.
    """
    files = selection_files(root, arguments)
    if not files or status_paths(root):
        return 'It cannot be offered elsewhere: commit and push the files it selects first.'
    return (
        'Or offer it to a host that admits it: '
        f'{running_interpreter()} -m dev_lab.dev.forge request {TESTS} --sha {head} --paths {" ".join(files)}'
    )
