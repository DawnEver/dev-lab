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
:func:`render_all` (``python -m dev_lab.dev.famfiles``), writes every RENDERED artefact a repo
declares a delta for, so a base edit here reaches a repo by one re-render rather than one per file.

THE TWO KINDS, and the line between them is the noun test the rules registry uses: a file whose
CONTENT is about the family's toolchain is managed; a file whose content is about the repo (its
licence, its architecture, its release history) is owned, and the row says which noun made it so.
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev import principles, remconfig
from dev_lab.dev.famconfig import BASES, INSTALLED, RENDERED, artefact_base, inspect_file, render

if TYPE_CHECKING:
    from collections.abc import Mapping

    from dev_lab.dev.famconfig import Delta

__all__ = [
    'GENERATED',
    'MANAGED',
    'OWNED',
    'PROJECT_FILES',
    'RENDERERS',
    'RENDER_COMMAND',
    'RENDER_TABLE',
    'ProjectFile',
    'Renderer',
    'due_renderers',
    'load_deltas',
    'main',
    'project_files_on_disk',
    'render_agent_files',
    'render_all',
    'render_argv',
    'unaccounted',
    'undeclared_inputs',
]

#: The one command a repo re-renders every family file with (its own deltas module named).
RENDER_COMMAND: Final = 'python -m dev_lab.dev.famfiles --deltas <the repo`s deltas module>'

#: A file whose content comes from a family mechanism named in the row.
MANAGED: Final = 'managed'
#: A file whose content is the repo's own; the row carries the reason.
OWNED: Final = 'repo-owned'


#: The repo's ``pyproject.toml`` table holding what a renderer reads from the repo (its deltas module, ...).
RENDER_TABLE: Final = 'tool.dev_lab.render'


@dataclass(frozen=True, slots=True)
class Renderer:
    """A family command writing generated files: ``<tree python> -m <command> <repo_flag> <tree> <inputs>``.

    *inputs* maps a key of the repo's :data:`RENDER_TABLE` to the flag it is passed as -- a list value repeats
    the flag -- and *required* names the keys without which the command cannot run.
    """

    name: str
    command: tuple[str, ...]
    repo_flag: str = '--repo'
    inputs: tuple[tuple[str, str], ...] = ()
    required: frozenset[str] = frozenset()


FAMFILES: Final = Renderer(
    'famfiles', ('dev_lab.dev.famfiles',), inputs=(('deltas', '--deltas'),), required=frozenset({'deltas'})
)
AGENT_GUARD: Final = Renderer('agent_guard', ('dev_lab.dev.agent_guard', '--install'))
HOOK_ADOPTION: Final = Renderer(
    'hook_adoption', ('dev_lab.dev.hook_adoption',), inputs=(('adoption', '--adoption'),),
    required=frozenset({'adoption'}),
)  # fmt: skip
CIWORKFLOWS: Final = Renderer('ciworkflows', ('dev_lab.dev.ciworkflows', 'render'), repo_flag='--root')
AUTODOORS: Final = Renderer(
    'autodoors', ('dev_lab.dev.autodoors', '--write'), inputs=(('shell_doors', '--shell-door'),)
)


@dataclass(frozen=True, slots=True)
class ProjectFile:
    """One project-level file: managed by a named mechanism, or owned by the repo for a stated reason."""

    path: str
    kind: str
    how: str
    generated: bool = False  # the mechanism writes the WHOLE file: a reviewer reads the generator, not this
    renderer: Renderer | None = None  # the command writing it, re-run after every relock (forge sync)


def _m(path: str, how: str) -> ProjectFile:
    return ProjectFile(path, MANAGED, how)


def _g(path: str, how: str, renderer: Renderer | None) -> ProjectFile:
    return ProjectFile(path, MANAGED, how, generated=True, renderer=renderer)


def _o(path: str, why: str) -> ProjectFile:
    return ProjectFile(path, OWNED, why)


