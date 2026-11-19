"""``python -m dev_lab.dev.storage {where|render|migrate}`` -- the storage kinds of a checkout, resolved once.

Where a kind (run output, venvs, worktrees, caches) of a repo lives is :func:`lab_commons.storage.root`; this
module is dev-lab's ONE adapter onto it (:func:`kind_root`, :func:`output_path`) plus the three doors:

* ``where [<kind>...]`` prints each kind's root for this checkout and whether it is bound.
* ``render [--to P]`` writes the rclone remotes this machine reaches -- the family's options plus each remote's
  secret, read ONLY from ``<[storage] secrets>/<name>.toml`` (placed there by ``ops secret place``) -- to an
  owner-only file outside every repo (:func:`dev_lab.dev.artefactstores.check_rclone_config`). Nobody
  hand-edits an rclone config; the secret never reaches argv, a log or this module's output.
* ``publish [--to P]`` writes the bound roots as JSON (:func:`publish`) for the agent-guard engine, which reads no
  TOML: a worktree under a bound ``worktrees`` root is admitted by WORKTREES-STAY-INSIDE only through it.
* ``migrate <kind>`` moves the in-tree default of a bound kind to its bound root ONCE and leaves a marker; a
  later in-tree copy of a bound kind is refused by name (:func:`refuse_stale`) -- never read as a fallback.

The repo name a root's ``{repo}`` takes is the MAIN checkout's directory name, so every worktree of one repo
shares one bound root.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from lab_commons import storage as _storage
from lab_commons.log import emit

from dev_lab.dev.gitdirs import common_dir

__all__ = [
    'MARKER',
    'ROOTS_ENV',
    'StaleTree',
    'checkout_output_path',
    'kind_root',
    'main_of',
    'migrate',
    'output_path',
    'publish',
    'refuse_stale',
    'render',
    'rendered',
    'roots_file',
    'worktrees_root',
]

#: The file a migration leaves at the bound root, naming the tree it came from.
MARKER: Final = '.storage-migrated'

#: Where ``render`` writes when no ``--to`` is given: outside every repo, beside the machine's config.
DEFAULT_RCLONE: Final = Path('~/.config/lab-commons/rclone.conf')
#: Where ``publish`` writes the machine's bound roots for readers with no TOML parser (the agent-guard engine).
DEFAULT_ROOTS: Final = Path('~/.config/lab-commons/storage-roots.json')
#: The variable that moves :data:`DEFAULT_ROOTS` (a test's own file).
ROOTS_ENV: Final = 'LAB_COMMONS_STORAGE_ROOTS'


class StaleTree(RuntimeError):
    """A bound kind still has an in-tree copy: migrate it once, or delete the leftover."""


def main_of(tree: Path) -> Path:
    """The MAIN checkout of *tree*, read off ``.git``/``commondir`` (no git process); *tree* itself outside one.

    Every writer asks this, the walls ledger on each stop among them, so it reads files rather than starting git
    (:func:`dev_lab.dev.gitdirs.common_dir`).
    """
    common = common_dir(Path(tree))
    return common.parent if common is not None else Path(tree)


def kind_root(kind: str, tree: Path, *, declared: _storage.Storage | None = None) -> Path | None:
    """Where *kind* of the checkout *tree* lives: bound by this machine, or its in-tree default."""
    main = main_of(tree)
    return _storage.root(kind, main.name, main, storage=declared)


def worktrees_root(tree: Path, *, declared: _storage.Storage | None = None) -> Path:
    """Where the linked worktrees of *tree*'s repository live: the bound ``worktrees`` root, else in-tree."""
    found = kind_root('worktrees', tree, declared=declared)
    if found is None:  # pragma: no cover -- worktrees always has an in-tree default
        msg = 'the worktrees storage kind has no root'
        raise _storage.StorageError(msg)
    return found


