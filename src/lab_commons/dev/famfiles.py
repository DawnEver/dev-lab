"""PROJECT-FILES-HAVE-ONE-SOURCE: the single list of every project-level file, and who owns each one.

THE RULING, 2026-10-03: `.gitignore`, `Makefile`, `.pre-commit-config.yaml`, `ruff.toml` "and the
rest" -- every project-level file the four repos repeat -- has ONE source of truth, here. The engines
already existed one file at a time (:mod:`lab_commons.dev.famconfig` for whole files,
:mod:`lab_commons.dev._famconfig_sections` for config TABLES, :mod:`lab_commons.dev.agent_guard` and
:mod:`lab_commons.dev.hook_adoption` for the agent hook files); what did not exist was the LIST: the
one place that says, for each file, which mechanism owns it -- or that the repo does, and why.

:data:`PROJECT_FILES` IS THAT LIST. A tracked project-level file in any repo of the family is either a
row here, or a row in the repo's own ``owned_here`` mapping with a reason; anything else is a file
drifting with nobody saying so, and :mod:`lab_commons.dev.famtests.famfiles` refuses it. ONE command,
:func:`render_all` (``python -m lab_commons.dev.famfiles``), writes every RENDERED artefact a repo
declares a delta for, so a base edit here reaches a repo by one re-render rather than one per file.

THE TWO KINDS, and the line between them is the noun test the rules registry uses: a file whose
CONTENT is about the family's toolchain is managed; a file whose content is about the repo (its
licence, its architecture, its release history) is owned, and the row says which noun made it so.
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.dev.famconfig import BASES, INSTALLED, RENDERED, artefact_base, inspect_file, render
from lab_commons.log import emit

if TYPE_CHECKING:
    from collections.abc import Mapping

    from lab_commons.dev.famconfig import Delta

__all__ = [
    'MANAGED',
    'OWNED',
    'PROJECT_FILES',
    'ProjectFile',
    'load_deltas',
    'main',
    'project_files_on_disk',
    'render_all',
    'unaccounted',
]

#: A file whose content comes from a family mechanism named in the row.
MANAGED: Final = 'managed'
#: A file whose content is the repo's own; the row carries the reason.
OWNED: Final = 'repo-owned'


@dataclass(frozen=True, slots=True)
class ProjectFile:
    """One project-level file: managed by a named mechanism, or owned by the repo for a stated reason."""

    path: str
    kind: str
    how: str


def _m(path: str, how: str) -> ProjectFile:
    return ProjectFile(path, MANAGED, how)


def _o(path: str, why: str) -> ProjectFile:
    return ProjectFile(path, OWNED, why)


#: THE LIST. Measured 2026-10-03 over the four checkouts; the inventory and its numbers are in
#: `docs-src/dev/project-files.md`. Every famconfig base is a row BY CONSTRUCTION (see the suite), so
#: a base added there cannot be missing here.
PROJECT_FILES: Final[dict[str, ProjectFile]] = {
    row.path: row
    for row in (
        _m('.gitignore', 'famconfig RENDERED: consumer core + GITIGNORE_FAMILY_LINES, plus the repo Delta'),
        _m('.gitattributes', 'famconfig RENDERED: the shipped-shell-payload line, plus the repo Delta'),
        _m('.pre-commit-config.yaml', 'famconfig RENDERED: the hook-id core, plus the repo Delta'),
        _m('Makefile', 'famconfig REQUIRED: the target headers and the verify recipe must be present'),
        _m('ruff.toml', 'famconfig section bases RUFF_SECTIONS (or the same tables under [tool.ruff])'),
        _m('pyproject.toml', 'famconfig section bases PYPROJECT_SECTIONS; per-repo tables named in PYPROJECT_DECLINED'),
        _m('.claude/settings.json', 'agent_guard.wire_settings (the PreToolUse hook) and allow_adoption'),
        _m('.claude/hooks/deny-commands.js', 'agent_guard install: the shipped engine, byte for byte'),
        _m('.claude/hooks/deny-rules.json', 'hook_adoption.render: the deny registry plus the repo remedies'),
        _m('.github/workflows/python-verify.yml', 'THE family CI definition, hosted here and called by every repo'),
        _m('.github/workflows/ci.yml', 'a thin caller of lab-commons` python-verify.yml; the checks are `make verify`'),
        _o('LICENSE', 'the licence is the repo`s: MIT, Apache-2.0 and LGPL-3.0 are all in use, one repo has none'),
        _o('README.md', 'its subject is the repo'),
        _o(
            'AGENTS.md',
            'its subject is the repo`s architecture; shared rules are cited by ID from lab_commons.dev.rules',
        ),
        _o('CLAUDE.md', 'a pointer to AGENTS.md; the shared rule pages arrive through famtests.rulespages'),
        _o('CHANGELOG.md', 'the repo`s release history'),
    )
}


def _git_lines(root: Path, *args: str) -> tuple[str, ...]:
    done = subprocess.run(
        [shutil.which('git') or 'git', '-C', str(root), *args],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=60,
    )
    if done.returncode != 0:
        msg = f'git {" ".join(args)} failed in {root}: {done.stderr.strip()}'
        raise RuntimeError(msg)
    return tuple(line for line in done.stdout.splitlines() if line)


def project_files_on_disk(root: Path) -> tuple[str, ...]:
    """The tracked project-level files of *root*: every top-level FILE, plus the registry's nested paths."""
    tracked = _git_lines(root, 'ls-files')
    nested = {path for path in PROJECT_FILES if '/' in path}
    return tuple(sorted(path for path in tracked if '/' not in path or path in nested or _is_workflow(path)))