#: THE LIST. Measured 2026-10-03 over the four checkouts; the inventory and its numbers are in
#: `docs-src/dev/project-files.md`. Every famconfig base is a row BY CONSTRUCTION (see the suite), so
#: a base added there cannot be missing here.
PROJECT_FILES: Final[dict[str, ProjectFile]] = {
    row.path: row
    for row in (
        _g('.gitignore', 'famconfig RENDERED: consumer core + GITIGNORE_FAMILY_LINES, plus the repo Delta', FAMFILES),
        _g('.gitattributes', 'famconfig RENDERED: the shipped-shell-payload line, plus the repo Delta', FAMFILES),
        _g('.rgignore', 'famconfig RENDERED: what ripgrep and Grep skip (attic/), plus the repo Delta', FAMFILES),
        _m('Makefile', 'famconfig REQUIRED: the target headers and the verify recipe must be present'),
        _m('ruff.toml', 'famconfig section bases RUFF_SECTIONS (or the same tables under [tool.ruff])'),
        _m('pyproject.toml', 'famconfig section bases PYPROJECT_SECTIONS; per-repo tables named in PYPROJECT_DECLINED'),
        _m('.claude/settings.json', 'agent_guard.wire_settings (the guard and stray hooks) and allow_adoption'),
        _g('.claude/hooks/deny-commands.js', 'agent_guard install: the shipped engine, byte for byte', AGENT_GUARD),
        _g('.claude/rules/principles.md', 'principles.render via famfiles: the family principles', FAMFILES),
        _g('.claude/rem.json', 'remconfig.render via famfiles: the backlog is the issue tracker', FAMFILES),
        _g('.claude/hooks/deny-rules.json', 'hook_adoption: the deny registry plus the repo remedies', HOOK_ADOPTION),
        _g('.codex/rules/family-doors.rules', 'autodoors --write: the family doors plus the repo`s', AUTODOORS),
        _g('.github/workflows/ci.yml', 'ciworkflows RENDERED: ci_base.toml + [tool.dev_lab.ci]', CIWORKFLOWS),
        _g('.github/workflows/review-again.yml', 'ciworkflows RENDERED: ci_base.toml + [tool.dev_lab.ci]', CIWORKFLOWS),
        _g('.github/workflows/merge-tick.yml', 'ciworkflows RENDERED: ci_base.toml + [tool.dev_lab.ci]', CIWORKFLOWS),
        _g('.github/workflows/continue.yml', 'ciworkflows RENDERED: ci_base.toml + [tool.dev_lab.ci]', CIWORKFLOWS),
        _g('uv.lock', 'famtests.lockpin pins it; forge relock and forge sync freshen it (PIN + FRESHNESS)', None),
        _o('LICENSE', 'the licence is the repo`s: MIT, Apache-2.0 and LGPL-3.0 are all in use, one repo has none'),
        _o('README.md', 'its subject is the repo'),
        _o(
            'AGENTS.md',
            'its subject is the repo`s architecture; shared rules are cited by ID from dev_lab.dev.rules',
        ),
        _o('CLAUDE.md', 'a pointer to AGENTS.md; the shared rule pages arrive through famtests.rulespages'),
        _o('CHANGELOG.md', 'the repo`s release history'),
    )
}

#: Every family file a mechanism writes whole: what a PR review never reads (:mod:`dev_lab.dev.forgereview_scope`).
GENERATED: Final = frozenset(row.path for row in PROJECT_FILES.values() if row.generated)

#: Every renderer, read off :data:`PROJECT_FILES` in row order: the one list a relock re-runs (user ruling
#: 2026-11-07: a relock that moved dev-lab left every generated file stale and the consumer red). NOT here:
#: ``automode write``, whose file is machine-local and never committed, and the lock, which is the door's.
RENDERERS: Final = tuple(dict.fromkeys(row.renderer for row in PROJECT_FILES.values() if row.renderer))


def due_renderers(root: Path) -> tuple[Renderer, ...]:
    """The renderers of :data:`RENDERERS` writing a file present in *root*: what a re-render there runs."""
    return _due(lambda path: (root / path).is_file())


def _due(has: Callable[[str], bool]) -> tuple[Renderer, ...]:
    present = {row.renderer for row in PROJECT_FILES.values() if row.renderer and has(row.path)}
    return tuple(renderer for renderer in RENDERERS if renderer in present)