def output_path(tree: Path, *parts: str, declared: _storage.Storage | None = None) -> Path:
    """A path under the checkout's ``output`` kind -- every dev-lab writer's ``output/...`` goes through here."""
    found = kind_root('output', tree, declared=declared)
    if found is None:  # pragma: no cover -- output always has an in-tree default
        msg = 'the output storage kind has no root'
        raise _storage.StorageError(msg)
    return found.joinpath(*parts)


def checkout_output_path(tree: Path, *parts: str, declared: _storage.Storage | None = None) -> Path:
    """:func:`output_path` for a writer that belongs to a checkout (the forge outbox, the intent journal).

    Raises:
        RuntimeError: when *tree* is in no git repository -- a deployed judge runs from ``/`` and must never
            write a checkout-shaped tree under whatever directory it was started in.

    """
    if common_dir(Path(tree)) is None:
        msg = f'not a git repository: {tree} -- this journal lives in a checkout'
        raise RuntimeError(msg)
    return output_path(tree, *parts, declared=declared)


def refuse_stale(kind: str, tree: Path, *, declared: _storage.Storage | None = None) -> None:
    """Refuse a bound *kind* whose in-tree default still holds data: it was never migrated, or came back."""
    declared = _storage.declared() if declared is None else declared
    default = _storage.KINDS[kind]
    if kind not in declared.roots or default is None:
        return
    leftover = main_of(tree) / default
    if leftover.exists() and any(leftover.iterdir()):
        msg = (
            f'{leftover} holds {kind!r} data, but this machine binds {kind!r} to {declared.roots[kind]}: '
            f'run `python -m dev_lab.dev.storage migrate {kind}` once, or delete the leftover'
        )
        raise StaleTree(msg)


def migrate(kind: str, tree: Path, *, declared: _storage.Storage | None = None) -> Path:
    """Move *kind*'s in-tree default to its bound root once; return the bound root."""
    declared = _storage.declared() if declared is None else declared
    if kind not in declared.roots:
        msg = f'{kind!r} is not bound on this machine: declare [storage.roots] {kind} first'
        raise _storage.StorageError(msg)
    default = _storage.KINDS[kind]
    if default is None:
        msg = f'{kind!r} has no in-tree copy to migrate (its default is the tool cache)'
        raise _storage.StorageError(msg)
    main = main_of(tree)
    source, target = main / default, kind_root(kind, tree, declared=declared)
    target = target if target is not None else source  # a bound kind always has a root
    if (target / MARKER).is_file():
        refuse_stale(kind, tree, declared=declared)
        return target
    if target.exists() and any(target.iterdir()):
        msg = f"{target} is not empty and carries no {MARKER}: it is not this migration's; choose an empty root"
        raise _storage.StorageError(msg)
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.exists():
        if target.exists():
            target.rmdir()
        shutil.move(str(source), str(target))
    else:
        target.mkdir(parents=True, exist_ok=True)
    (target / MARKER).write_text(f'{source}\n', encoding='utf-8')
    return target


def roots_file(environ: dict[str, str] | None = None) -> Path:
    """The published roots file: :data:`ROOTS_ENV` when set, else :data:`DEFAULT_ROOTS`."""
    env = os.environ if environ is None else environ
    return Path(env.get(ROOTS_ENV) or DEFAULT_ROOTS).expanduser()


def publish(to: Path, *, declared: _storage.Storage | None = None) -> Path:
    """Write every BOUND kind as ``{kind: {"root": <template>, "default": <in-tree default>}}`` JSON to *to*.

    The agent-guard engine (node, no TOML) reads this to admit a worktree under a bound home
    (``bound-worktree-home``, :mod:`dev_lab.dev._deny_worktree_row`): the binding stays ONE fact in the machine
    file, and this file is its rendering. No kind bound: an empty object, which admits nothing.
    """
    declared = _storage.declared() if declared is None else declared
    table = {kind: {'root': root, 'default': _storage.KINDS[kind]} for kind, root in sorted(declared.roots.items())}
    to.parent.mkdir(parents=True, exist_ok=True)
    temporary = to.with_name(f'{to.name}.{os.getpid()}.tmp')
    temporary.write_text(f'{json.dumps(table, indent=2)}\n', encoding='utf-8')
    temporary.replace(to)
    return to


