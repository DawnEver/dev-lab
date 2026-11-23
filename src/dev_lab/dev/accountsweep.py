"""THE CALLER'S RETENTION RULES, RUN ON AN ACCOUNT THAT CANNOT TAKE AN UPDATE: one file, standard library only.

A DEADLOCK, measured 2026-11-22: an account at its FILE quota (2,019,981 of 2,020,000) cannot update its kit
("unable to create temporary file: Disk quota exceeded"), so ``hpcaccount retention`` ran the kit's OLD retention
there -- no rule for what filled it -- and freed ten files. The cleanup must not depend on the account's kit.

So the workstation STREAMS THIS FILE to the account's interpreter on stdin (``python - <spec>``,
:func:`dev_lab.dev.hpcaccount.storage.streamed_rules_command`): the rules are always the caller's version and NOTHING IS
WRITTEN on the account -- no temp file, no checkout, no import of the kit. It therefore imports nothing but the
standard library and holds NO LIST of its own: what an old copy is, and the names of the environment pointer,
arrive in the spec from their one source (:mod:`dev_lab.dev.oldcopies`, :mod:`dev_lab.dev.venvpointer`).

THE RULES THAT RUN IN THIS MODE -- the ones that matter on a full account:

* ``old-copy``: each declared old copy of the layout before the declared root;
* ``venv-not-current``: a ``<root>/repos/<repo>/.venvs/<name>`` the repo's ``.venv`` pointer does not name -- a
  half-built or superseded environment;
* ``uv-cache-tmp``: a ``.tmp*`` entry of ``<root>/cache/uv``, what an interrupted install left;
* the spec's ``cargo_rule``: an extracted crate under ``~/.cargo/registry/src/<index>/`` untouched for the spec's
  ``cargo_hours`` (the ``.crate`` download cache is never named; cargo re-extracts what a build needs).

A PATH THAT CANNOT BE REMOVED IS NAMED AND KEPT (measured 2026-11-22: one directory the account could not chmod
killed the whole pass with a traceback, nothing after it ran and no summary was printed). Entries that cannot go are
NAMED PER TOP-MOST DIRECTORY holding them (measured next: 206,412 such entries sat under ONE directory, one line each
drowned the output): ``[retention] kept <dir> -- cannot remove N entries: <cause>``; the total line counts them.
The rest of that copy and every other rule go on, and the totals count only what went.

Every other retention rule (runs, trees, builds, packs, artefacts, logs, rust) reads the forge's run state and
needs the kit: :mod:`dev_lab.dev.retention`, on the account.

A REFERENCED PATH IS KEPT, BY NAME (:func:`referenced`): one a live process works in, executes from or names, one a
crontab line names, one this interpreter runs from, one that holds the declared root. A crontab or a process table
that cannot be read keeps everything; a running ``uv`` keeps every cache entry. A dry run unless the spec says
``apply``; the lines are :mod:`dev_lab.dev.retention`'s -- one JSON line per path, then one line per rule and a total.
"""

from __future__ import annotations

import errno
import json
import os
import re
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

__all__ = [
    'EVENT', 'LEFT_BEHIND', 'UV_TMP', 'VENV', 'candidates', 'crontab', 'main', 'processes', 'referenced', 'sweep',
]  # fmt: skip

EVENT = 'lab_commons.forge.retention'
LEFT_BEHIND = 'old-copy'
VENV = 'venv-not-current'
UV_TMP = 'uv-cache-tmp'
_MB = 1024**2
_OWNER = stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC


def _real(path: object) -> str:
    return os.path.realpath(str(path))


def _holds(holder: str, path: str) -> bool:
    """Whether the resolved *path* is the resolved *holder* or lies in it."""
    return bool(path) and (path == holder or path.startswith(holder.rstrip('/\\') + os.sep))


