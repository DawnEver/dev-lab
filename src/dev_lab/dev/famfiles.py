"""PROJECT-FILES-HAVE-ONE-SOURCE: the single list of every project-level file, and who owns each one.

THE RULING, 2026-10-03: `.gitignore`, `Makefile`, the git hooks, `ruff.toml` "and the
rest" -- every project-level file the four repos repeat -- has ONE source of truth, here. The engines
already existed one file at a time (:mod:`dev_lab.dev.famconfig` for whole files,
:mod:`dev_lab.dev._famconfig_sections` for config TABLES, :mod:`dev_lab.dev.agent_guard` and
:mod:`dev_lab.dev.hook_adoption` for the agent hook files); what did not exist was the LIST: the
one place that says, for each file, which mechanism owns it -- or that the repo does, and why.

:data:`PROJECT_FILES` IS THAT LIST. A tracked project-level file in any repo of the family is either a
row here, or a row in the repo's own ``owned_here`` mapping with a reason; anything else is a file
drifting with nobody saying so, and :mod:`dev_lab.dev.famtests.famfiles` refuses it. ONE command,
:func:`render_all` (``python -m dev_lab.dev.famfiles``), writes every RENDERED artifact a repo
declares a delta for, so a base edit here reaches a repo by one re-render rather than one per file.

THE ONE DOOR (2026-11-13). ``python -m dev_lab.dev.famfiles`` WITHOUT ``--files`` runs every renderer due in
the repo (:func:`render_repo`) -- CI workflows, the whole files, deny rules and engine, the settings wiring, the
door rules, the dev-docs pointer table -- each with the inputs its ``[tool.dev_lab.render]`` declares; ``forge
sync``'s relock calls the same function. In a FAMILY repo (:func:`is_member`: a dev-lab dependency or any
``[tool.dev_lab.*]`` table) every renderer whose inputs are derivable is due, present files or not -- cc-market
(2026-11-13) declared only ``[tool.dev_lab.integrator]`` and the door rendered nothing while its workflows were
missing. Elsewhere a renderer is due where a file it writes is present. One that writes a PART of a repo-owned file
is due only where its input is declared. The door prints one line per renderer: rendered, or skipped and why.

THE TWO KINDS, and the line between them is the noun test the rules registry uses: a file whose
CONTENT is about the family's toolchain is managed; a file whose content is about the repo (its
license, its architecture, its release history) is owned, and the row says which noun made it so.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev._famfiles_registry import (
    CIWORKFLOWS,
    OWNED,
    PROJECT_FILES,
    RENDERERS,
    RETIRED_PROJECT_FILES,
    WORKFLOW_FILES,
    ProjectFile,
    Renderer,
    render_table,
)
from dev_lab.dev.famconfig import BASES, INSTALLED, RENDERED, ForkedDelta, artifact_base, inspect_file, render
from dev_lab.dev.repodeltas import load_deltas
from dev_lab.dev.trackedrender import Kit, RenderRefused, guard_render, interpreter_kit

if TYPE_CHECKING:
    from collections.abc import Mapping

    from dev_lab.dev.famconfig import Base, Delta

__all__ = [
    'RENDER_COMMAND',
    'delta_base',
    'due_renderers',
    'is_member',
    'main',
    'managed_sections',
    'plan',
    'render_agent_files',
    'render_all',
    'render_argv',
    'render_repo',
    'undeclared_inputs',
]

#: The one command a repo re-renders every family file with (its own deltas module named).
RENDER_COMMAND: Final = 'python -m dev_lab.dev.famfiles'


def due_renderers(root: Path) -> tuple[Renderer, ...]:
    """The renderers of :data:`RENDERERS` due in *root*: what a re-render there runs (:class:`Renderer`)."""
    return tuple(renderer for renderer, why in plan(root) if why is None)


#: Each renderer by name: what a :attr:`Renderer.needs` names.
_NAMED: Final = {renderer.name: renderer for renderer in RENDERERS}


def plan(root: Path) -> tuple[tuple[Renderer, str | None], ...]:
    """Every renderer of :data:`RENDERERS` with ``None`` when it is due in *root*, else why it is skipped.

    Due: a file it writes is present, or -- in a family repo (:func:`is_member`) -- its required inputs are all
    declared.
    """
    text = _manifest(root)
    member = is_member(text)
    present = set(_due(lambda path: (root / path).is_file()))

    def why(renderer: Renderer) -> str | None:
        if renderer in present:
            return None
        if renderer.present_only:
            return 'no file it writes is present (a repo committing Rust carries rust-toolchain.toml: lockcheck)'
        if not member:
            return 'not a family repo (no dev-lab dependency, no [tool.dev_lab.*] table) and no file it writes exists'
        if missing := renderer.missing(text):
            return renderer.why_missing(missing)
        if renderer.needs and (reason := why(_NAMED[renderer.needs])) is not None:
            return f'it needs {renderer.needs}, skipped: {reason}'
        return None

    return tuple((renderer, why(renderer)) for renderer in RENDERERS)


def _due(has: Callable[[str], bool]) -> tuple[Renderer, ...]:
    def due(row: ProjectFile) -> bool:
        if row.renderer is None:
            return False
        return has(row.path)

    present = {row.renderer for row in PROJECT_FILES.values() if due(row)}
    if any(has(path) for path in WORKFLOW_FILES):
        present.add(CIWORKFLOWS)
    return tuple(renderer for renderer in RENDERERS if renderer in present)


_DEV_LAB: Final = re.compile(r'^\s*dev[-_.]lab(?![\w.-])', re.IGNORECASE)


def is_member(text: str) -> bool:
    """Whether manifest *text* is a family repo's: it depends on dev-lab, or declares any ``[tool.dev_lab.*]`` table."""
    data = tomllib.loads(text) if text else {}
    if data.get('tool', {}).get('dev_lab'):
        return True
    project = data.get('project', {})
    lists = [project.get('dependencies', []), *project.get('optional-dependencies', {}).values()]
    lists += data.get('dependency-groups', {}).values()
    return any(isinstance(dep, str) and _DEV_LAB.match(dep) for deps in lists for dep in deps)