def rendered(declared: _storage.Storage) -> str:
    """The rclone config text for every reached remote: family options, then the placed secret's keys."""
    blocks = []
    for remote in declared.reach:
        secrets = declared.secrets or Path()  # lab_commons.storage refuses a reach without one
        secret_file = secrets / f'{remote.name}.toml'
        if not secret_file.is_file():
            msg = (
                f'no secret for remote {remote.name!r} at {secret_file}: place it with '
                f'`python -m dev_lab.ops secret place --path {secret_file}` (TOML of the transport keys)'
            )
            raise _storage.StorageError(msg)
        secret = tomllib.loads(secret_file.read_text(encoding='utf-8'))
        if clash := sorted(set(secret) & set(remote.options)):
            msg = f'{secret_file} restates {clash[0]!r}, a family option of {remote.name!r}: keep only secrets there'
            raise _storage.StorageError(msg)
        lines = [f'[{remote.name}]', *(f'{k} = {v}' for k, v in {**remote.options, **secret}.items())]
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks) + ('\n' if blocks else '')


def render(to: Path, *, repo: Path, declared: _storage.Storage | None = None) -> Path:
    """Write :func:`rendered` to *to* (owner-only, outside *repo*); return the path."""
    from dev_lab.dev.artefactstores import ArtefactRefused, check_rclone_config  # noqa: PLC0415 -- writers import this module

    declared = _storage.declared() if declared is None else declared
    if (to := to.expanduser()).resolve().is_relative_to(repo.resolve()):
        msg = f'the rclone config is never in a repo: render it outside {repo} (e.g. {DEFAULT_RCLONE})'
        raise ArtefactRefused(msg)
    to.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(to, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as out:
        out.write(rendered(declared))
    if os.name != 'nt':
        to.chmod(0o600)
    check_rclone_config(to, repo=repo)
    return to


def _rclone() -> str:
    """The rclone the rendered config serves, from the pinned install place (:mod:`dev_lab.dev.toolrelease`)."""
    from dev_lab.dev.toolrelease import ToolAbsent, resolve  # noqa: PLC0415 -- only render needs the tool table

    try:
        return str(resolve('rclone'))
    except ToolAbsent as absent:
        return f'not installed -- {absent}'


def main(argv: Sequence[str] | None = None) -> int:
    """Run one door; 2 on a refusal (named on stderr)."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.storage', description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='verb', required=True)
    where = sub.add_parser('where', help='print each kind root of this checkout')
    where.add_argument('kinds', nargs='*')
    out = sub.add_parser('render', help='write the reached rclone remotes, owner-only, outside every repo')
    out.add_argument('--to', type=Path, default=DEFAULT_RCLONE)
    move = sub.add_parser('migrate', help='move a bound kind out of the checkout once')
    move.add_argument('kind')
    shown = sub.add_parser('publish', help='write the bound roots for the agent-guard engine')
    shown.add_argument('--to', type=Path, default=None)
    for each in (where, out, move, shown):
        each.add_argument('--tree', type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        declared = _storage.declared()
        if args.verb == 'where':
            for kind in args.kinds or list(_storage.KINDS):
                bound = 'bound' if kind in declared.roots else 'default'
                emit(f'{kind}: {kind_root(kind, args.tree, declared=declared)} ({bound})')
        elif args.verb == 'render':
            emit(f'rendered {len(declared.reach)} remote(s) to {render(args.to, repo=args.tree, declared=declared)}')
            emit(f'rclone: {_rclone()}')
        elif args.verb == 'publish':
            emit(
                f'published {len(declared.roots)} bound root(s) to '
                f'{publish(args.to or roots_file(), declared=declared)}'
            )
        else:
            emit(f'{args.kind}: migrated to {migrate(args.kind, args.tree, declared=declared)}')
    except (_storage.StorageError, StaleTree, ValueError, RuntimeError) as refused:
        emit(f'refused: {refused}', err=True)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