def processes(proc: Path = Path('/proc')) -> list[dict] | None:
    """Every live process but this one, as ``{pid, exe, cwd, argv}``; ``None`` where ``/proc`` cannot be read."""
    if not proc.is_dir():
        return None
    found = []
    for entry in proc.iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            argv = (entry / 'cmdline').read_bytes().decode('utf-8', 'replace').split('\0')
            exe, cwd = str((entry / 'exe').readlink()), str((entry / 'cwd').readlink())
        except OSError:  # another user's process, a kernel thread, or one that just ended
            continue
        found.append({'pid': int(entry.name), 'exe': exe, 'cwd': cwd, 'argv': [word for word in argv if word]})
    return found


def crontab() -> str | None:
    """The account's ``crontab -l`` (``''``: it has none); ``None`` when it cannot be read."""
    try:
        done = subprocess.run(
            ['crontab', '-l'],  # noqa: S607
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=False,
        )
    except OSError:
        return None
    if done.returncode:
        return '' if 'no crontab' in (done.stderr or '') else None
    return done.stdout or ''


def _named(path: Path, home: Path, cron: str) -> bool:
    spelled = [path.as_posix()]
    if _holds(_real(home), _real(path)) and path != home:
        rest = Path(_real(path)).relative_to(_real(home)).as_posix()
        spelled += [f'~/{rest}', f'$HOME/{rest}', f'${{HOME}}/{rest}']
    named = re.compile('|'.join(f'{re.escape(one)}(?![\\w.-])' for one in spelled))
    return any(named.search(line) for line in cron.splitlines() if not line.lstrip().startswith('#'))


def referenced(path: Path, *, home: Path, root: Path, cron: str | None, live: list[dict] | None) -> str:
    """Why *path* is still referenced (``''``: nothing references it)."""
    here = _real(path)
    if _holds(here, _real(root)):
        return 'it holds the declared root: the account still lives in it'
    if any(_holds(here, _real(one)) for one in (sys.executable, sys.prefix, Path.cwd())):
        return 'this retention runs from it'
    if cron is None or live is None:
        return f'the {"crontab" if cron is None else "process table"} cannot be read, so nothing is known not to use it'
    if _named(path, home, cron):
        return 'a crontab line still names it'
    using = [one for one in live if any(_holds(here, _real(word)) for word in (one['exe'], one['cwd'], *one['argv']))]
    return 'a live process still uses it: ' + ', '.join(f'pid {one["pid"]}' for one in using) if using else ''


def candidates(spec: dict, home: Path, root: Path, live: list[dict] | None) -> list[tuple[Path, str, str]]:
    """Every ``(path, rule, why it is kept whatever references it)`` the caller's rules judge on this account."""
    old = [home / p for p in spec['strays_in_home']] + [root / p for p in spec['strays_in_root']]
    old += [repo / spec['retired_pointer'] for repo in sorted((root / 'repos').glob('*'))]
    found = [(path, LEFT_BEHIND, '') for path in old]
    for envs in sorted((root / 'repos').glob(f'*/{spec["envs"]}')):
        current = _real(envs.parent / spec['pointer'])
        found += [(env, VENV, '') for env in sorted(envs.iterdir()) if env.is_dir() and _real(env) != current]
    installing = live is None or any(Path(one['exe']).name == 'uv' for one in live)
    busy = 'a uv process is running: its cache is in use' if installing else ''
    found += [(tmp, UV_TMP, busy) for tmp in sorted((root / 'cache' / 'uv').glob('.tmp*'))]
    if rule := spec.get('cargo_rule'):
        stale = time.time() - float(spec['cargo_hours']) * 3600
        crates = sorted((home / '.cargo' / 'registry' / 'src').glob('*/*'))
        found += [(crate, rule, '') for crate in crates if crate.lstat().st_mtime <= stale]
    return [(path, rule, why) for path, rule, why in found if path.exists() or path.is_symlink()]


def _measure(path: Path) -> tuple[int, int]:
    if not path.is_dir() or path.is_symlink():
        return path.lstat().st_size, 1
    size, files = 0, 1
    for here, dirs, names in os.walk(path):
        for name in (*names, *dirs):
            try:
                size += Path(here, name).lstat().st_size
            except OSError:
                continue
            files += 1
    return size, files


