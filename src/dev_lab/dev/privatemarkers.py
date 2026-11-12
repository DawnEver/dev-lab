"""PRIVATE-MARKERS: no tracked file of a PUBLISHED repo may name a machine, a person, a home path or a chat id.

Shipped as kit because every published repo in the family needs the same scan and a copy per repo
is a fork waiting to drift; each consumer calls :func:`scan_tree` over its own checkout from one
test, and the planted positives and negatives in lab-commons exercise exactly this code.

Two layers:

* GENERIC patterns, committed here, that need no knowledge of whose machine this is: absolute home
  paths not written as a ``<placeholder>``, e-mail addresses outside the reserved example domains,
  Telegram supergroup ids, and an ``OneDrive - <Org>`` folder name.
* An optional MACHINE-LOCAL denylist at ``~/.claude/private-markers`` -- one case-insensitive
  literal or ``/regex/`` per line, ``#`` comments. It names the private values themselves, so it is
  never committed; absent, the layer is silent. A denylist hit is reported by KIND only, never by
  value, so a log of the check cannot leak what it guards.

The TEXT scans (a PR title or body, a pushed commit message) guard PUBLIC repositories only: a private repo
is where private names belong. Visibility is the forge's ``private`` flag (:func:`repo_is_private`); when it
cannot be read, the text is scanned and the reason said -- fail closed.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Final, TextIO

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.forge import NoCredential, Transport, forge_from_remote, forge_of_url, forge_transport
from dev_lab.dev.forgehosts import is_private
from dev_lab.dev.forgework import client_for
from dev_lab.dev.githooks.runner import PUSH_URL_ENV

__all__ = [
    'AUTHORSHIP',
    'GENERIC',
    'MARKERS_FILE',
    'PUBLIC_MASK',
    'load_markers',
    'pushed_messages',
    'repo_is_private',
    'scan_text',
    'scan_tree',
    'staged_added_lines',
    'text_refusal',
    'tracked_files',
]

#: Domains an address may use: the RFC 2606 / 6761 reserved names and GitHub's noreply alias.
_ALLOWED_MAIL = re.compile(
    r'(?:^|\.)(?:example\.com|example\.org|example\.net|users\.noreply\.github\.com)$|\.(?:invalid|example|test)$',
    re.IGNORECASE,
)

GENERIC: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ('windows home path', re.compile(r'\b[A-Za-z]:[\\/]+Users[\\/]+(?![<$%{])[^\\/\s\'"`]+', re.IGNORECASE)),
    ('posix home path', re.compile(r'(?<![\w.])/(?:Users|home)/(?![<$%{])[A-Za-z0-9._-]+')),
    ('telegram chat id', re.compile(r'-100\d{9,}')),
    ('cloud folder', re.compile(r'OneDrive[ ]-[ ](?!<)\S')),
)

_MAIL = re.compile(r'(?<![\\\w.%+-])[A-Za-z0-9][A-Za-z0-9._%+-]*@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})\b')

#: A ``/regex/`` line is the two slashes plus a body, so anything this short is a literal.
_SLASHES: Final = 2

#: The default location of the machine-local denylist; shared with the sibling cc-config check.
MARKERS_FILE: Final = Path.home() / '.claude' / 'private-markers'


def load_markers(path: Path = MARKERS_FILE) -> tuple[re.Pattern[str], ...]:
    """Compile the denylist at *path*; an absent file is an empty denylist, never an error."""
    if not path.is_file():
        return ()
    out: list[re.Pattern[str]] = []
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if len(line) > _SLASHES and line.startswith('/') and line.endswith('/'):
            out.append(re.compile(line[1:-1], re.IGNORECASE))
        else:
            out.append(re.compile(re.escape(line), re.IGNORECASE))
    return tuple(out)


#: The one place each file NAMES ITS AUTHOR on purpose: the copyright line and the package author.
#: The denylist is skipped on exactly these lines -- keyed by path and line shape, so the exemption
#: never has to spell the name it admits. Generic patterns (an author e-mail) still apply here.
AUTHORSHIP: Final[dict[str, re.Pattern[str]]] = {
    'LICENSE': re.compile(r'^\s*Copyright \(c\) \d{4} [^@]+$'),
    'pyproject.toml': re.compile(r'^authors = \[\{ name = "[^"]+" \}\]$'),
}


#: What a public name is masked to before a line is scanned. It opens with ``<``, so a home path whose
#: user segment was a public name reads as a placeholder, exactly as ``<user>`` does.
PUBLIC_MASK: Final = '<public>'


def _mask(line: str, public: tuple[str, ...]) -> str:
    for name in public:
        line = re.sub(re.escape(name), PUBLIC_MASK, line, flags=re.IGNORECASE)
    return line


def scan_text(
    text: str, markers: tuple[re.Pattern[str], ...] = (), *, path: str = '', public: tuple[str, ...] = ()
) -> list[tuple[int, str, str]]:
    """Every ``(line, kind, match)`` in *text*. A private-denylist hit reports its kind only.

    *public* names what the calling repo publishes ON PURPOSE -- its own name, a public sibling, a
    deploy user named after the repo. Each occurrence is masked out of a line before it is scanned:
    one machine-local denylist serves every repo, the kit included, and a repo's own name cannot be
    private to that repo. Masking the OCCURRENCE rather than dropping a denylist entry is the point:
    an entry that is a substring of a public name still fires everywhere else on the line.
    """
    hits: list[tuple[int, str, str]] = []
    authorship = AUTHORSHIP.get(path)
    for number, raw in enumerate(text.splitlines(), 1):
        line = _mask(raw, public)
        for kind, pattern in GENERIC:
            hits.extend((number, kind, m.group(0)) for m in pattern.finditer(line))
        hits.extend((number, 'email', m.group(0)) for m in _MAIL.finditer(line) if not _ALLOWED_MAIL.search(m.group(1)))
        # The matched private value is never echoed: a log of the check must not leak what it guards.
        if authorship is not None and authorship.match(line):
            continue
        hits.extend((number, 'private marker', '<redacted>') for p in markers if p.search(line))
    return hits


def tracked_files(root: Path) -> list[Path]:
    """The files git tracks under *root* -- exactly what a push publishes."""
    done = _door.run(['git', 'ls-files', '-z'], cwd=root, capture_output=True, check=True)
    return [root / name for name in done.stdout.decode('utf-8').split('\0') if name]


def scan_tree(root: Path, markers: tuple[re.Pattern[str], ...] = (), *, public: tuple[str, ...] = ()) -> list[str]:
    """``path:line: kind: match`` for every hit in every tracked text file under *root*."""
    found: list[str] = []
    for path in tracked_files(root):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b'\0' in data:
            continue
        text = data.decode('utf-8', errors='replace')
        rel = path.relative_to(root).as_posix()
        found.extend(f'{rel}:{n}: {kind}: {m}' for n, kind, m in scan_text(text, markers, path=rel, public=public))
    return found


_HUNK = re.compile(r'^@@ -\S+ \+(\d+)(?:,\d+)? @@')


def staged_added_lines(root: Path, paths: list[str]) -> list[tuple[str, int, str]]:
    """``(path, line, text)`` for every line the index ADDS to *paths* -- what this commit introduces, nothing older."""
    if not paths:
        return []
    argv = ['git', '-c', 'core.quotePath=false', 'diff', '--cached', '-U0', '--no-color', '--no-ext-diff', '--', *paths]
    out = _door.run(argv, cwd=root, capture_output=True, check=True).stdout.decode('utf-8', errors='replace')
    added: list[tuple[str, int, str]] = []
    rel, number, in_hunk = '', 0, False
    for line in out.splitlines():
        if line.startswith('diff --git '):
            in_hunk = False
        elif not in_hunk and line.startswith('+++ '):
            rel = line[6:] if line.startswith('+++ b/') else ''
        elif hunk := _HUNK.match(line):
            in_hunk, number = True, int(hunk.group(1))
        elif in_hunk and line.startswith('+') and rel:
            added.append((rel, number, line[1:]))
            number += 1
    return added


#: git's all-zero object name: a pushed ref's remote side when the remote has no such ref yet (or a deletion).
_ZERO = re.compile(r'^0+$')


def pushed_messages(root: Path, ref_lines: str) -> list[tuple[str, str]]:
    """``(sha, message)`` of every commit a push publishes, from git's pre-push *ref_lines* on stdin.

    An existing remote ref: ``<remote sha>..<local sha>``; a new one: the local sha minus every remote-tracking
    ref -- what no remote holds yet. A deletion publishes nothing.
    """
    found: dict[str, str] = {}
    for line in ref_lines.splitlines():
        match line.split():
            case [_, local, _, remote] if not _ZERO.match(local):
                span = [local, '--not', '--remotes'] if _ZERO.match(remote) else [f'{remote}..{local}']
            case _:
                continue
        argv = ['git', 'log', '--format=%H%x00%B%x1e', *span]
        out = _door.run(argv, cwd=root, capture_output=True, check=True).stdout.decode('utf-8', errors='replace')
        for record in out.split('\x1e'):
            sha, _, message = record.strip().partition('\0')
            if sha:
                found[sha] = message
    return list(found.items())


#: Each repository's answer, read once per process: ``(host, owner, repo) -> (private, why unread)``.
_VISIBILITY: dict[tuple[str, str, str], tuple[bool, str]] = {}


def repo_is_private(
    root: Path, *, url: str = '', env: Mapping[str, str] | None = None, transport: Transport = forge_transport
) -> tuple[bool, str]:
    """``(private, why)``: whether the forge says *root*'s ``origin`` (or *url*) is private (the retrying client).

    ``why`` is empty when the flag was read; otherwise it says why it was not, and ``private`` is ``False`` so the
    caller scans -- an unreadable visibility fails closed. Cached per process by repository.
    """
    try:
        forge = forge_of_url(url) if url else forge_from_remote(root)
    except OSError as unread:
        return False, f'repository unknown ({unread})'
    key = (forge.host, forge.owner, forge.repo)
    if key not in _VISIBILITY:
        try:
            _VISIBILITY[key] = is_private(client_for(root, env=env, transport=transport, url=url)), ''
        except (OSError, NoCredential) as unread:
            _VISIBILITY[key] = False, f'visibility of {forge.owner}/{forge.repo} unreadable ({unread})'
    return _VISIBILITY[key]


def text_refusal(text: str, what: str, markers: tuple[re.Pattern[str], ...] | None = None) -> str | None:
    """The PRIVATE-MARKERS refusal for *what* (a PR body...) when *text* holds a marker, else ``None``.

    The markers are the machine-local denylist (:data:`MARKERS_FILE`, read at call time) unless given; a hit is
    named by line and kind only.
    """
    hits = scan_text(text, load_markers(MARKERS_FILE) if markers is None else markers)
    if not hits:
        return None
    named = ', '.join(f'line {n}: {kind}' for n, kind, _ in hits)
    return f'PRIVATE-MARKERS: the {what} names a private value ({named}); neutralise it before it is published.'


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """The local pre-commit row: refuse a marker on a line the index ADDS. Only this machine holds the denylist.

    Judging added lines, not whole files, is the point: a legacy hit on an untouched line is not this commit's,
    and refusing it would block every edit to that file. The tracked-tree test owns the legacy hits.
    """
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.privatemarkers')
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--markers', type=Path, default=MARKERS_FILE)
    parser.add_argument('--push', action='store_true', help="pre-push: judge the pushed commits' messages (stdin)")
    parser.add_argument('--url', default='', help=f'--push: the pushed-to URL (default ${PUSH_URL_ENV}, else origin)')
    parser.add_argument('paths', nargs='*')
    args = parser.parse_args(argv)
    markers = load_markers(args.markers)
    if args.push:
        private, why = repo_is_private(args.root, url=args.url or os.environ.get(PUSH_URL_ENV, ''))
        if private:
            return 0
        if why:
            emit(f'[private-markers] scanning this push: {why}', err=True)
        said = [
            f'{sha[:12]} message line {n}: {kind}'
            for sha, message in pushed_messages(args.root, (sys.stdin if stdin is None else stdin).read())
            for n, kind, _ in scan_text(message, markers)
        ]
        if said:
            emit('PRIVATE-MARKERS: a pushed commit message names a private value; reword it before pushing:', err=True)
            emit('\n'.join(said), err=True)
        return 1 if said else 0
    found = [
        f'{rel}:{number}: {kind}'
        for rel, number, text in staged_added_lines(args.root, args.paths)
        for _, kind, _ in scan_text(text, markers, path=rel)
    ]
    if found:
        emit('PRIVATE-MARKERS: a staged line names a private value; neutralise it before committing:', err=True)
        emit('\n'.join(found), err=True)
    return 1 if found else 0


if __name__ == '__main__':
    raise SystemExit(main())
