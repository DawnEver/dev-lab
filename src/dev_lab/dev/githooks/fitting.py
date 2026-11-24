"""The interpreter a bootstrap door names: one that imports dev_lab AND satisfies the checkout's ``requires-python``.

A borrowed interpreter (another checkout's venv, or the one recorded at install) may be older than the checkout
it judges: a 3.12 venv named as the door of a ``>=3.13`` repo is a door that refuses again. So the door is the
first candidate -- the running interpreter, then the main checkout's current venv -- whose version fits.
"""

from __future__ import annotations

import platform
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterable
from pathlib import Path

import lab_commons.launch as _door
from packaging.specifiers import InvalidSpecifier, SpecifierSet

from dev_lab.dev import familyroot, venvpointer

__all__ = ['bootstrap_interpreter', 'candidates', 'fits', 'probe', 'requires_python']

#: Prints the interpreter's version only when it imports dev_lab (the door runs ``-m dev_lab.dev.dep``).
_PROBE = 'import dev_lab, platform; print(platform.python_version())'


def requires_python(root: Path) -> str | None:
    """*root*'s ``[project] requires-python``, else ``None`` (no pyproject, no project table, no bound)."""
    try:
        data = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    spec = data.get('project', {}).get('requires-python')
    return spec if isinstance(spec, str) else None


def fits(version: str, spec: str | None) -> bool:
    """Whether Python *version* satisfies *spec* (no spec, or an unparsable one, bounds nothing)."""
    if not spec:
        return True
    try:
        return SpecifierSet(spec).contains(version, prereleases=True)
    except InvalidSpecifier:
        return True


def probe(python: str) -> str | None:
    """*python*'s version when it runs and imports dev_lab, else ``None``."""
    try:
        done = _door.run([python, '-c', _PROBE], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None if done.returncode == 0 else None


def candidates(root: Path) -> list[str]:
    """The interpreters other than the running one that could run the door: the main checkout's current venv."""
    try:
        main = familyroot.main_checkout(root)
    except RuntimeError:
        return []
    prefix = venvpointer.current(main)
    return [str(path) for path in (prefix / 'Scripts' / 'python.exe', prefix / 'bin' / 'python') if path.is_file()]


def bootstrap_interpreter(
    root: Path,
    others: Iterable[str] | None = None,
    version_of: Callable[[str], str | None] | None = None,
) -> str | None:
    """The first interpreter importing dev_lab whose version fits *root*'s ``requires-python``, else ``None``.

    The running interpreter (it imports dev_lab by running this) comes first; *others* default to
    :func:`candidates`, each probed by *version_of* (default :func:`probe`).
    """
    spec = requires_python(root)
    if fits(platform.python_version(), spec):
        return Path(sys.executable).as_posix()
    for python in candidates(root) if others is None else others:
        version = (probe if version_of is None else version_of)(python)
        if version is not None and fits(version, spec):
            return Path(python).as_posix()
    return None
