"""THE REVIEW RUNTIME FOLLOWS THE LOCK: a host's ai-lab is the one its installed dev-lab's ``uv.lock`` pins.

INCIDENT 2026-11-05: host host-a review failed "the review command on this host does not take these arguments": its
ai-lab was a hand-built venv the machine file named (``[runtimes.ai_lab] python``), and it had drifted from the
ai-lab dev-lab pins. CI had already solved it (dev-lab #107, the ``method`` step of ``ci_base.toml``): the ai-lab
COMMIT is the one the door's dev-lab lock pins, and every package beside it is ai-lab's OWN lock at that commit,
exported ``--frozen`` and installed ``--no-deps``, so nothing resolves past it. A host now does the same, so the
lock is the one source and no path is maintained by hand:

* :func:`kit` -- the installed dev-lab's lock and where it came from: an editable checkout's ``uv.lock`` (a
  workstation's serve checkout), else the lock at the commit a git install records (PEP 610; the ops judge),
  fetched once and cached;
* :func:`ensure` -- ``<forge home>/runtimes/ai-lab-<sha12>/``, REUSED while its ``READY`` stamp names the pinned
  commit, BUILT when the pin moved (CI's steps, :data:`EXPORT`), every other ``ai-lab-*`` removed after;
* :func:`review_runtimes` -- the ``[runtimes]`` a review command is filled from: the machine file's, each
  ``--runtime NAME.KEY=VALUE`` over it, and ``ai_lab.python`` from :func:`ensure` unless a ``--runtime`` names
  one (a CI runner hands the interpreter its ``method`` step built).

ai-lab is fetched from the forge dev-lab came from (``<owner>/ai-lab.git`` beside ``<owner>/dev-lab.git``), as
CI fetches ``${FAMILY_SOURCE}ai-lab.git``: one owner, one credential, the commit the lock pins.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlparse
from urllib.request import url2pathname

import lab_commons.launch as _door

from dev_lab.dev.forgereview_runtimes import host_runtimes, runtimes_with
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.servelock import forge_home

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = [
    'EXPORT',
    'PACKAGE',
    'READY',
    'RUNTIME',
    'build',
    'ensure',
    'interpreter',
    'kit',
    'pinned',
    'review_runtimes',
    'runtime_dir',
    'sibling',
]

#: The ``[runtimes]`` name the family's review commands read (``{runtimes.ai_lab.python}``), and its package.
RUNTIME: Final = 'ai_lab'
PACKAGE: Final = 'ai-lab'

#: ai-lab's own lock as requirements: frozen, no hashes, ai-lab itself installed after (CI's ``method`` step).
EXPORT: Final = (
    'export',
    '--no-config',
    '--frozen',
    '--no-hashes',
    '--no-header',
    '--no-annotate',
    '--no-emit-project',
)

#: The stamp a finished build writes LAST, holding the commit: a runtime without it is rebuilt, never used.
READY: Final = 'READY'

#: Runs one argv to completion; its stdout. A nonzero exit raises.
type Run = Callable[[Sequence[str]], str]


def _run(argv: Sequence[str]) -> str:
    done = _door.run(
        list(argv), capture_output=True, text=True, encoding='utf-8', errors='replace', check=False,
        stdin=subprocess.DEVNULL,
    )  # fmt: skip
    if done.returncode:
        msg = f'{" ".join(argv[:3])} ... exit {done.returncode}: {done.stderr.strip()[-400:]}'
        raise ValueError(msg)
    return done.stdout


def _net(argv: Sequence[str]) -> str:
    report = run_network_verb(argv)
    if not report.ok:
        raise ValueError(report.remedy)
    return ''


def pinned(lock: str) -> str:
    """The ai-lab commit *lock* (a ``uv.lock``'s text) pins; refused unless it pins exactly one, from git."""
    sources = [p.get('source', {}) for p in tomllib.loads(lock).get('package', []) if p.get('name') == PACKAGE]
    if len(sources) != 1:
        msg = 'the dev-lab lock pins no ai-lab' if not sources else 'the dev-lab lock pins ai-lab twice'
        raise ValueError(msg)
    git = sources[0].get('git', '')
    if '#' not in git:
        msg = f'ai-lab is locked from {sources[0]}, not a git revision'
        raise ValueError(msg)
    return git.rpartition('#')[2]


def sibling(url: str, repo: str = PACKAGE) -> str:
    """*repo*'s clone URL beside the repo *url* names on the same owner: ``<owner>/<repo>.git``."""
    owner = url.rstrip('/').removeprefix('git+').rpartition('/')[0]
    if not owner:
        msg = f'{url!r} names no owner to fetch {repo} from'
        raise ValueError(msg)
    return f'{owner}/{repo}.git'


def runtime_dir(home: Path, commit: str) -> Path:
    """Where the runtime for ai-lab *commit* lives: ``<home>/runtimes/ai-lab-<sha12>``."""
    return home / 'runtimes' / f'{PACKAGE}-{commit[:12]}'


def interpreter(venv: Path) -> Path:
    """*venv*'s interpreter."""
    return venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def build(venv: Path, source: str, commit: str, *, run: Run = _run, net: Run = _net) -> None:
    """Build *venv* as CI's ``method`` step does: ai-lab *commit* from *source*, its own lock ``--frozen``."""
    src, python = venv.with_name(f'{venv.name}.src'), interpreter(venv)
    shutil.rmtree(src, ignore_errors=True)
    run([sys.executable, '-I', '-m', 'venv', str(venv)])
    net([str(python), '-I', '-m', 'pip', 'install', '-q', 'uv'])
    uv = str(python.with_name('uv.exe' if os.name == 'nt' else 'uv'))
    net(['git', 'clone', '-q', '--no-tags', '--filter=blob:none', '--no-checkout', source, str(src)])
    net(['git', '-C', str(src), 'fetch', '-q', '--no-tags', 'origin', commit])
    run(['git', '-C', str(src), 'checkout', '-q', '--detach', commit])
    requirements = venv.with_name(f'{venv.name}.txt')
    requirements.write_text(run([uv, *EXPORT, '--project', str(src)]), encoding='utf-8')
    install = [uv, 'pip', 'install', '--no-config', '--no-deps', '--python', str(python)]
    net([*install, '-r', str(requirements)])
    run([*install, str(src)])
    requirements.unlink()
    shutil.rmtree(src, ignore_errors=True)


def ensure(home: Path, source: str, commit: str, *, build: Callable[..., None] = build) -> Path:
    """The interpreter of the runtime for *commit*: reused when stamped READY for it, else (re)built and stamped.

    A build that did not finish leaves no stamp, so the next call rebuilds it from scratch. After a build every
    other ``ai-lab-*`` runtime is removed: a pin that moved leaves nothing behind.
    """
    venv = runtime_dir(home, commit)
    stamp = venv / READY
    if stamp.is_file() and stamp.read_text(encoding='utf-8').strip() == commit and interpreter(venv).is_file():
        return interpreter(venv)
    shutil.rmtree(venv, ignore_errors=True)
    venv.parent.mkdir(parents=True, exist_ok=True)
    build(venv, source, commit)
    stamp.write_text(f'{commit}\n', encoding='utf-8')
    for old in venv.parent.glob(f'{PACKAGE}-*'):
        if old.is_dir() and old != venv:
            shutil.rmtree(old, ignore_errors=True)
    return interpreter(venv)


def kit(home: Path, *, origin: dict[str, Any] | None = None, run: Run = _run, net: Run = _net) -> tuple[str, str]:
    """The installed dev-lab's ``uv.lock`` text and the URL it came from.

    *origin* is dev-lab's PEP 610 ``direct_url.json`` (default: the installed distribution's). An editable install
    is a checkout: its ``uv.lock``, its ``origin`` remote. A git install names its commit: the lock at that commit,
    fetched once into ``<home>/runtimes/dev-lab-<sha12>.uv.lock``. Anything else names no lock and is refused.
    """
    if origin is None:
        origin = json.loads(metadata.distribution('dev-lab').read_text('direct_url.json') or '{}')
    url = origin.get('url', '')
    if origin.get('dir_info', {}).get('editable'):
        root = Path(url2pathname(urlparse(url).path))
        remote = run(['git', '-C', str(root), 'remote', 'get-url', 'origin']).strip()
        return (root / 'uv.lock').read_text(encoding='utf-8'), remote
    commit = origin.get('vcs_info', {}).get('commit_id', '')
    if not commit:
        msg = f'dev-lab is installed from {url or "nowhere recorded"}, so no lock names the ai-lab it pins'
        raise ValueError(msg)
    cached = home / 'runtimes' / f'dev-lab-{commit[:12]}.uv.lock'
    if not cached.is_file():
        cached.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cached.parent) as clone:
            net(['git', 'clone', '-q', '--no-tags', '--filter=blob:none', '--no-checkout', url, clone])
            net(['git', '-C', clone, 'fetch', '-q', '--no-tags', 'origin', commit])
            cached.write_text(run(['git', '-C', clone, 'show', f'{commit}:uv.lock']), encoding='utf-8')
    return cached.read_text(encoding='utf-8'), url


def review_runtimes(given: Sequence[str] = ()) -> dict[str, dict[str, Any]]:
    """The ``[runtimes]`` a review command is filled from: the machine file's, *given* over it, ai-lab locked.

    ``ai_lab.python`` is the runtime :func:`ensure` keeps for the commit the installed dev-lab pins, unless *given*
    names one (``--runtime ai_lab.python=...``: a CI runner's ``method`` step built it from the same lock).
    """
    out = runtimes_with(host_runtimes(), given)
    if not out.get(RUNTIME, {}).get('python'):
        where = forge_home()
        lock, came_from = kit(where)
        out.setdefault(RUNTIME, {})['python'] = str(ensure(where, sibling(came_from), pinned(lock)))
    return out
