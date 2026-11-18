"""ON-DEMAND EXTRAS (D78): a part's needs name the extras its tests import; a missing one is refused with its door.

A worktree's environment holds the base dependencies and the extras the repo DECLARES
(``[tool.dev_lab.dep] extras``); nothing else is installed by default (:func:`dev_lab.dev._dep_project.read_project`).
A test that needs more says so by its resource marker -- the need-set its part is named for
(:mod:`lab_commons.hpc.needsets`) -- and the repo maps a need to the extra that serves it, once, beside its extras::

    [tool.dev_lab.dep]
    extras = ["dev"]
    needs = { simba = "simba" }

``verify --part <part>`` asks :func:`missing_for_part` before it runs: every need of the part that maps to an
extra whose requirements are not installed in this interpreter refuses the run BY NAME, with the exact sync that
adds it -- the declared extras plus the missing one, because an explicit ``--extra`` list narrows the sync.
Refusing (not installing) keeps every environment change behind the one ``dep`` door.

LIMITS, STATED: a requirement carrying an environment marker is not judged (this module evaluates no markers), so
it never makes an extra look missing; a targeted selection with no ``--part`` carries no need-set before
collection and is not checked.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable, Mapping
from importlib import metadata
from pathlib import Path
from typing import Final

from lab_commons.hpc.needsets import BASE

#: A requirement's distribution name: the leading identifier, before extras, versions, URLs or markers.
_NAME: Final = re.compile(r'\s*([A-Za-z0-9][A-Za-z0-9._-]*)')


def _installed(name: str) -> bool:
    try:
        metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return False
    return True


def _table(root: Path) -> tuple[Mapping[str, object], Mapping[str, list[str]]]:
    manifest = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    dep = manifest.get('tool', {}).get('dev_lab', {}).get('dep', {})
    return dep, manifest.get('project', {}).get('optional-dependencies', {})


def declared_needs(root: Path) -> dict[str, str]:
    """``[tool.dev_lab.dep] needs``: need -> extra, each extra a declared one, else :class:`ValueError` by name."""
    dep, available = _table(root)
    needs = dep.get('needs', {})
    if not isinstance(needs, dict) or any(not isinstance(v, str) for v in needs.values()):
        msg = 'tool.dev_lab.dep.needs must be a table of need = "<extra>"'
        raise ValueError(msg)
    for need, extra in needs.items():
        if extra not in available:
            msg = f'tool.dev_lab.dep.needs: {need} -> {extra!r} is no declared extra ({sorted(available)})'
            raise ValueError(msg)
    return dict(needs)


def missing_for_part(root: Path, part: str, *, installed: Callable[[str], bool] = _installed) -> str | None:
    """The refusal naming the sync door when *part*'s needs map to an extra not installed here, else ``None``."""
    needs = declared_needs(root)
    dep, available = _table(root)
    wanted = [needs[need] for need in part.split('+') if need and need != BASE and need in needs]
    missing = [
        extra for extra in dict.fromkeys(wanted) if not all(installed(name) for name in _names(available[extra]))
    ]
    if not missing:
        return None
    declared = [str(e) for e in dep.get('extras', ())]
    flags = ' '.join(f'--extra {extra}' for extra in dict.fromkeys([*declared, *missing]))
    need_list = ', '.join(repr(extra) for extra in missing)
    return (
        f'verify: refused -- part {part} needs extra {need_list}, not installed in this environment '
        f'(D78: extras are installed on demand); add it: python -m dev_lab.dev.dep --sync {root} {flags}'
    )


#: The frontmatter line a task record declares its needs on: ``needs: [simba, windows]`` (D79).
_NEEDS_LINE: Final = re.compile(r'^needs:\s*(.*?)\s*$', re.MULTILINE)
_NEED: Final = re.compile(r'[a-z0-9][a-z0-9_-]*')
#: The line that closes a frontmatter block.
_FENCE: Final = '\n---'


def task_needs(ledger: Path, task: str) -> tuple[str, ...]:
    """The needs the task record ``<ledger>/<slug>/TASK.md`` declares in its frontmatter (D79), else ``()``.

    A TASK DECLARES THE NEEDS ITS WORK EXERCISES -- the same need names its tests' resource markers carry -- never
    an extra: which extra serves a need is the REPO's fact (:func:`declared_needs`), stated once. A line that is no
    ``[a, b]`` list of need names is refused by name, so a typo never silently installs nothing.
    """
    record = Path(ledger) / task.split('@', 1)[0] / 'TASK.md'
    text = record.read_text(encoding='utf-8') if record.is_file() else ''
    front = text[3:].partition(_FENCE)[0] if text.startswith('---') else ''
    found = _NEEDS_LINE.search(front)
    if found is None:
        return ()
    value = found.group(1)
    names = [part.strip() for part in value.strip('[]').split(',')] if value.startswith('[') else None
    if names is None or not value.endswith(']') or any(not _NEED.fullmatch(name) for name in names if name):
        msg = f'{record}: needs must be a list of need names, e.g. needs: [simba, windows] -- got {value!r}'
        raise ValueError(msg)
    return tuple(name for name in names if name)


def extras_for(root: Path, needs: tuple[str, ...]) -> tuple[str, ...]:
    """The extras a sync selects for *needs*: the repo's declared extras plus every extra a need maps to, in order.

    A need the repo maps to no extra (a platform, an external tool) installs nothing.
    """
    dep, _available = _table(root)
    mapped = declared_needs(root)
    return tuple(dict.fromkeys([*(str(e) for e in dep.get('extras', ())), *(mapped[n] for n in needs if n in mapped)]))


def _names(requirements: list[str]) -> list[str]:
    """Distribution names of *requirements*, skipping any with an environment marker (not evaluated here)."""
    return [m.group(1) for req in requirements if ';' not in req and (m := _NAME.match(req))]
