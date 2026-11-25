"""TYPES-RATCHET: pyright over a repo's ``[tool.pyright]``, its error counts per owner a ratchet that only falls.

User ruling (consumer v1 ledger D107): type checking is a family mechanism. The family base is the
``[tool.pyright]`` section dev-lab owns (:data:`dev_lab.dev._famconfig_pyproject_rows.PYRIGHT`: ``src`` strict,
``tests`` basic); ``verify`` runs this module as a lint step (:data:`dev_lab.dev.verifysteps.LINT_STEPS`).

THE RATCHET is ``[tool.dev_lab.typecheck] errors = { <owner> = <count> }`` in the repo's ``pyproject.toml``. An
owner is the child package of the repo's package a file lies in (``src/<package>/<owner>/...``, the OWNER-DAG
owners), a module directly in the package counting as the package's own name, and any other file its top
directory (``tests``, ``scripts``). Both sides refuse: a count ABOVE the record is a regression; a count BELOW it
is a floor that must come down to what was measured, so the record never sits above a measurement and can only
fall. An owner measured and unrecorded, or recorded and measured at zero, is refused the same way.

A repo with no ``[tool.pyright]`` is not judged and says so: whether it must adopt the base is
``famtests.configrender.assert_every_section_is_owned``'s (a pending section is named there).

Astral's ``ty`` is a documented future option (docs-src/dev/refusals.md#types-ratchet), not adopted: one checker
judges.

Exit codes follow :func:`dev_lab.dev.reports.read_lint`: ``0`` clean, ``1`` refused (printed), ``2`` pyright did
not run. ``--write`` records the measured counts -- an owner's first count, or a lower one after a fix; it refuses
to raise a recorded count, so the record only falls.
"""

from __future__ import annotations

import argparse
import json
import sys
import sysconfig
import tomllib
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import IO, TYPE_CHECKING, Final

import lab_commons.launch as _door
import tomlkit

from dev_lab.dev.family import declared_table
from dev_lab.dev.ownerdag import python_tree

if TYPE_CHECKING:
    from collections.abc import Mapping

    from dev_lab.dev.ownerdag import PythonTree

__all__ = [
    'CLEAN',
    'ERRORED',
    'FOUND',
    'INSTALL_DOOR',
    'RULE_ID',
    'binary',
    'check',
    'counts',
    'main',
    'owner',
    'problems',
]

RULE_ID: Final = 'TYPES-RATCHET'
CLEAN: Final = 0
FOUND: Final = 1
ERRORED: Final = 2

#: What a missing checker is fixed by: pyright ships in the ``dev-lab[test]`` kit.
INSTALL_DOOR: Final = 'python -m dev_lab.dev.dep --sync (pyright ships in the dev-lab[test] extra)'
_DOOR: Final = (
    'fix the type errors, then record the lower count with `python -m dev_lab.dev.typecheck --write`; '
    'a count may never be raised by hand'
)
_DETAILS: Final = 'details: docs-src/dev/refusals.md#types-ratchet (dev-lab)'


def binary() -> Path | None:
    """The pyright installed in THIS interpreter's environment, so the checker is the locked one."""
    name = 'pyright.exe' if sys.platform == 'win32' else 'pyright'
    path = Path(sysconfig.get_path('scripts')) / name
    return path if path.is_file() else None


def owner(tree: PythonTree | None, rel: str) -> str:
    """The owner a repo-relative POSIX path counts against (see the module docstring)."""
    parts = PurePosixPath(rel).parts
    if tree is not None:
        base = PurePosixPath(tree.directory).parts
        if parts[: len(base)] == base and len(parts) > len(base):
            return parts[len(base)] if len(parts) > len(base) + 1 else tree.package
    return parts[0]


def counts(report: Mapping[str, object], root: Path, tree: PythonTree | None) -> dict[str, int]:
    """Error counts per owner from pyright's ``--outputjson`` *report* (warnings and information do not count)."""
    found: Counter[str] = Counter()
    diagnostics = report.get('generalDiagnostics', [])
    for item in diagnostics if isinstance(diagnostics, list) else []:
        if isinstance(item, dict) and item.get('severity') == 'error':
            path = Path(str(item.get('file', '')))
            rel = path.resolve().relative_to(root.resolve()).as_posix() if path.is_absolute() else path.as_posix()
            found[owner(tree, rel)] += 1
    return dict(sorted(found.items()))


