"""A REQUEST IS A JOB ON THE PART PATH -- compute a person or agent asks for, run by a ``forge serve`` host.

Design: one admission for the distributed compute system, migration step 7 (2026-10-13). A test part and a
request are the SAME noun, a :class:`~lab_commons.compute.model.Job` ``(repo, sha, producer, needs)``: they
differ only in who created it (a push, or a person or agent) and in their status context. A part's is
``tests/<part>``; a request's is ``request/<issue number>`` (:func:`request_context`). Both are ranked,
ADMITTED by the one admission (:func:`lab_commons.compute.admission.admit`: its need-set present, its size
free), claimed, leased, renewed and released by the one path (:mod:`lab_commons.dev.forgetake`,
:mod:`lab_commons.dev.forgeproduce`).

A REQUEST IS AN OPEN ISSUE labelled ``forge:request`` whose body names a producer and a sha::

    producer = "femm_goldens"
    sha = "<40-hex commit>"

The repo is the issue's, the requester its author. The body NEVER carries a command: the producer is a
NAME the repository declares at that sha, ONCE, beside its tests' producer, so a request cannot run
anything its repository did not commit (an undeclared name is refused, never run)::

    [tool.lab_commons.requests.femm_goldens]
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
exactly those files, sized as a selection (:func:`lab_commons.dev.verifybox.selection_mem_gb`). Every
other rule above (trusted sha and author, lock, reachability) applies unchanged. The one other
built-in is :data:`UNIT`: one compute unit, its bundle and size carried in ``paths``
(:func:`lab_commons.dev.forgeunit.unit_request`).

A request is pinned to its sha, so nothing supersedes it. Its producer knows nothing of the forge, so
serve SETTLES it from the exit code (:func:`result`, :func:`settle`): 0 posts ``success`` and labels the
issue ``request:done``, 1 posts ``failure``, every other code is released as a part's would be
(:func:`lab_commons.dev.producer.release_reason`). The issue gets a comment naming the outcome, the host,
where the record is kept there, each file's sha256 and the log's tail -- a failure is on record, never
silent. Nothing closes it: the REQUESTER closes it to sign off on what was made.
"""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
import urllib.parse
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.box.machine import RESOURCE_NAME
from lab_commons.compute.model import REQUEST
from lab_commons.config import section
from lab_commons.dev.forge import _GIT
from lab_commons.dev.forgelabels import add_label
from lab_commons.dev.forgework import ForgeCallFailed
from lab_commons.dev.platformparts import origin_url
from lab_commons.dev.producer import ProducerExit, release_reason
from lab_commons.dev.verifybox import SELECTION_CPU, SELECTION_WALL_S, selection_mem_gb
from lab_commons.hpc.builds import git_dependencies
from lab_commons.hpc.declared import OutdatedKit, kit_tables, pyproject_at
from lab_commons.hpc.needsets import part_name

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence
    from pathlib import Path

    from lab_commons.compute.model import Ranked
    from lab_commons.dev.forgework import Client

__all__ = [
    'CONTEXT_PREFIX',
    'DONE_LABEL',
    'REQUESTS_TABLE',
    'TESTS',
    'UNADMITTED',
    'UNIT',
    'Declared',
    'UndeclaredRequest',
    'declared_request',
    'git_sources',
    'parse_body',
    'parse_paths',
    'remind',
    'request_authors',
    'request_body',
    'request_context',
    'result',
    'settle',
    'unreachable_source',
    'unserved',
    'untrusted',
]

#: The status context prefix of a request job; a part's is ``tests/``.
CONTEXT_PREFIX: Final = 'request/'
#: How many log lines the result comment quotes.
TAIL_LINES: Final = 40

_LINE: Final = re.compile(r'^\s*(?P<key>producer|sha)\s*=\s*["\'](?P<value>[^"\']*)["\']\s*$', re.MULTILINE)
_SHA: Final = re.compile(r'^[0-9a-f]{40}$')
_PATHS: Final = re.compile(r'^\s*paths\s*=\s*(?P<value>\[.*\])\s*$', re.MULTILINE)