def _render_table(text: str) -> dict[str, object]:
    table: object = tomllib.loads(text) if text else {}
    for part in RENDER_TABLE.split('.'):
        table = table.get(part, {}) if isinstance(table, dict) else {}
    return table if isinstance(table, dict) else {}


def undeclared_inputs(text: str, has: Callable[[str], bool]) -> list[str]:
    """Each required input of a renderer due in a tree that manifest *text* leaves undeclared, ``"<renderer> <key>"``.

    A renderer is DUE where a file it writes is present (``has(path)``); without its input a relock cannot
    re-render that tree's family files, and they go stale.
    """
    declared = _render_table(text)
    return [f'{r.name} {key}' for r in _due(has) for key in sorted(r.required - set(declared))]


def render_argv(renderer: Renderer, root: Path, python: str) -> list[str]:
    """*renderer*'s command for *root* under *python*, its inputs read from *root*'s :data:`RENDER_TABLE`.

    RAISES :class:`ValueError` naming the key when a required input is not declared.
    """
    manifest = root / 'pyproject.toml'
    declared = _render_table(manifest.read_text(encoding='utf-8') if manifest.is_file() else '')
    if missing := sorted(renderer.required - set(declared)):
        msg = (
            f'{renderer.name} renders files {root} holds, but [{RENDER_TABLE}] {", ".join(missing)} is not '
            'declared in its pyproject.toml: declare the path it reads'
        )
        raise ValueError(msg)
    argv = [python, '-m', *renderer.command, renderer.repo_flag, str(root)]
    for key, flag in renderer.inputs:
        value = declared.get(key, ())
        for item in [value] if isinstance(value, str) else value if isinstance(value, list) else ():
            argv += [flag, str(item)]
    return argv


def _git_lines(root: Path, *args: str) -> tuple[str, ...]:
    done = _door.run(
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
            path.write_bytes(render(base, deltas[artefact]).encode('utf-8'))
            out.append(f'{artefact}: rendered (was {report.status})')
        else:
            out.append(f'{artefact}: would render (is {report.status})')
    undeclared = sorted(set(BASES) - set(deltas))
    out += [f'{artefact}: NO DELTA DECLARED -- this repo has not adopted the family base' for artefact in undeclared]
    return tuple(out)


#: The family files every repo carries whole, with no delta: (repo-relative path, its text).
def _whole_files() -> tuple[tuple[str, str], ...]:
    return ((principles.PAGE_REL, principles.render()), (remconfig.REL, remconfig.render()))


def render_agent_files(root: Path, *, write: bool) -> tuple[str, ...]:
    """The family files with no delta, re-rendered into *root*; one line per file. *write* false: the check mode.

    ``.claude/rem.json`` that differs is the repo's own choice and is reported, never overwritten.
    """
    out: list[str] = []
    for rel, text in _whole_files():
        path = root / rel
        held = path.read_text(encoding='utf-8') if path.is_file() else None
        if held == text:
            out.append(f'{rel}: current')
        elif rel == remconfig.REL and held is not None:
            out.append(f'{rel}: the repo`s own choice, not written -- reconcile it with {text.strip()} by hand')
        elif write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8', newline='\n')
            out.append(f'{rel}: rendered')
        else:
            out.append(f'{rel}: would render ({"absent" if held is None else "drifted"})')
    return tuple(out)


def main(argv: list[str] | None = None) -> int:
    """CLI. Exit 0 when every declared artefact is current (after writing, unless --check), else 1."""
    parser = argparse.ArgumentParser(description='Render every family-managed project file from base + delta.')
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--deltas', type=Path, required=True, help='the module file holding this repo`s DELTAS')
    parser.add_argument('--check', action='store_true', help='write nothing; report what would change')
    args = parser.parse_args(argv)
    root = args.repo.resolve()
    lines = (
        *render_all(root, load_deltas(args.deltas.resolve()), write=not args.check),
        *render_agent_files(root, write=not args.check),
    )
    for line in lines:
        emit(f'[famfiles] {line}')
    settled = ('current', 'rendered')
    return 0 if all(line.split(': ', 1)[1].startswith(settled) for line in lines) else 1


if __name__ == '__main__':
    raise SystemExit(main())