def problems(measured: Mapping[str, int], recorded: Mapping[str, int]) -> list[str]:
    """Every way *measured* is not exactly *recorded*: a rise, a floor left above its measurement, a stray owner."""
    out: list[str] = []
    for name in sorted(set(measured) | set(recorded)):
        now, floor = measured.get(name, 0), recorded.get(name)
        if floor is None:
            out.append(f'{name}: {now} type error(s), and [tool.dev_lab.typecheck] errors records no {name}')
        elif now > floor:
            out.append(f'{name}: {now} type error(s), above its recorded {floor} -- a regression of {now - floor}')
        elif now < floor:
            out.append(
                f'{name}: {now} type error(s), below its recorded {floor} -- lower the record to {now}'
                + (' (delete the entry)' if now == 0 else '')
            )
    return out


def _recorded(root: Path) -> tuple[bool, dict[str, int]]:
    """Whether *root* adopts the base (a ``[tool.pyright]`` table), and its recorded counts."""
    path = root / 'pyproject.toml'
    data = tomllib.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    errors = declared_table(data, 'typecheck', {}).get('errors', {})
    if not isinstance(errors, dict) or not all(isinstance(v, int) and v >= 0 for v in errors.values()):
        msg = f'[tool.dev_lab.typecheck] errors must map owner -> a count >= 0, not {errors!r}'
        raise ValueError(msg)
    return 'pyright' in data.get('tool', {}), {str(k): int(v) for k, v in errors.items()}


def _measure(root: Path, pyright: Path) -> dict[str, object]:
    done = _door.run(
        [str(pyright), '--outputjson', '--pythonpath', sys.executable],
        cwd=root,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
        timeout=1200,
    )
    report = json.loads(done.stdout)
    if not isinstance(report, dict):
        raise TypeError(done.stdout[:200])
    return report


def _write(root: Path, measured: Mapping[str, int]) -> None:
    path = root / 'pyproject.toml'
    document = tomlkit.parse(path.read_text(encoding='utf-8'))
    tool = document.setdefault('tool', tomlkit.table(is_super_table=True))
    lab = tool.setdefault('dev_lab', tomlkit.table(is_super_table=True))
    table = lab.setdefault('typecheck', tomlkit.table())
    inline = tomlkit.inline_table()
    inline.update({name: count for name, count in measured.items() if count})
    table['errors'] = inline
    path.write_text(tomlkit.dumps(document), encoding='utf-8', newline='')


def _measured(root: Path, handle: IO[str]) -> tuple[dict[str, int], dict[str, int]] | int:
    """``(measured, recorded)``, or the exit code when there is nothing to judge (not adopted, or not run)."""
    try:
        adopted, recorded = _recorded(root)
    except (OSError, ValueError) as exc:
        handle.write(f'{RULE_ID}: {exc}\n')
        return ERRORED
    if not adopted:
        handle.write(f'{RULE_ID}: {root.name} declares no [tool.pyright], so its types are not judged\n')
        return CLEAN
    pyright = binary()
    if pyright is None:
        handle.write(f'pyright is not installed in {sys.prefix}: {INSTALL_DOOR}\n')
        return ERRORED
    try:
        report = _measure(root, pyright)
    except (ValueError, TypeError) as exc:
        handle.write(f'{RULE_ID}: pyright gave no JSON report ({exc})\n')
        return ERRORED
    return counts(report, root, python_tree(root)), recorded


def check(root: Path, *, handle: IO[str], write: bool = False) -> int:
    """Run pyright over *root* and judge its counts against the record; ``CLEAN``, ``FOUND`` or ``ERRORED``."""
    reading = _measured(root, handle)
    if isinstance(reading, int):
        return reading
    measured, recorded = reading
    if write:
        risen = [f'{n}: {c} > {recorded[n]}' for n, c in measured.items() if n in recorded and c > recorded[n]]
        if not risen:
            _write(root, measured)
        handle.write(
            f'{RULE_ID}: --write never raises a recorded count: {", ".join(risen)}\n'
            if risen
            else f'{RULE_ID}: recorded {measured}\n'
        )
        return FOUND if risen else CLEAN
    found = problems(measured, recorded)
    lines = [f'{RULE_ID}: {len(found)} refusal(s)', *found, f'door: {_DOOR}', _DETAILS] if found else []
    handle.write('\n'.join(lines or [f'{RULE_ID}: {sum(measured.values())} type error(s), every owner at its record']))
    handle.write('\n')
    return FOUND if found else CLEAN


def main(argv: list[str] | None = None) -> int:
    """Judge the tree at the working directory; ``--write`` records the measured counts instead."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.typecheck', description=__doc__.splitlines()[0])
    parser.add_argument('--write', action='store_true', help='record the measured counts in pyproject.toml')
    parsed = parser.parse_args(argv)
    return check(Path.cwd(), handle=sys.stdout, write=parsed.write)


if __name__ == '__main__':
    raise SystemExit(main())
