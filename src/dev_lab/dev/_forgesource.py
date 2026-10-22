"""Whether a request's sha can be built the same on every host: its lock, origin's refs, its git sources.

Split from :mod:`dev_lab.dev.forgerequest`, which re-exports every public name here; a request is
refused, never degraded, when any of these says no.
"""

from __future__ import annotations

import os
import re
import subprocess
import urllib.parse
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from dev_lab.dev.forge import _GIT

__all__ = ['LOCK_FILE', 'REACH_TIMEOUT_S', 'git_sources', 'unreachable_source', 'unreproducible', 'unserved']

#: The lock a request's sha must commit: it pins every dependency revision the tree is built from.
LOCK_FILE: Final = 'uv.lock'


def unreproducible(root: Path, sha: str) -> str:
    """Why a tree built at *sha* would not be the same on every host, ``''`` when it would.

    A sha committing no :data:`LOCK_FILE` resolves its floating dependencies to whatever they are on the
    day, on the host: two runs of one request build two environments, so it is refused, never degraded.
    """
    done = _door.run([_GIT, '-C', str(root), 'cat-file', '-e', f'{sha}:{LOCK_FILE}'], capture_output=True, check=False)
    return '' if done.returncode == 0 else f'{sha[:12]} commits no {LOCK_FILE}: a request pins every dependency'


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


#: A git source in a lock: ``source = { git = "<url>?rev=..#<commit>" }``.
_LOCKED_GIT: Final = re.compile(r'git\s*=\s*"(?P<url>[^"?#]+)')
#: How long one ``git ls-remote`` of a source may take before it counts as unreachable, in seconds.
REACH_TIMEOUT_S: Final = 60.0


def git_sources(root: Path, sha: str) -> tuple[str, ...]:
    """Every repository a tree at *sha* fetches by git: its lock's git sources, then its submodules' urls."""
    lock = _show(root, f'{sha}:{LOCK_FILE}')
    found = [match['url'] for match in _LOCKED_GIT.finditer(lock)]
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
    """``git show <spec>`` (or origin's url when *remote*) at *root*, ``''`` when git cannot say."""
    argv = ['remote', 'get-url', 'origin'] if remote else ['show', spec]
    done = _door.run([_GIT, '-C', str(root), *argv], capture_output=True, text=True, encoding='utf-8', check=False)
    return done.stdout.strip() if done.returncode == 0 else ''
