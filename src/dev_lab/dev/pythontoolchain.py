"""THE FAMILY PYTHON (user ruling 2026-11-27, dev-lab #1045): ONE interpreter, declared here, followed everywhere.

:data:`VERSION` is the one declaration; nothing else in the family types the number. What derives from it:

* a repo's ``[project] requires-python`` (:data:`REQUIRES_PYTHON`) and ``[tool.ruff] target-version``
  (:data:`RUFF_TARGET`), rendered into its ``pyproject.toml`` by this module -- the one door
  (``python -m dev_lab.dev.famfiles``) runs it -- and judged by :func:`drift`;
* every venv ``dep --bootstrap`` builds: it builds under the target's ``requires-python``, which only this
  interpreter fits (:func:`dev_lab.dev._dep_project.bootstrap_python`);
* every ``uv sync`` a rendered CI workflow runs (``ci_base.toml``'s ``@python@``, :data:`SYNC_FLAGS`): a uv-managed
  interpreter on every runner, never the runner's own;
* the interpreter a rendered wheels workflow builds and smoke-imports on (:mod:`dev_lab.dev.nativewheels`);
* a cluster deployment's default interpreter (:data:`dev_lab.dev.hpcaccount.spec.DEFAULT_PYTHON`).

WHY ``requires-python`` CARRIES A CEILING (``>=3.14,<3.15``). The family runs ONE minor, so the ceiling is the
ruling itself, not a resolver accident inherited by four trees. MEASURED 2026-11-27: with ``>=3.12`` uv picked the
newest interpreter installed (3.15.2 on a workstation, Homebrew 3.15 on the macOS runner, 3.13 on the Windows one),
so the floor alone let every host choose its own. With the ceiling, every plain ``uv sync``/``uv run`` in a family
tree selects this interpreter (fetching it when absent), and a lock resolves only this minor's wheels. Moving the
family is one edit to :data:`VERSION`, then a relock and a re-render in each repo.

``python -m dev_lab.dev.pythontoolchain render|check [--repo PATH]``
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Final, cast

from lab_commons.log import emit

from dev_lab.dev.ciworkflowshape import WORKFLOW_DIRS
from dev_lab.dev.famconfig import OWNED, SectionBase, SectionDelta, inspect_section
from dev_lab.dev.sectionrender import render_section

__all__ = [
    'MANIFEST',
    'RENDER_COMMAND',
    'REQUIRES_PYTHON',
    'RUFF_TARGET',
    'SECTIONS',
    'SYNC_FLAGS',
    'VERSION',
    'drift',
    'main',
    'minor_check',
    'unpinned_syncs',
    'write',
]

#: THE family interpreter, as ``<major>.<minor>``: the one place the number is typed.
VERSION: Final = '3.14'

_MAJOR, _MINOR = (int(part) for part in VERSION.split('.'))
#: ``[project] requires-python``: this minor and no other (the ceiling is the ruling; see the module docstring).
REQUIRES_PYTHON: Final = f'>={VERSION},<{_MAJOR}.{_MINOR + 1}'
#: ``[tool.ruff] target-version``: the syntax ruff may assume is this interpreter's.
RUFF_TARGET: Final = f'py{_MAJOR}{_MINOR}'
#: What every rendered ``uv sync`` carries: this interpreter, uv-managed -- never the runner's own.
SYNC_FLAGS: Final = f'--python {VERSION} --managed-python'

#: The file both keys live in (ruff's dedicated files are retired: ``_famfiles_registry.RETIRED_PROJECT_FILES``).
MANIFEST: Final = 'pyproject.toml'
#: The two keys this fact owns, each a one-scalar section the family writer renders and the section reader judges.
SECTIONS: Final[tuple[SectionBase, ...]] = (
    SectionBase('[project]', ('project',), (), {'requires-python': REQUIRES_PYTHON}, {}),
    SectionBase('[tool.ruff]', ('tool', 'ruff'), ('tool', 'ruff'), {'target-version': RUFF_TARGET}, {}),
)
RENDER_COMMAND: Final = 'python -m dev_lab.dev.pythontoolchain render'

_NO_DELTA: Final = SectionDelta(repo='family', added={}, dropped={}, ceiling=0)
_RENDERED_BY: Final = '# Rendered by '


def minor_check(want: str) -> str:
    """A ``python -c`` program exiting 0 on Python *want* (``<major>.<minor>``), else 1 naming both and the door.

    Written for any Python 3: it runs on the very interpreter that may be too old for the kit's code.
    """
    return (
        "import sys; have = '%d.%d' % sys.version_info[:2]; "
        f"sys.exit(0 if have == '{want}' else 'KIT-PYTHON-MINOR: the kit venv runs Python ' + have + "
        f"', the kit requires {want}: deploy-fleet --account <this account> (dev_lab.dev.hpcaccount) rebuilds it "
        "in a Slurm job')"
    )


def unpinned_syncs(workflow: object) -> list[str]:
    """Every ``uv sync`` command line in *workflow* (a rendered workflow's data) lacking :data:`SYNC_FLAGS`."""
    if isinstance(workflow, str):
        return [line for line in workflow.splitlines() if 'uv sync' in line and SYNC_FLAGS not in line]
    values: Iterable[object] = ()
    if isinstance(workflow, Mapping):
        values = cast('Mapping[object, object]', workflow).values()
    elif isinstance(workflow, list):
        values = cast('list[object]', workflow)
    return [line for value in values for line in unpinned_syncs(value)]


def _rendered_workflows(root: Path) -> dict[Path, object]:
    """Every rendered workflow file under *root*'s forge directories, parsed (a stamp line, then JSON)."""
    found: dict[Path, object] = {}
    for directory in WORKFLOW_DIRS.values():
        if (root / directory).is_dir():
            for path in sorted((root / directory).glob('*.yml')):
                stamp, _, body = path.read_text(encoding='utf-8').partition('\n')
                if stamp.startswith(_RENDERED_BY):
                    found[path] = json.loads(body)
    return found


def drift(root: Path) -> list[str]:
    """Every place *root* declares or renders a Python other than the family's, each with its door; ``[]`` when none."""
    out: list[str] = []
    for base in SECTIONS:
        report = inspect_section(root / MANIFEST, base, _NO_DELTA)
        if report.status != OWNED:
            said = '; '.join(report.offending) or report.detail
            out.append(f'{MANIFEST} {base.artifact}: {said} -- {RENDER_COMMAND}')
    for path, workflow in _rendered_workflows(root).items():
        out += [
            f'{path.relative_to(root).as_posix()}: `{line.strip()}` syncs without `{SYNC_FLAGS}` -- the family '
            f'Python reaches a workflow through ci_base.toml; drop the override, then `python -m dev_lab.dev.famfiles`'
            for line in unpinned_syncs(workflow)
        ]
    return out


def write(root: Path) -> str:
    """Render the family Python's keys into *root*'s manifest; one status line. Every other key stays the repo's."""
    path = root / MANIFEST
    if not path.is_file():
        msg = f'{path}: no manifest to render the family Python into'
        raise FileNotFoundError(msg)
    if all(inspect_section(path, base, _NO_DELTA).status == OWNED for base in SECTIONS):
        return f'{MANIFEST}: current'
    for base in SECTIONS:
        render_section(path, base)
    return f'{MANIFEST}: rendered'


def main(argv: list[str] | None = None) -> int:
    """CLI: ``render`` writes the manifest's keys; ``check`` exits 1 naming every drift (manifest and workflows)."""
    parser = argparse.ArgumentParser(
        prog='python -m dev_lab.dev.pythontoolchain', description=(__doc__ or '').splitlines()[0]
    )
    parser.add_argument('action', choices=('render', 'check'))
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    root = args.repo.resolve()
    if args.action == 'render':
        emit(f'[pythontoolchain] {write(root)}')
        return 0
    found = drift(root)
    for line in found:
        emit(f'[pythontoolchain] {line}')
    if not found:
        emit(f'[pythontoolchain] {MANIFEST} and every rendered workflow run Python {VERSION}')
    return 1 if found else 0


if __name__ == '__main__':
    raise SystemExit(main())