#: The reserved producer name of the repository's own test producer over named test files (D5).
TESTS: Final = 'tests'
#: The producer that runs ONE compute unit a box offered because it could not run it (:mod:`lab_commons.dev.forgeunit`).
UNIT: Final = 'unit'

#: Characters a test path never carries: a glob, or a quote/space that would make it more than one path.
_NOT_A_PATH: Final = frozenset('*?[]{}"\' \t')


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


def request_body(producer: str, sha: str, paths: Sequence[str] = ()) -> str:
    """The issue body that IS a request for *producer* at *sha* (and, for :data:`TESTS`, its *paths*)."""
    listed = f'paths = [{", ".join(f"{p!r}".replace(chr(39), chr(34)) for p in paths)}]\n' if paths else ''
    return f'producer = "{producer}"\nsha = "{sha}"\n{listed}'


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


def _test_roots(text: str) -> tuple[str, ...]:
    roots = tomllib.loads(text).get('tool', {}).get('pytest', {}).get('ini_options', {}).get('testpaths')
    return tuple(str(one).strip('/') for one in roots) if isinstance(roots, list) and roots else ()


def _path_refusal(root: Path, sha: str, path: str, roots: Sequence[str]) -> str:
    """Why *path* is not a test file at *sha* under *roots*; ``''`` when it is."""
    pure = PurePosixPath(path)
    if not path or path.startswith('-'):
        return f'{path!r} looks like an option, not a test file'
    if _NOT_A_PATH & set(path):
        return f'{path!r} is a glob or more than one path: name each test file'
    if pure.is_absolute() or '..' in pure.parts or '\\' in path:
        return f'{path!r} leaves the repository'
    if not any(pure.parts[: len(PurePosixPath(r).parts)] == PurePosixPath(r).parts for r in roots):
        return f'{path!r} is outside the declared test roots {list(roots)}'
    if pure.suffix != '.py':
        return f'{path!r} is not a test file (.py)'
    found = _door.run(
        [_GIT, '-C', str(root), 'cat-file', '-e', f'{sha}:{path}'], capture_output=True, check=False, timeout=60
    )
    return '' if found.returncode == 0 else f'{path!r} does not exist at {sha[:12]}'


def _tests_request(root: Path, sha: str, paths: Sequence[str]) -> Declared:
    """The repository's test producer over *paths*, each validated at *sha* (D5)."""
    if not paths:
        msg = f'producer {TESTS!r} runs named test files: the body names `paths = ["tests/test_x.py", ...]`'
        raise UndeclaredRequest(msg)
    try:
        text = pyproject_at(root, sha)
    except (ValueError, OSError) as why:
        msg = f'pyproject.toml unreadable at {sha[:12]}: {why}'
        raise UndeclaredRequest(msg) from why
    produce = kit_tables(text).get('tests', {}).get('produce')
    roots = _test_roots(text)
    if not isinstance(produce, list) or '--part' not in produce or not roots:
        msg = f'{sha[:12]} declares no [tool.lab_commons.tests] produce door with --part, or no pytest testpaths'
        raise UndeclaredRequest(msg)
    refused = [why for path in paths if (why := _path_refusal(root, sha, path, roots))]
    if refused:
        msg = f'producer {TESTS!r} refused: ' + '; '.join(refused)
        raise UndeclaredRequest(msg)
    door = [str(one) for one in produce[: produce.index('--part')]]
    try:
        repo = origin_url(root)
    except OSError:  # no origin: no learned peaks, so the per-task floor prices it
        repo = ''
    mem_gb = selection_mem_gb(repo, paths, SELECTION_CPU)
    return Declared(TESTS, (*door, '--', *paths), frozenset(), float(SELECTION_CPU), mem_gb, SELECTION_WALL_S / 3600)


def _unit_request(_root: Path, _sha: str, paths: Sequence[str]) -> Declared:
    from lab_commons.dev.forgeunit import unit_request  # noqa: PLC0415 -- forgeunit publishes through this module

    return unit_request(paths)


#: The producers every repository has without declaring them: they take ``paths``.
_BUILT_IN: Final = {TESTS: _tests_request, UNIT: _unit_request}


