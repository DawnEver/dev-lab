"""SECURITY -- the three deterministic scans a head must pass before a merge, and the family default.

The scans are pure readings of a tree; :mod:`dev_lab.dev.forgesecurity` runs them once per head as a forge serve
step and posts ``tests/security``. The FAMILY DEFAULT is declared once here; a repo declares only its differences
(``[tool.dev_lab.security]``, read by that step), every one with its reason:

* :func:`code_findings` -- ruff's ``S`` (bandit) rules over the tracked Python, run ``--isolated`` so a repo's
  own ``ignore`` or ``per-file-ignores`` cannot switch a rule off. The rules off for the whole family are
  :data:`FAMILY_IGNORE`, each with its reason; the trees never scanned are :data:`FAMILY_EXCLUDE`. A
  ``# noqa: Sxxx`` stays honoured: it is a per-site, reviewed declaration.
* :func:`secret_findings` -- every tracked text file against :data:`SECRET_PATTERNS`, plus any tracked
  ``.env`` file. A hit is reported as ``path:line: kind: sha256:<12 hex>`` and NEVER by value, so the
  record of the check cannot leak what it found.
* :func:`advisories` / :func:`vulnerable` -- every registry package pinned in ``uv.lock`` against the OSV
  database (``api.osv.dev``). An unreachable or unreadable database raises :class:`AdvisoriesUnreachable`,
  which the step posts as ``error`` -- never a pass on an unanswered question.

A failure of the scanner itself (ruff erroring, git absent) raises :class:`ScanFailed` rather than
returning an empty list: "nothing found" and "nothing read" must never read alike.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tomllib
from http.client import HTTPException, HTTPSConnection
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping

__all__ = [
    'FAMILY_EXCLUDE',
    'FAMILY_IGNORE',
    'SECRET_PATTERNS',
    'AdvisoriesUnreachable',
    'ScanFailed',
    'advisories',
    'code_findings',
    'locked_packages',
    'scan_secrets',
    'secret_findings',
    'vulnerable',
]

#: The ``S`` rules off for the WHOLE family, each with why. Measured 2026-10-26 over the seven repos'
#: integrate/main, outside test trees: S603 217 findings, S101 about 230 (196 of them in one downstream ``src/``).
FAMILY_IGNORE: Final[dict[str, str]] = {
    'S101': (
        'assert is flagged because `python -O` strips it; no family entry point runs under -O, the sites are '
        'invariants and type narrowing, and an assert guarding access is a review finding a per-line rule '
        'firing on every invariant cannot single out'
    ),
    'S603': (
        'subprocess-without-shell-equals-true fires on EVERY subprocess call whose argv is not a literal; in '
        'repos whose job is driving git, uv, cargo and vendor solvers that is every call, so it says nothing '
        'per site. shell=True (S602/S604) and a partial executable path (S607) stay enforced.'
    ),
}

#: Never scanned for ``S``, each with why; ruff matches a bare name against EVERY path component (a ``**/``
#: glob would let ``*`` cross a separator). A repo adds its own through ``exclude=``.
FAMILY_EXCLUDE: Final[dict[str, str]] = {
    'tests': 'a test tree, at any depth: tests assert by `assert` and plant the hazards their controls must find',
    'test_*.py': 'a test module beside the code it tests, the same',
    'conftest.py': 'pytest fixtures, the same',
    '.claude': 'memory and its attachments: recorded evidence, never imported or shipped',
}

#: ``(kind, pattern)`` for a credential that may not be tracked. Each is the vendor's documented token
#: SHAPE, so a hit is a credential or a deliberate fake -- never prose.
SECRET_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ('private key', re.compile(r'-----BEGIN (?:[A-Z]+ )*PRIVATE KEY(?: BLOCK)?-----')),
    ('aws access key', re.compile(r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b')),
    ('github token', re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b')),
    ('gitlab token', re.compile(r'\bglpat-[A-Za-z0-9_-]{20,}\b')),
    ('slack token', re.compile(r'\bxox[abposr]-[A-Za-z0-9-]{10,}\b')),
    ('anthropic key', re.compile(r'\bsk-ant-[A-Za-z0-9_-]{20,}')),
    ('openai key', re.compile(r'\bsk-(?:proj-)?[A-Za-z0-9]{32,}\b')),
    ('google api key', re.compile(r'\bAIza[0-9A-Za-z_-]{35}\b')),
    ('telegram bot token', re.compile(r'\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b')),
    ('pypi token', re.compile(r'\bpypi-AgE[A-Za-z0-9_-]{50,}')),
    (
        'credential in a url',
        re.compile(r'\b[a-z][a-z0-9+.-]*://[^\s/:@<>{}$\'"`]+:(?![<${])[^\s/@<>\'"`]{6,}@[A-Za-z0-9.-]+'),
    ),
)

#: A tracked file by this name is environment content, whatever it holds; ``.env.example`` is documentation.
_ENV_FILE: Final = re.compile(r'(?:^|/)\.env(?:\.(?!example$|sample$|template$)[^/]+)?$')

_OSV_HOST: Final = 'api.osv.dev'
_OSV_BATCH: Final = 1000
_OSV_WALL_S: Final = 60.0
_HTTP_OK: Final = 200
_RUFF_FINDINGS: Final = 1


class ScanFailed(RuntimeError):
    """The scanner could not read the checkout; nothing found would be a claim nobody measured."""


class AdvisoriesUnreachable(RuntimeError):
    """The advisory database gave no answer; the dependency question is INCONCLUSIVE, never clean."""


def _digest(value: str) -> str:
    return 'sha256:' + hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]


def code_findings(
    root: Path, *, exclude: Mapping[str, str], ignore: Mapping[str, str], tracked: Collection[str] | None = None
) -> list[str]:
    """``path:line:col: Sxxx message`` for every bandit finding in a TRACKED file under *root*.

    *exclude* and *ignore* are the REPO's differences (``{glob or code: reason}``), on top of
    :data:`FAMILY_EXCLUDE` and :data:`FAMILY_IGNORE`; a difference without a reason is refused. Ruff walks
    the tree and only findings in files git tracks are kept, so an untracked scratch file judges nothing;
    *tracked* (relative posix paths) replaces ``git ls-files`` when the tree is not a checkout.

    Raises:
        ScanFailed: ruff erred instead of reporting, git could not list the files, or a difference carries
            no reason.

    """
    for name, reason in {**exclude, **ignore}.items():
        if not reason.strip():
            msg = f'security: {name!r} is declared with no reason -- a waiver must say why'
            raise ScanFailed(msg)
    codes = ','.join(sorted({*FAMILY_IGNORE, *ignore}))
    globs = ','.join(sorted({*FAMILY_EXCLUDE, *exclude}))
    argv = [sys.executable, '-m', 'ruff', 'check', '--isolated', '--select', 'S', '--ignore', codes]
    argv += ['--extend-exclude', globs, '--output-format', 'concise', '--no-cache', '--quiet', '.']
    done = _door.run(argv, cwd=root, capture_output=True, text=True, encoding='utf-8', check=False)
    if done.returncode not in {0, _RUFF_FINDINGS}:
        msg = f'security: ruff exited {done.returncode}, an error rather than a report: {done.stderr.strip()}'
        raise ScanFailed(msg)
    kept = set(_tracked(root) if tracked is None else tracked)
    found = (line.replace('\\', '/') for line in done.stdout.splitlines() if line.strip())
    return [line for line in found if line.split(':', 1)[0] in kept]


def scan_secrets(text: str) -> list[tuple[int, str, str]]:
    """``(line, kind, sha256 digest)`` for every credential shape in *text*; the value itself is never kept."""
    return [
        (number, kind, _digest(found.group(0)))
        for number, line in enumerate(text.splitlines(), 1)
        for kind, pattern in SECRET_PATTERNS
        for found in pattern.finditer(line)
    ]


def _tracked(root: Path) -> list[str]:
    try:
        done = _door.run(['git', 'ls-files', '-z'], cwd=root, capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as why:
        msg = f'security: git could not list the tracked files of {root}: {why}'
        raise ScanFailed(msg) from why
    return [name for name in done.stdout.decode('utf-8').split('\0') if name]


def secret_findings(root: Path, *, allowed: Mapping[str, str], tracked: Collection[str] | None = None) -> list[str]:
    """``path:line: kind: sha256:<12>`` for every credential in a tracked file under *root*.

    *allowed* is the REPO's difference: ``{"sha256:<12 hex>": reason}`` for a deliberate fake (a test
    vector), keyed by the DIGEST so the allowance cannot spell the value and survives a moved line.
    *tracked* replaces ``git ls-files`` as in :func:`code_findings`.

    Raises:
        ScanFailed: git could not list the files, or an allowance carries no reason.

    """
    if blank := sorted(key for key, reason in allowed.items() if not reason.strip()):
        msg = f'security: {blank} allowed with no reason -- an allowance must say why'
        raise ScanFailed(msg)
    found: list[str] = []
    for name in _tracked(root) if tracked is None else tracked:
        if _ENV_FILE.search(name):
            found.append(f'{name}:0: env file: tracked')
        path = root / name
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b'\0' in data:
            continue
        rel = PurePosixPath(name).as_posix()
        hits = scan_secrets(data.decode('utf-8', errors='replace'))
        found.extend(f'{rel}:{line}: {kind}: {digest}' for line, kind, digest in hits)
    return [hit for hit in found if hit.rsplit(': ', 1)[-1] not in allowed]


def locked_packages(lock: Path) -> dict[str, str]:
    """``{name: version}`` of every package ``uv.lock`` pins FROM A REGISTRY; git and path sources are the family's."""
    data = tomllib.loads(lock.read_text(encoding='utf-8'))
    return {
        str(package['name']): str(package['version'])
        for package in data.get('package', [])
        if 'registry' in package.get('source', {}) and 'version' in package
    }