_WORKFLOWS: Final = '.github/workflows/'


def _is_workflow(path: str) -> bool:
    return path.startswith(_WORKFLOWS) and '/' not in path[len(_WORKFLOWS) :]


def unaccounted(root: Path, owned_here: Mapping[str, str]) -> tuple[str, ...]:
    """Project-level files in *root* that neither the family list nor the repo's own *owned_here* names."""
    return tuple(path for path in project_files_on_disk(root) if path not in PROJECT_FILES and path not in owned_here)


def load_deltas(path: Path) -> Mapping[str, Delta]:
    """The ``DELTAS`` mapping a repo declares, read from the module file at *path* (its own convention)."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        msg = f'cannot load a module from {path}'
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(path.stem, module)
    spec.loader.exec_module(module)
    return module.DELTAS


def render_all(root: Path, deltas: Mapping[str, Delta], *, write: bool) -> tuple[str, ...]:
    """Every RENDERED base this repo declares, re-rendered into *root*; one line per artefact, what happened.

    A REQUIRED base (the Makefile) is NOT written -- it is presence-only, and rendering it would clobber
    the recipes that are the repo's own. Its status is reported, so one command still answers for all.
    With *write* false nothing is written and the lines say what WOULD change: the check mode.
    """
    out: list[str] = []
    for artefact in sorted(deltas):
        base = artefact_base(artefact)
        path = root / artefact
        report = inspect_file(path, base, deltas[artefact])
        if report.status == INSTALLED:
            out.append(f'{artefact}: current')
        elif base.mode != RENDERED:
            out.append(f'{artefact}: {report.status} ({base.mode}, not written) -- {report.detail}')
        elif write:
            path.write_text(render(base, deltas[artefact]), encoding='utf-8')
            out.append(f'{artefact}: rendered (was {report.status})')
        else:
            out.append(f'{artefact}: would render (is {report.status})')
    undeclared = sorted(set(BASES) - set(deltas))
    out += [f'{artefact}: NO DELTA DECLARED -- this repo has not adopted the family base' for artefact in undeclared]
    return tuple(out)


def main(argv: list[str] | None = None) -> int:
    """CLI. Exit 0 when every declared artefact is current (after writing, unless --check), else 1."""
    parser = argparse.ArgumentParser(description='Render every family-managed project file from base + delta.')
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--deltas', type=Path, required=True, help='the module file holding this repo`s DELTAS')
    parser.add_argument('--check', action='store_true', help='write nothing; report what would change')
    args = parser.parse_args(argv)
    root = args.repo.resolve()
    lines = render_all(root, load_deltas(args.deltas.resolve()), write=not args.check)
    for line in lines:
        emit(f'[famfiles] {line}')
    settled = ('current', 'rendered')
    return 0 if all(line.split(': ', 1)[1].startswith(settled) for line in lines) else 1


if __name__ == '__main__':
    raise SystemExit(main())
