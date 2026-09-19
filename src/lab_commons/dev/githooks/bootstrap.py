"""The consumer-side BOOTSTRAP: an entry a ``.pre-commit-config.yaml`` names with NO interpreter.

THE GAP THIS CLOSES, AND WHY THE OBVIOUS ANSWERS DO NOT. Every hook entry in this family is
``bash scripts/hooks/with-venv.sh <something>``, and that file is the ONE piece of the git-hook
mechanism that could not move into the wheel, because reaching anything shipped in a wheel costs an
interpreter and ``with-venv.sh`` is the file that FINDS one. MEASURED 2026-09-17 against a real
``pre-commit.exe`` in a throwaway git repo, once with the caller's ``PATH`` carrying a venv and once
without:

* ``language: system`` and ``language: script`` inherit the caller's ``PATH`` UNCHANGED. Invoked the
  way git invokes a hook, ``command -v python`` resolved to
  ``.../AppData/Local/Microsoft/WindowsApps/python`` -- the Microsoft Store stub, which exits 9009
  with "Python was not found" -- and this held even with a real venv's ``Scripts`` present later in
  ``PATH``. So ``python -m lab_commons.dev.githooks`` cannot be the first token of such an entry,
  and a console script cannot be reached by name either: no venv is on ``PATH`` to hold it.
* ``language: python`` PREPENDS pre-commit's OWN managed environment to ``PATH``, before every
  inherited element and independently of what the caller had. Measured first element:
  ``~/.cache/pre-commit/repo<hash>/py_env-python3/Scripts``. A console script installed there is
  therefore nameable as the first token of ``entry``, with nothing in front of it -- measured with
  ``entry: ruff`` / ``additional_dependencies: ['ruff']``, which printed its version.
* ``additional_dependencies`` accepts this package's own install spelling. Measured with
  ``lab-commons @ git+https://github.com/DawnEver/lab-commons.git``: the hook imported
  ``lab_commons.dev.githooks`` out of the managed environment and read :data:`SCRIPTS` back.

So the bootstrap is a CONSOLE SCRIPT and the interpreter in front of it is pre-commit's, supplied by
the ``language:`` the consumer declares. That is the whole trick, and it is the only shape measured
to work: nothing is committed in the consumer, nothing is hand-maintained, and the entry is a
literal name.

THE MANAGED ENVIRONMENT IS A LAUNCHER AND NOTHING ELSE, which is what makes its staleness harmless.
pre-commit resolves ``additional_dependencies`` once and caches the environment forever, so the copy
of this package living there is pinned to whenever that cache was built -- a second install of the
shared package is exactly the fork this subpackage exists to remove. It is not one, because
:func:`main` does not DO the work: it resolves the consumer's OWN interpreter and hands the whole
command to it. Everything that is judged -- ruff, pyright, the gate, ``lab_commons.dev.githooks``
itself -- runs from the consumer's venv at the consumer's version. The cached copy contributes the
six lines below and its protocol is the argv of ``with-venv.sh``, which has been stable since it was
written.

WHAT IT REFUSES TO DO IS EXIT 0 HAVING FOUND NOTHING. A bootstrap that cannot find an interpreter and
returns quietly reads exactly like a hook that passed -- the defect :data:`KINDS` and
:func:`run_hook` were built to refuse one week earlier, arriving by a new route. :class:`NoInterpreter`
is raised, printed, and :func:`main` returns 1.

THE RESOLUTION IS ``with-venv.sh``'s, PORTED RATHER THAN REDESIGNED, and its three measured lessons
travel with it because each was paid for: a lane's own venv WINS when it has one (user directive,
restated 2026-08-10); a venv DIRECTORY is not an ENVIRONMENT, so one with no distribution in it is
not a candidate (measured 2026-08-15, a three-file stub beat a populated venv and every hook died
with ``No module named ruff``); and "has something installed" is not "has what this call asked for",
so the probe asks whether THIS module imports (measured 2026-09-14, a real venv with no ruff in it).

``git-env-repair.sh`` DISSOLVES HERE rather than being ported, and that is the resolution its own
header asks for. Its subject is an inherited, incomplete ``GIT_CONFIG_*`` set that makes every git
call exit 128; its header records that passing the triple as a subprocess ``env=`` mapping survives
the chain intact, and that a shell hook cannot do that for a call it does not make. This module MAKES
the git calls, so it passes :func:`sanitized_env` and the failure cannot occur. The fragment stays
shipped for the shell payload; nothing here needs it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from lab_commons.dev.venvpath import CANDIDATE_RELATIVE_PATHS as _CANDIDATE_RELATIVE_PATHS
from lab_commons.log import emit

__all__ = [
    'CANDIDATE_RELATIVE_PATHS',
    'NoInterpreter',
    'command_for',
    'find_interpreter',
    'main',
    'needed_module',
    'repo_roots',
    'sanitized_env',
]

#: Re-exported from :mod:`lab_commons.dev.venvpath`, which is now the ONE place this kit spells a
#: venv interpreter. AUTHORED here and moved there unchanged: this module was already correct --
#: it probes BOTH layouts on every platform rather than switching on the OS -- and the move is so
#: that the two adoption modules, which were spelling the Windows half by hand in prose a consumer
#: copies, consult the same data instead. The name stays exported here because `find_interpreter`
#: below is documented in terms of it and consumers import it from this module.
CANDIDATE_RELATIVE_PATHS: Final[tuple[tuple[str, ...], ...]] = _CANDIDATE_RELATIVE_PATHS

#: pyright picks the environment it ANALYSES against from the project root it runs in, so a lane
#: without a ``.venv`` silently analyses against the system interpreter and every third-party import
#: goes unresolved (measured 2026-07-28: 41 spurious errors from a venv-less worktree). The source
#: analysed stays the caller's; only the environment is pinned.
_PYRIGHT: Final = 'pyright'


class NoInterpreter(RuntimeError):
    """No venv under this checkout or its main checkout can run what was asked for.

    RAISED rather than reported, because the caller is a git hook and the alternative is an exit code
    of 0. A bootstrap that cannot find an interpreter and returns quietly is indistinguishable from a
    hook that passed -- the same reason :func:`~lab_commons.dev.githooks.run_hook` refuses a
    ``FRAGMENT``.
    """


def sanitized_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """*env* with an INCOMPLETE ``GIT_CONFIG_*`` set dropped whole, ``os.environ`` by default.

    git rejects such a set outright -- ``missing config value GIT_CONFIG_VALUE_0``, exit 128, before
    running anything -- so there is nothing in it to preserve, and dropping it restores exactly the
    behaviour of a process that never set it. It arrives because on Windows an environment variable
    cannot hold the empty string: a caller clearing ``credential.helper`` the documented way through
    ``os.environ`` exports a COUNT and a KEY with no VALUE.

    Returned as a new mapping rather than applied to ``os.environ``: the repair belongs to the git
    calls this module makes, and mutating the process environment would hand it to the wrapped
    command as well, which never asked for it.
    """
    out = dict(os.environ if env is None else env)
    raw = out.get('GIT_CONFIG_COUNT')
    if raw is None or not raw.isdigit():
        return out
    indices = range(int(raw))
    if all(f'GIT_CONFIG_KEY_{i}' in out and f'GIT_CONFIG_VALUE_{i}' in out for i in indices):
        return out
    for i in indices:
        out.pop(f'GIT_CONFIG_KEY_{i}', None)
        out.pop(f'GIT_CONFIG_VALUE_{i}', None)
    out.pop('GIT_CONFIG_COUNT', None)
    return out


def repo_roots(start: Path | None = None) -> tuple[Path, ...]:
    """Both roots to look for a venv in -- this checkout, then its main checkout -- in that order.

    THIS checkout first: a lane that has its own ``.venv`` uses it, so a dependency change belongs to
    the lane instead of being a change to everyone's environment. MAIN is the fallback that makes a
    venv-less worktree work at all, and it cannot be spelled: a hook runs from whichever checkout is
    being committed to, however deep it is nested. ``--git-common-dir`` always points at MAIN's
    ``.git``, one level under MAIN's root, which is what derives it from git rather than from a path.

    De-duplicated, because on MAIN itself the two roots are the same directory and probing it twice
    would report a doubled diagnosis.

    Args:
        start: The directory to ask git from; the process's cwd when omitted.

    Raises:
        NoInterpreter: When *start* is not inside a git checkout at all. The hook has no repo to
            judge, and reporting that is the only useful thing left to do.

    """
    env = sanitized_env()
    cwd = Path.cwd() if start is None else start
    try:
        this = _git(('rev-parse', '--show-toplevel'), cwd, env)
        common = _git(('rev-parse', '--path-format=absolute', '--git-common-dir'), cwd, env)
    except (OSError, subprocess.CalledProcessError) as exc:
        msg = f'{cwd}: git could not name this checkout, so no venv can be looked for ({exc})'
        raise NoInterpreter(msg) from exc
    roots = [Path(this).resolve(), Path(common).resolve().parent]
    return tuple(dict.fromkeys(roots))


def _git(args: Sequence[str], cwd: Path, env: Mapping[str, str]) -> str:
    """One git call, with the repaired environment and an ABSOLUTE git -- never the bare name.

    Looked up rather than spelled, exactly as :func:`~lab_commons.dev.githooks.bash_executable` does
    it: this runs inside a hook, where PATH is whatever the invoking process had, and the measurement
    that motivates this whole module is a PATH lookup returning something other than the tool asked
    for.
    """
    git = shutil.which('git')
    if git is None:
        msg = 'no git on PATH, so this checkout cannot be named and no venv can be looked for'
        raise NoInterpreter(msg)
    done = subprocess.run(
        [git, *args],
        cwd=cwd,
        env=dict(env),
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def _is_populated(venv: Path) -> bool:
    """Whether *venv* holds a DISTRIBUTION, not merely an interpreter.

    An interpreter that exists is not an environment that works, and the difference is invisible
    exactly where it hurts. MEASURED 2026-08-15: a lane carried a ``.venv`` of three files and no
    distributions -- what an interrupted creation leaves -- so an executability probe said yes, it
    won the preference over MAIN's populated venv, and every hook died naming the tool it could not
    import. One ``*.dist-info`` tells a real environment from a placeholder and costs a glob.
    """
    return any(
        any(parent.glob('*.dist-info'))
        for parent in (*venv.glob('lib/python*/site-packages'), venv / 'Lib' / 'site-packages')
        if parent.is_dir()
    )


def _provides(python: Path, module: str) -> bool:
    """Whether *python* can import *module* -- the CALLER's own question, asked of the candidate.

    "Has something installed" is not "has what this call asked for", and the gap is the same one a
    layer up. MEASURED 2026-09-14: a real venv with dist-info files and no ``ruff`` in it passed the
    distribution probe, won the preference, and every commit died with ``No module named ruff`` while
    a populated venv sat one fallback away -- and the message named ruff, so it read as ruff being
    broken. A lane venv that CAN provide the module still wins, so the isolation the user directive
    asked for is untouched; the preference only yields where it would otherwise fail outright.
    """
    if not module:
        return True
    probe = f'import importlib.util, sys; sys.exit(0 if importlib.util.find_spec({module!r}) else 1)'
    try:
        done = subprocess.run(
            [str(python), '-c', probe],
            capture_output=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def needed_module(argv: Sequence[str]) -> str:
    """The module *argv* is about to import, or ``''`` when it names a SCRIPT PATH.

    A script path is not a module name and ``-m`` cannot run one. MEASURED 2026-08-06 in the consumer
    that shipped this wrapper: an entry reading ``with-venv.sh python scripts/gate/covering_tests.py``
    expanded to ``python -m python scripts/...`` and failed instantly with ``No module named python``,
    so from the commit that introduced it until the fix **the pre-push smoke never executed a single
    test** -- and the two repairs made in between were to a selector that was never being reached.
    The ``.py`` suffix is already unambiguous, so it is dispatched on rather than given a flag that
    every call site would have to repeat.
    """
    first = argv[0] if argv else ''
    return '' if first.endswith('.py') else first


def find_interpreter(roots: Sequence[Path], module: str) -> Path:
    """The interpreter to run *module* through: this checkout's when it can, else the main one's.

    Args:
        roots: Candidate checkout roots in preference order, as :func:`repo_roots` returns them.
        module: The module the call is about to import, or ``''`` for a script path.

    Raises:
        NoInterpreter: With a message that distinguishes the two cases, because they have DIFFERENT
            remedies and the wrong one sends the reader to the wrong place: a venv that exists and
            lacks the tool is a missing TOOL, and no venv at all is a missing ENVIRONMENT.

    """
    saw_venv = False
    for root in roots:
        for parts in CANDIDATE_RELATIVE_PATHS:
            candidate = root.joinpath(*parts)
            if not os.access(candidate, os.X_OK) or not _is_populated(root / '.venv'):
                continue
            saw_venv = True
            if _provides(candidate, module):
                return candidate
    where = ' or '.join(str(root) for root in roots) or '(no checkout)'
    if saw_venv:
        msg = (
            f'no .venv under {where} provides {module!r}. A venv EXISTS in at least one of them, so '
            f'this is a missing TOOL rather than a missing environment -- install {module} into one '
            f'of those venvs.'
        )
    else:
        msg = (
            f"no populated .venv under {where}. Create one in either: this checkout's own "
            f'(preferred -- it isolates a dependency change to the lane that made it), or the main '
            f"checkout's, which every worktree without one borrows."
        )
    raise NoInterpreter(msg)


def command_for(python: Path, argv: Sequence[str]) -> list[str]:
    """The argv to run, given the resolved *python*. Pure, so the dispatch can be driven directly.

    Three shapes, and the first two are not special cases of the third:

    * ``pyright`` also pins the environment it ANALYSES against, which is a different question from
      which interpreter runs it -- see :data:`_PYRIGHT`.
    * a ``*.py`` first argument is a SCRIPT PATH and is run as one -- see :func:`needed_module`.
    * anything else is a MODULE and goes through ``-m``.
    """
    rest = list(argv)
    if not rest:
        msg = 'nothing to run: name a module, a script path, or pyright'
        raise NoInterpreter(msg)
    if rest[0] == _PYRIGHT:
        return [str(python), '-m', _PYRIGHT, '--pythonpath', str(python), *rest[1:]]
    if rest[0].endswith('.py'):
        return [str(python), *rest]
    return [str(python), '-m', *rest]


def main(argv: Sequence[str] | None = None) -> int:
    """Resolve the consumer's interpreter and hand it the whole command.

    Args:
        argv: The command to run, as ``with-venv.sh`` took it; ``sys.argv[1:]`` when omitted.

    Returns:
        The wrapped command's exit code, or 1 when no interpreter could be found -- never 0 on a
        failure to bootstrap, which is the one outcome this module exists to make impossible.

    """
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        roots = repo_roots()
        python = find_interpreter(roots, needed_module(args))
        command = command_for(python, args)
    except NoInterpreter as exc:
        emit(f'lab-with-venv: {exc}', err=True)
        return 1
    return subprocess.run(command, check=False, env=sanitized_env()).returncode


if __name__ == '__main__':
    sys.exit(main())
