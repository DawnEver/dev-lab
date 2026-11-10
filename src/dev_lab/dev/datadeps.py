"""A DATA dependency is pinned like a code one: the repo declares it, a sync checks out exactly that commit.

A family repo can depend on another repo that is DATA, not a Python package: a library of recipes that the code
reads from a git-ignored directory. Before this, the consumer read whatever copy the box happened to hold, so a
test judged an unknown revision and the data repo's own pull requests never reached the consumer's tests.

ONE DECLARATION (``pyproject.toml``)::

    [tool.dev_lab.data.<name>]
    url = "https://forge.example.org/team/recipes.git"   # where it lives
    line = "integrate/main"                                # the line a relock follows
    rev = "<40-hex sha>"                                   # THE pin: what every reader gets
    path = "recipes"                                       # the git-ignored checkout, relative to the repo root

* :func:`sync` makes ``path`` a checkout of ``rev`` (clone or fetch through the retrying network door, then a
  detached checkout); a checkout with local edits is refused, never overwritten.
* :func:`stale` is the ONE reading of "the copy here is the pin": a consumer's test calls it and refuses a copy
  at any other commit, naming the sync.
* :func:`relock` moves ``rev`` to ``line``'s current head -- ``forge sync`` calls it beside the lock relock, so a
  data pin follows its line exactly the way a floated sibling does.

``python -m dev_lab.dev.datadeps sync|check|relock [--root DIR]``.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

import tomlkit
from lab_commons.log import emit

from dev_lab.dev.gitenv import unlocated
from dev_lab.dev.netverb import run_network_verb

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ['DataDep', 'DataRefused', 'declared', 'main', 'relock', 'stale', 'sync']

_GIT: Final = 'git'
_SHA: Final = re.compile(r'[0-9a-f]{40}')
#: The remedy every refusal names.
SYNC: Final = 'python -m dev_lab.dev.datadeps sync'


class DataRefused(RuntimeError):
    """A data dependency cannot be read, synced or relocked; the message names why and the remedy."""


@dataclass(frozen=True)
class DataDep:
    """One ``[tool.dev_lab.data.<name>]`` row."""

    name: str
    url: str
    line: str
    rev: str
    path: str


def declared(root: Path) -> tuple[DataDep, ...]:
    """Every data dependency *root*'s ``pyproject.toml`` declares; RAISES :class:`DataRefused` on a malformed row."""
    pyproject = root / 'pyproject.toml'
    if not pyproject.is_file():
        return ()
    table = tomllib.loads(pyproject.read_text(encoding='utf-8')).get('tool', {}).get('dev_lab', {}).get('data', {})
    deps = []
    for name, row in sorted(table.items()):
        missing = [key for key in ('url', 'line', 'rev', 'path') if not isinstance(row.get(key), str) or not row[key]]
        if missing:
            msg = f'[tool.dev_lab.data.{name}] lacks {", ".join(missing)}'
            raise DataRefused(msg)
        if not _SHA.fullmatch(row['rev']):
            msg = f'[tool.dev_lab.data.{name}] rev {row["rev"]!r} is not a full 40-hex commit'
            raise DataRefused(msg)
        if Path(row['path']).is_absolute() or '..' in Path(row['path']).parts:
            msg = f'[tool.dev_lab.data.{name}] path {row["path"]!r} must stay inside the repo'
            raise DataRefused(msg)
        deps.append(DataDep(name, row['url'], row['line'], row['rev'], row['path']))
    return tuple(deps)


def _git(cwd: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_GIT, '-C', str(cwd), *argv], capture_output=True, text=True, encoding='utf-8', errors='replace',
        check=False, env=unlocated(),
    )  # fmt: skip


def _network(*argv: str, cwd: Path | None = None) -> None:
    report = run_network_verb([_GIT, *argv], cwd=cwd, env=unlocated(), timeout=600)
    if not report.ok:
        msg = f'`git {" ".join(argv)}` failed: {report.remedy}'
        raise DataRefused(msg)


def _head(checkout: Path) -> str | None:
    done = _git(checkout, 'rev-parse', 'HEAD')
    return done.stdout.strip() if done.returncode == 0 else None