def _manifest(root: Path) -> str:
    manifest = root / 'pyproject.toml'
    return manifest.read_text(encoding='utf-8') if manifest.is_file() else ''


def undeclared_inputs(text: str, has: Callable[[str], bool]) -> list[str]:
    """Each required input of a renderer due in a tree that manifest *text* leaves undeclared, ``"<renderer> <key>"``.

    A renderer is DUE where a file it writes is present (``has(path)``); without its input a relock cannot
    re-render that tree's family files, and they go stale.
    """
    return [f'{r.name} {key}' for r in _due(has) for key in r.missing(text)]


def render_argv(renderer: Renderer, root: Path, python: str) -> list[str]:
    """*renderer*'s command for *root* under *python*, its inputs read from *root*'s :data:`RENDER_TABLE`.

    RAISES :class:`ValueError` naming the key when a required input is not declared.
    """
    declared = render_table(text := _manifest(root))
    if missing := renderer.missing(text):
        msg = (
            f'{renderer.name} renders files {root} holds, but {renderer.why_missing(missing)} in its '
            'pyproject.toml: declare what it reads'
        )
        raise ValueError(msg)
    argv = [python, '-m', *renderer.command, renderer.repo_flag, str(root)]
    for key, flag in renderer.inputs:
        value = declared.get(key, ())
        for item in [value] if isinstance(value, str) else value if isinstance(value, list) else ():
            argv += [flag, str(item)]
    return argv


def render_repo(
    root: Path, python: str, run: Callable[[list[str], Path], int], kit: Kit | None = None
) -> tuple[str, ...]:
    """THE ONE DOOR: run every renderer due in *root* under *python* (``run(argv, root)``).

    Answers one line per renderer of :data:`RENDERERS`, ``"<name>: rendered"`` or ``"<name>: skipped -- <why>"``.
    RAISES :class:`ValueError` naming the renderer when a declared input is missing or it exits non-zero, before
    any later renderer runs. A TRACKED file moves only under the checkout's own kit in a linked worktree
    (:mod:`dev_lab.dev.trackedrender`): *kit* is the one rendering, default the one *python* runs; otherwise every
    moved tracked file is put back and :class:`~dev_lab.dev.trackedrender.RenderRefused` names files, kit and door.
    """
    steps = [(r, why, None if why else render_argv(r, root, python)) for r, why in plan(root)]

    def render() -> tuple[str, ...]:
        for renderer, _why, argv in steps:
            if argv is not None and (exited := run(argv, root)) != 0:
                msg = f'the renderer {renderer.name} exited {exited} in {root}: {" ".join(argv[1:])}'
                raise ValueError(msg)
        return tuple(f'{r.name}: skipped -- {why}' if why else f'{r.name}: rendered' for r, why, _argv in steps)

    return guard_render(root, render, lambda: kit or interpreter_kit(python), RENDER_COMMAND)


def _run(argv: list[str], root: Path) -> int:
    return _door.run(argv, cwd=root, check=False).returncode