def _grouped(kept: list[tuple[str, OSError]]) -> dict[str, tuple[int, str]]:
    """*kept* per top-most directory holding an entry that could not go: ``{dir: (entries, first cause)}``."""
    groups: dict[str, tuple[int, str]] = {}
    for name, why in kept:
        parent = Path(name).parent.as_posix()
        count, cause = groups.get(parent, (0, why.strerror or str(why)))
        groups[parent] = (count + 1, cause)
    tops: dict[str, tuple[int, str]] = {}
    for parent in sorted(groups, key=len):
        top = next((t for t in tops if parent == t or parent.startswith(t + '/')), parent)
        count, cause = tops.get(top, (0, groups[parent][1]))
        tops[top] = (count + groups[parent][0], cause)
    return tops


def _remove(path: Path, say: Callable[[str], None]) -> tuple[int, int, int]:
    """Remove *path*; what cannot go is named per top-most directory. The (bytes, files, entries) left behind."""
    kept: list[tuple[str, OSError]] = []

    def gone(entry: Path) -> None:
        """Remove one *entry*; refused, its owner bits are set and it is tried once more, else it is kept."""
        remove = entry.rmdir if entry.is_dir() and not entry.is_symlink() else entry.unlink
        try:
            remove()
        except OSError:
            try:
                for one in (entry.parent, entry) if not entry.is_symlink() else (entry.parent,):
                    one.chmod(_OWNER)
                remove()
            except OSError as why:
                if why.errno != errno.ENOTEMPTY:  # a parent of a kept entry: the entry itself is the one counted
                    kept.append((str(entry), why))

    # bottom-up by hand, never shutil.rmtree: its error hook is ``onerror`` before 3.12 and ``onexc`` after
    if path.is_dir() and not path.is_symlink():
        for here, dirs, names in os.walk(path, topdown=False):
            for name in (*names, *dirs):
                gone(Path(here, name))
    gone(path)
    for top, (count, cause) in sorted(_grouped(kept).items()):  # os.walk order is the filesystem's, not stable
        say(f'[retention] kept {top} -- cannot remove {count} entries: {cause}')
    left = _measure(path) if path.exists() or path.is_symlink() else (0, 0)
    return (*left, len(kept))


def sweep(
    spec: dict, *, home: Path, root: Path, cron: str | None, live: list[dict] | None, say: Callable[[str], None] = print
) -> dict[str, tuple[int, int, int]]:
    """Judge every candidate, delete the unreferenced when the spec says ``apply``; per rule (paths, bytes, files)."""
    apply, by_rule, unremovable = bool(spec.get('apply')), {}, 0
    for path, rule, busy in candidates(spec, home, root, live):
        if why := busy or referenced(path, home=home, root=root, cron=cron, live=live):
            say(f'[retention] kept ({rule}): {path.as_posix()} -- {why}')
            continue
        size, files = _measure(path)
        if apply:
            left = _remove(path, say)
            size, files, unremovable = size - left[0], files - left[1], unremovable + left[2]
        paths, total, count = by_rule.get(rule, (0, 0, 0))
        by_rule[rule] = (paths + 1, total + size, count + files)
        row = {'path': str(path), 'bytes': size, 'files': files, 'rule': rule, 'dry_run': not apply}
        say(json.dumps({'event': EVENT, **row}))
    verb = 'deleted' if apply else 'would delete'
    for rule, (paths, size, files) in sorted(by_rule.items()):
        say(f'[retention] {verb} {rule}: {paths} paths, {size / _MB:.1f} MB, {files} files')
    paths, size, files = (sum(row[at] for row in by_rule.values()) for at in range(3))
    held = f'; kept {unremovable} entries that cannot be removed' if unremovable else ''
    say(f'[retention] {verb} {paths} paths, {size / _MB:.1f} MB, {files} files{held}')
    return by_rule


def main(argv: list[str]) -> int:
    """``python - '<spec json>'``: the spec names the declared root, the lists and whether to ``apply``; 0 always."""
    spec = json.loads(argv[0])
    sweep(spec, home=Path.home(), root=Path(spec['root']), cron=crontab(), live=processes())
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