def stale(root: Path, dep: DataDep) -> str | None:
    """Why *root*'s copy of *dep* is not its pin, or ``None`` when it is; the ONE reading every consumer calls."""
    checkout = root / dep.path
    if not (checkout / '.git').exists():
        return f'{dep.name}: no checkout at {checkout}; run `{SYNC}`'
    if (head := _head(checkout)) != dep.rev:
        return f'{dep.name}: {checkout} is at {head}, the pin is {dep.rev}; run `{SYNC}`'
    return None


def sync(root: Path, dep: DataDep) -> str:
    """Make *root*/``path`` a checkout of *dep*'s pin; what it did. RAISES :class:`DataRefused`."""
    checkout = root / dep.path
    if not (checkout / '.git').exists():
        if checkout.exists() and any(checkout.iterdir()):
            msg = f'{checkout} exists and is not a git checkout: move it aside, then run `{SYNC}`'
            raise DataRefused(msg)
        _network('clone', '-q', '--no-checkout', dep.url, str(checkout))
    elif (origin := _git(checkout, 'remote', 'get-url', 'origin').stdout.strip()) != dep.url:
        msg = f'{checkout} clones {origin}, the declaration names {dep.url}'
        raise DataRefused(msg)
    elif _git(checkout, 'status', '--porcelain').stdout.strip():
        msg = f'{checkout} has local changes: commit them to {dep.url} or discard them, then run `{SYNC}`'
        raise DataRefused(msg)
    if _head(checkout) == dep.rev:
        return f'{dep.name}: already at {dep.rev[:12]}'
    if _git(checkout, 'cat-file', '-e', f'{dep.rev}^{{commit}}').returncode != 0:
        _network('fetch', '-q', '--no-tags', 'origin', dep.rev, cwd=checkout)
    if (done := _git(checkout, 'checkout', '-q', '--detach', dep.rev)).returncode != 0:
        msg = f'checking out {dep.rev} in {checkout} failed: {done.stderr.strip()}'
        raise DataRefused(msg)
    return f'{dep.name}: {checkout} at {dep.rev[:12]}'


def _line_head(dep: DataDep) -> str:
    report = run_network_verb([_GIT, 'ls-remote', dep.url, f'refs/heads/{dep.line}'], env=unlocated(), timeout=120)
    ref = f'refs/heads/{dep.line}'
    heads = [row.split('\t')[0] for row in report.attempts[-1].output.splitlines() if row.endswith(f'\t{ref}')]
    sha = heads[0] if report.ok and len(heads) == 1 else ''
    if not _SHA.fullmatch(sha):
        msg = f'{dep.name}: the head of {dep.line} on {dep.url} could not be read'
        raise DataRefused(msg)
    return sha


def relock(root: Path) -> tuple[str, ...]:
    """Move every declared pin to its line's head, rewriting ``pyproject.toml`` only; the names that moved."""
    moves = {dep.name: head for dep in declared(root) if (head := _line_head(dep)) != dep.rev}
    if moves:
        pyproject = root / 'pyproject.toml'
        doc = tomlkit.parse(pyproject.read_text(encoding='utf-8'))
        rows = cast('dict[str, dict[str, str]]', cast('Any', doc)['tool']['dev_lab']['data'])  # declared() read them
        for name, head in moves.items():
            rows[name]['rev'] = head
        pyproject.write_text(tomlkit.dumps(doc), encoding='utf-8', newline='')
    return tuple(sorted(moves))


def main(argv: Sequence[str] | None = None) -> int:
    """``sync`` / ``check`` / ``relock``: exit 0 when every declared data dependency is (now) its pin."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.datadeps', description=__doc__.split('\n', 1)[0])
    parser.add_argument('verb', choices=('sync', 'check', 'relock'))
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        deps = declared(args.root)
        if args.verb == 'relock':
            moved = relock(args.root)
            emit(f'[data] relocked: {", ".join(moved)}' if moved else '[data] every pin is at its line head')
            return 0
        if args.verb == 'sync':
            for dep in deps:
                emit(f'[data] {sync(args.root, dep)}')
            return 0
        reasons = [reason for dep in deps if (reason := stale(args.root, dep))]
    except DataRefused as refused:
        emit(f'[data] refused: {refused}', err=True)
        return 2
    for reason in reasons:
        emit(f'[data] stale: {reason}', err=True)
    return 1 if reasons else 0


if __name__ == '__main__':
    raise SystemExit(main())
