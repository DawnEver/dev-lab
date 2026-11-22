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
* ``uv-cache-tmp``: a ``.tmp*`` entry of ``<root>/cache/uv``, what an interrupted install left.

Every other retention rule (runs, trees, builds, packs, artefacts, logs, rust) reads the forge's run state and
needs the kit: :mod:`dev_lab.dev.retention`, on the account.

A REFERENCED PATH IS KEPT, BY NAME (:func:`referenced`): one a live process works in, executes from or names, one a
crontab line names, one this interpreter runs from, one that holds the declared root. A crontab or a process table
that cannot be read keeps everything; a running ``uv`` keeps every cache entry. A dry run unless the spec says
``apply``; the lines are :mod:`dev_lab.dev.retention`'s -- one JSON line per path, then one line per rule and a total.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

__all__ = ['EVENT', 'OLD_COPY', 'UV_TMP', 'VENV', 'candidates', 'crontab', 'main', 'processes', 'referenced', 'sweep']

EVENT = 'lab_commons.forge.retention'
OLD_COPY = 'old-copy'
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
    found = [(path, OLD_COPY, '') for path in old]
    for envs in sorted((root / 'repos').glob(f'*/{spec["envs"]}')):
        current = _real(envs.parent / spec['pointer'])
        found += [(env, VENV, '') for env in sorted(envs.iterdir()) if env.is_dir() and _real(env) != current]
    installing = live is None or any(Path(one['exe']).name == 'uv' for one in live)
    busy = 'a uv process is running: its cache is in use' if installing else ''
    found += [(tmp, UV_TMP, busy) for tmp in sorted((root / 'cache' / 'uv').glob('.tmp*'))]
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


def _writable(path: Path) -> None:
    """Make every entry of the tree at *path* writable, so a read-only file a build left can be removed."""
    path.chmod(_OWNER)
    for here, dirs, names in os.walk(path):
        for entry in (Path(here, name) for name in (*dirs, *names)):
            if not entry.is_symlink():
                entry.chmod(_OWNER)


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        try:
            shutil.rmtree(path)
        except PermissionError:  # a read-only entry; no rmtree error hook spans 3.8 and 3.12+ alike
            _writable(path)
            shutil.rmtree(path)
    else:
        path.unlink()


def sweep(
    spec: dict, *, home: Path, root: Path, cron: str | None, live: list[dict] | None, say: Callable[[str], None] = print
) -> dict[str, tuple[int, int, int]]:
    """Judge every candidate, delete the unreferenced when the spec says ``apply``; per rule (paths, bytes, files)."""
    apply, by_rule = bool(spec.get('apply')), {}
    for path, rule, busy in candidates(spec, home, root, live):
        if why := busy or referenced(path, home=home, root=root, cron=cron, live=live):
            say(f'[retention] kept ({rule}): {path.as_posix()} -- {why}')
            continue
        size, files = _measure(path)
        if apply:
            _remove(path)
        paths, total, count = by_rule.get(rule, (0, 0, 0))
        by_rule[rule] = (paths + 1, total + size, count + files)
        row = {'path': str(path), 'bytes': size, 'files': files, 'rule': rule, 'dry_run': not apply}
        say(json.dumps({'event': EVENT, **row}))
    verb = 'deleted' if apply else 'would delete'
    for rule, (paths, size, files) in sorted(by_rule.items()):
        say(f'[retention] {verb} {rule}: {paths} paths, {size / _MB:.1f} MB, {files} files')
    paths, size, files = (sum(row[at] for row in by_rule.values()) for at in range(3))
    say(f'[retention] {verb} {paths} paths, {size / _MB:.1f} MB, {files} files')
    return by_rule


def main(argv: list[str]) -> int:
    """``python - '<spec json>'``: the spec names the declared root, the lists and whether to ``apply``; 0 always."""
    spec = json.loads(argv[0])
    sweep(spec, home=Path.home(), root=Path(spec['root']), cron=crontab(), live=processes())
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