def delta_base(artifact: str) -> Base:
    """The base a repo's delta for *artifact* renders over, or a refusal naming why there is none and the door.

    EVERY-WALL-TEACHES (2026-11-25): famconfig's "no family base" sends a stale delta to ADD a base row, which
    for a file the family retired or hands to the repo is the wrong door. Both facts live in this module's
    tables, above famconfig, so the refusal that knows them is raised here.
    """
    if artifact in RETIRED_PROJECT_FILES:
        msg = (
            f'{artifact!r} is RETIRED from the family (dev_lab.dev._famfiles_registry.RETIRED_PROJECT_FILES): '
            f'{RETIRED_PROJECT_FILES[artifact]}. Its delta renders over nothing -- drop its row (and any constant '
            f'only it used) from the repo DELTAS module and `git rm {artifact}`.'
        )
        raise ForkedDelta(msg)
    row = PROJECT_FILES.get(artifact)
    if row is not None and row.kind == OWNED:
        msg = (
            f"{artifact!r} is the repo's OWN file, with no family base (dev_lab.dev._famfiles_registry.PROJECT_FILES: "
            f'{row.how}). Its delta renders over nothing -- drop its row (and any constant only it used) from '
            f'the repo DELTAS module; the file itself stays the repo`s.'
        )
        raise ForkedDelta(msg)
    return artifact_base(artifact)


def render_all(root: Path, deltas: Mapping[str, Delta], *, write: bool) -> tuple[str, ...]:
    """Every RENDERED base this repo declares, re-rendered into *root*; one line per artifact, what happened.

    With *write* false nothing is written and the lines say what WOULD change: the check mode.
    A delta with no base is refused by :func:`delta_base`, which names the retirement or ownership if either holds.
    """
    out: list[str] = []
    for artifact in sorted(deltas):
        base = delta_base(artifact)
        path = root / artifact
        report = inspect_file(path, base, deltas[artifact])
        if report.status == INSTALLED:
            out.append(f'{artifact}: current')
        elif base.mode != RENDERED:
            out.append(f'{artifact}: {report.status} ({base.mode}, not written) -- {report.detail}')
        elif write:
            path.write_bytes(render(base, deltas[artifact]).encode('utf-8'))
            out.append(f'{artifact}: rendered (was {report.status})')
        else:
            out.append(f'{artifact}: would render (is {report.status})')
    undeclared = sorted(set(BASES) - set(deltas))
    out += [f'{artifact}: NO DELTA DECLARED -- this repo has not adopted the family base' for artifact in undeclared]
    return tuple(out)


def managed_sections() -> tuple[tuple[str, str], ...]:
    """The family sections every repo carries inside a file of its own: (repo-relative path, the section text)."""
    from dev_lab.dev import agentsection  # noqa: PLC0415 -- the light merge job imports famfiles

    return ((agentsection.AGENTS_REL, agentsection.render_section()),)


def render_agent_files(root: Path, *, write: bool) -> tuple[str, ...]:
    """The family section of AGENTS.md, re-rendered into *root*; one line. *write* false: the check mode."""
    from dev_lab.dev import agentsection  # noqa: PLC0415 -- the light merge job imports famfiles

    return (agentsection.render_into(root, write=write),)


def main(argv: list[str] | None = None) -> int:
    """CLI. Without ``--files``/``--deltas``: THE ONE DOOR (:func:`render_repo`), exit 0 when every due renderer did.

    With ``--files`` (the famfiles renderer itself): the whole files, plus every base + delta file when ``--deltas``
    names the repo's module (no deltas: no per-file overrides, no base written); exit 0 when every one is current
    (after writing, unless --check), else 1. ``--deltas`` implies ``--files``.
    """
    parser = argparse.ArgumentParser(description='Render every family artifact a repo declares (the one door).')
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--files', action='store_true', help='only the famfiles renderer: whole + base/delta files')
    parser.add_argument('--deltas', type=Path, help='the repo DELTAS module; implies --files')
    parser.add_argument('--check', action='store_true', help='with --files: write nothing; report what would change')
    args = parser.parse_args(argv)
    root = args.repo.resolve()
    if not args.files and args.deltas is None:
        if args.check:
            parser.error('--check reads one renderer: name --files')
        try:
            lines = render_repo(root, sys.executable, _run)
        except (ValueError, RenderRefused) as exc:
            emit(f'[famfiles] REFUSED -- {exc}', err=True)
            return 1
        for line in lines:
            emit(f'[famfiles] {line}')
        return 0
    deltas = load_deltas(args.deltas.resolve()) if args.deltas is not None else None
    lines = (
        *(render_all(root, deltas, write=not args.check) if deltas is not None else ()),
        *render_agent_files(root, write=not args.check),
    )
    for line in lines:
        emit(f'[famfiles] {line}')
    settled = ('current', 'rendered')
    return 0 if all(line.split(': ', 1)[1].startswith(settled) for line in lines) else 1


if __name__ == '__main__':
    raise SystemExit(main())