def declared_request(root: Path, sha: str, name: str, paths: Sequence[str] = ()) -> Declared:
    """The producer *name* as commit *sha* declares it under ``[tool.lab_commons.requests.<name>]``.

    :data:`TESTS` is the repository's test producer over *paths* (validated; the module docstring).

    Raises:
        UndeclaredRequest: absent, malformed, or the sha unreadable; the message names the key.
        OutdatedKit: the sha declares a table this kit does not know.

    """
    table = f'[tool.lab_commons.requests.{name}]'
    if sha and name in _BUILT_IN:
        return _BUILT_IN[name](root, sha, paths)
    if paths:
        msg = f'only producers {TESTS!r} and {UNIT!r} take paths; {name!r} runs exactly what its row declares'
        raise UndeclaredRequest(msg)
    if not name or not sha:
        msg = f'a request body names `producer = "<declared name>"` and `sha = "<40-hex>"`; got {name!r} at {sha!r}'
        raise UndeclaredRequest(msg)
    try:
        row = kit_tables(pyproject_at(root, sha)).get('requests', {}).get(name)
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


def unserved(root: Path, sha: str) -> str:
    """Why origin cannot serve *sha* to a host that fetches it, ``''`` when one of its refs contains it.

    A serve host's checkout sits on any branch; it builds a request's tree from what it fetched of origin, so a
    sha only the requester holds (or only a deleted branch held) is one no host can build.
    """
    done = _door.run(
        [_GIT, '-C', str(root), 'for-each-ref', '--count=1', '--contains', sha, 'refs/remotes/origin/'],
        encoding='utf-8',
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode == 0 and done.stdout.strip():
        return ''
    return f'origin serves no ref containing {sha[:12]}: push it where origin keeps it'


#: How long one ``git ls-remote`` of a source may take before it counts as unreachable, in seconds.
REACH_TIMEOUT_S: Final = 60.0


def git_sources(root: Path, sha: str) -> tuple[str, ...]:
    """Every repository a tree at *sha* fetches by git: its pyproject's git dependencies, then its submodules' urls."""
    found = [url for url, _ in git_dependencies(pyproject_at(root, sha))]
    modules = _door.run(
        [_GIT, '-C', str(root), 'config', '--blob', f'{sha}:.gitmodules', '--get-regexp', r'^submodule\..*\.url$'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
    )
    origin = _show(root, '', remote=True)
    for line in modules.stdout.splitlines():
        url = line.split(maxsplit=1)[-1]
        found.append(urllib.parse.urljoin(origin.rstrip('/') + '/', url) if url.startswith('.') else url)
    return tuple(dict.fromkeys(found))


def unreachable_source(root: Path, sha: str) -> str:
    """Why THIS host cannot fetch every git source of *sha* (:func:`git_sources`), ``''`` when it can.

    Each is asked once with ``git ls-remote`` and no prompt: a source behind a credential this host lacks
    fails here, before a claim, rather than mid-bootstrap after one.
    """
    quiet = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never'}
    for url in git_sources(root, sha):
        try:
            done = _door.run(
                [_GIT, 'ls-remote', '-q', url, 'HEAD'],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=REACH_TIMEOUT_S,
                env=quiet,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return f'this host cannot fetch {_public(url)}: no answer in {REACH_TIMEOUT_S:g} s'
        if done.returncode:
            said = (done.stderr or '').strip().splitlines()
            return f'this host cannot fetch {_public(url)}: {said[-1] if said else f"exit {done.returncode}"}'
    return ''


def _public(url: str) -> str:
    """*url* without any userinfo: a credential is never written to a status or a log."""
    parts = urllib.parse.urlsplit(url)
    return parts._replace(netloc=parts.hostname or '').geturl() if parts.username or parts.password else url


def _show(root: Path, spec: str, *, remote: bool = False) -> str:
    argv = ['remote', 'get-url', 'origin'] if remote else ['show', spec]
    done = _door.run([_GIT, '-C', str(root), *argv], capture_output=True, text=True, encoding='utf-8', check=False)
    return done.stdout.strip() if done.returncode == 0 else ''


#: The machine-file table naming whose requests this host runs off the trunks: ``authors = ["<login>", ...]``.
REQUESTS_TABLE: Final = 'requests'


def request_authors() -> frozenset[str]:
    """The logins this host runs a request for at ANY served sha (its machine file's ``[requests] authors``)."""
    table = section(REQUESTS_TABLE)
    authors = table.get('authors', [])
    if set(table) - {'authors'} or not isinstance(authors, list) or not all(isinstance(a, str) for a in authors):
        msg = f'[{REQUESTS_TABLE}] takes only authors = ["<forge login>", ...]'
        raise ValueError(msg)
    return frozenset(authors)


def untrusted(root: Path, sha: str, author: str, *, trunks: Sequence[str], authors: Collection[str]) -> str:
    """Why this host does not run *author*'s request at *sha*, ``''`` when it does.

    A request runs its sha's code on another person's box: only code reviewed onto one of *trunks* (origin's
    integration branch or trunk) runs for anyone; code anywhere else runs only for an author this host's
    machine file allows (:func:`request_authors`).
    """
    if author and author in authors:
        return ''
    for ref in trunks:
        done = _door.run(
            [_GIT, '-C', str(root), 'merge-base', '--is-ancestor', sha, f'refs/remotes/origin/{ref}'],
            capture_output=True,
            check=False,
        )
        if done.returncode == 0:
            return ''
    who = author or 'its unresolved author'
    on = ' nor '.join(trunks)
    return f"{sha[:12]} is on neither {on}, and {who} is not in this host's [{REQUESTS_TABLE}] authors"


#: The mark of the one comment a request waiting past ``request_unadmitted_hours`` gets.
UNADMITTED: Final = '**unadmitted**'


def remind(client: Client, queue: Sequence[Ranked], *, hours: float, host: str) -> list[str]:
    """Comment ONCE on each request of *queue* blocked past *hours*, naming why *host* did not admit it.

    The requester otherwise learns nothing but by polling ``forge queue``. The issue's comments are read
    first: one carrying :data:`UNADMITTED` means it was told. A forge call that fails is said, never raised.
    """
    said = []
    for item in queue:
        one = item.candidate
        if one.kind != REQUEST or not item.blocked or item.wait_h < hours:
            continue
        path = f'{client.repo}/issues/{one.number}/comments'
        try:
            if any(UNADMITTED in str(raw.get('body') or '') for raw in client.call('GET', path) or ()):
                continue
            client.issue_comment(
                one.number,
                f'{UNADMITTED} for {item.wait_h:.0f} h: no host has claimed this request. {host}: {item.blocked}',
            )
        except ForgeCallFailed as failed:
            said.append(f'could not tell issue/{one.number} it waits: {failed}')
        else:
            said.append(f'told issue/{one.number} it waited {item.wait_h:.0f} h unadmitted')
    return said


def result(code: int, host: str) -> tuple[str, str]:
    """The ``(state, description)`` a request's producer exiting *code* on *host* settles it with."""
    if code == ProducerExit.PASS:
        return 'success', f'request done: exit 0 on {host}'
    if code == ProducerExit.FAIL:
        return 'failure', f'request failed: exit 1 on {host}'
    return 'error', release_reason(code)


#: The label a request whose producer exited 0 gets: done, awaiting its requester's sign-off.
DONE_LABEL: Final = 'request:done'


def settle(
    client: Client,
    number: int,
    state: str,
    description: str,
    *,
    log: str,
    host: str,
    record: tuple[str, Sequence[tuple[str, str]]],
) -> None:
    """Comment the outcome, where its record is kept, each file's sha256 and the log's tail on issue *number*.

    A success is labelled :data:`DONE_LABEL` and LEFT OPEN: exit 0 says the producer finished, not that the
    requester accepts what it made -- the requester signs off by closing it.
    """
    tail = '\n'.join(log.rstrip().splitlines()[-TAIL_LINES:])
    kept, files = record
    sums = ''.join(f'- `{digest}`  {name}\n' for name, digest in files) or '- (no file)\n'
    where = f'record: `{kept}` on {host}' if kept else f'record: none declared on {host}'
    body = f'**{state}** -- {description}\n\n{where}\n\nsha256:\n\n{sums}\nlog tail:\n\n```\n{tail}\n```'
    client.issue_comment(number, body)
    if state == 'success':
        add_label(client, number, DONE_LABEL)