def _osv_batch(queries: list[dict[str, object]]) -> list[dict[str, object]]:
    """One ``/v1/querybatch`` round trip; the host is pinned, so nothing in a query can move the request."""
    connection = HTTPSConnection(_OSV_HOST, timeout=_OSV_WALL_S)
    try:
        body = json.dumps({'queries': queries})
        connection.request('POST', '/v1/querybatch', body=body, headers={'Content-Type': 'application/json'})
        answer = connection.getresponse()
        payload = answer.read()
        if answer.status != _HTTP_OK:
            msg = f'{_OSV_HOST} answered HTTP {answer.status}'
            raise AdvisoriesUnreachable(msg)
        results = json.loads(payload.decode('utf-8')).get('results')
    except (OSError, HTTPException, ValueError) as why:
        msg = f'{_OSV_HOST} gave no answer ({why}); the dependency audit is INCONCLUSIVE -- re-run with network'
        raise AdvisoriesUnreachable(msg) from why
    finally:
        connection.close()
    if not isinstance(results, list) or len(results) != len(queries):
        msg = f'{_OSV_HOST} answered {len(queries)} queries with an unreadable result list'
        raise AdvisoriesUnreachable(msg)
    return results


def advisories(
    packages: Mapping[str, str], *, query: Callable[[list[dict[str, object]]], list[dict[str, object]]] = _osv_batch
) -> dict[str, tuple[str, ...]]:
    """``{"name==version": advisory ids}`` for every pinned package OSV knows a vulnerability in.

    Raises:
        AdvisoriesUnreachable: the database did not answer; read this in a fixture so the part is INCONCLUSIVE.

    """
    pinned = sorted(packages.items())
    found: dict[str, tuple[str, ...]] = {}
    for start in range(0, len(pinned), _OSV_BATCH):
        chunk = pinned[start : start + _OSV_BATCH]
        queries: list[dict[str, object]] = [
            {'package': {'name': name, 'ecosystem': 'PyPI'}, 'version': version} for name, version in chunk
        ]
        for (name, version), result in zip(chunk, query(queries), strict=True):
            vulns = result.get('vulns') or []
            if not isinstance(vulns, list):
                msg = f'{_OSV_HOST} answered {name}=={version} with an unreadable vulns field'
                raise AdvisoriesUnreachable(msg)
            if ids := tuple(sorted(str(v['id']) for v in vulns if isinstance(v, dict) and 'id' in v)):
                found[f'{name}=={version}'] = ids
    return found


def vulnerable(found: Mapping[str, tuple[str, ...]], *, accepted: Mapping[str, str]) -> list[str]:
    """``name==version: id`` for every advisory not in the repo's *accepted* ``{id: reason}``.

    Raises:
        ScanFailed: an acceptance carries no reason.

    """
    if blank := sorted(key for key, reason in accepted.items() if not reason.strip()):
        msg = f'security: advisories {blank} accepted with no reason'
        raise ScanFailed(msg)
    return [f'{pin}: {vid}' for pin, ids in sorted(found.items()) for vid in ids if vid not in accepted]
