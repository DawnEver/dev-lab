"""PROJECT-FILES-HAVE-ONE-SOURCE, the DATA: every project-level file the family knows, who owns it, and its renderer.

:data:`PROJECT_FILES` is the one list (ruling 2026-10-03) and :data:`RENDERERS` is read off its rows; the
machinery that plans and runs the renders is :mod:`dev_lab.dev.famfiles`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from dev_lab.dev import ciworkflowshape

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
    present_only: bool = False  # set: due only where a file it writes is present, member or not
    needs: str = ''  # set: in a family repo with no file it writes, due only where the renderer named here is


#: Optional ``deltas``: a repo with no deltas module (cc-market) has no per-file overrides and adopts no base.
FAMFILES: Final = Renderer('famfiles', ('dev_lab.dev.famfiles', '--files'), inputs=(('deltas', '--deltas'),))


#: The guard installs over the deny rules hook_adoption renders: without them its install is refused (exit 1).
AGENT_GUARD: Final = Renderer('agent_guard', ('dev_lab.dev.agent_guard', '--install'), needs='hook_adoption')


HOOK_ADOPTION: Final = Renderer(
    'hook_adoption', ('dev_lab.dev.hook_adoption',), inputs=(('adoption', '--adoption'),),
    required=frozenset({'adoption'}),
)  # fmt: skip


CIWORKFLOWS: Final = Renderer('ciworkflows', ('dev_lab.dev.ciworkflows', 'render'), repo_flag='--root')


#: The editor's managed keys; every other key of the file stays the user's (dev_lab.dev.vscodesettings).
VSCODE: Final = Renderer('vscodesettings', ('dev_lab.dev.vscodesettings', 'render'))


AUTODOORS: Final = Renderer(
    'autodoors', ('dev_lab.dev.autodoors', '--write'), inputs=(('shell_doors', '--shell-door'),)
)


#: The family Rust toolchain, where a repo carries one (it commits Rust: dev_lab.dev.lockcheck).
RUST_TOOLCHAIN: Final = Renderer('rusttoolchain', ('dev_lab.dev.rusttoolchain', 'render'), present_only=True)


#: The whole .claude/settings.json: hooks, the door allow rows (autodoors' source) and the env, plus the delta.
CLAUDE_SETTINGS: Final = Renderer(
    'claudesettings', ('dev_lab.dev.claudesettings', 'render'), inputs=(('shell_doors', '--shell-door'),)
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
        _g(
            '.gitattributes',
            'famconfig RENDERED: the one repo-wide LF line, plus the repo Delta',
            FAMFILES,
        ),
        _m('pyproject.toml', 'famconfig section bases PYPROJECT_SECTIONS; per-repo tables named in PYPROJECT_DECLINED'),
        _g(
            '.claude/settings.json',
            'claudesettings RENDERED: hooks, door allow rows, MPLBACKEND=Agg, plus [tool.dev_lab.claude]',
            CLAUDE_SETTINGS,
        ),
        _g('.claude/hooks/deny-commands.js', 'agent_guard install: the shipped engine, byte for byte', AGENT_GUARD),
        _g('.claude/hooks/venv_resolver.js', 'agent_guard install: the one environment resolver', AGENT_GUARD),
        _g('.claude/hooks/deny-rules.json', 'hook_adoption: the deny registry plus the repo remedies', HOOK_ADOPTION),
        _g('.codex/rules/family-doors.rules', 'autodoors --write: the family doors plus the repo`s', AUTODOORS),
        _g('.codex/rules/family-denies.rules', 'autodoors --write: the deny registry as Codex rules', AUTODOORS),
        ProjectFile(
            '.vscode/settings.json',
            MANAGED,
            'vscodesettings renders the editor excludes; every other key is the user`s',
            renderer=VSCODE,
        ),
        _g(
            'rust-toolchain.toml',
            'rusttoolchain RENDERED: the family channel + components, plus [tool.dev_lab.rust]',
            RUST_TOOLCHAIN,
        ),
        _g('uv.lock', 'famtests.lockpin pins it; forge relock and forge sync freshen it (PIN + FRESHNESS)', None),
        _o('LICENSE', 'the license is the repo`s: MIT, Apache-2.0 and LGPL-3.0 are all in use, one repo has none'),
        _o('README.md', 'its subject is the repo'),
        _o('Makefile', 'its targets and recipes are the repo`s; the family contract retired 2026-11-24'),
        ProjectFile(
            'AGENTS.md',
            MANAGED,
            'agentsection renders the family section between its markers via famfiles; the rest is the repo`s',
            renderer=FAMFILES,
        ),
        _o('CLAUDE.md', 'a pointer to AGENTS.md; the shared rule pages arrive through famtests.rulespages'),
        _o('layout.toml', 'its placement and DECLARED-LAYOUT tables (dev_lab.dev.layout): the tree is the repo`s'),
        _o('CHANGELOG.md', 'the repo`s release history'),
    )
}


#: RETIRED-NAMES-REGISTERED (user ruling 2026-11-24): a project file the family no longer renders or requires,
#: with why. Tracked again in any repo, it is refused by name (:mod:`dev_lab.dev.famtests.famfiles`).
RETIRED_PROJECT_FILES: Final[dict[str, str]] = {
    '.claude/rem.json': 'the backlog is the Gitea tasks repo plus the issue tracker; no per-repo rem config',
    '.claude/rules/principles.md': (
        'the principles render only inside AGENTS.md`s family section (dev_lab.dev.agentsection); no rule page'
    ),
    '.claude/sharp-review.json': 'the forge review is the one review (2026-11-05); no sharp-review ledger',
    '.rgignore': 'no family search-skip file (user ruling 2026-11-24)',
    'ruff.toml': 'ruff config lives only under [tool.ruff] in pyproject.toml',
}


#: Every family file a mechanism writes whole: what a PR review never reads (:mod:`dev_lab.dev.forgereview_scope`).
#: Every base workflow path on either forge (``ci_base.toml``): rendered whole by ciworkflows wherever placed.
#: Not rows -- a repo keeps only the ones its ``[tool.dev_lab.ci]`` places (:func:`ciworkflows.declared_paths`).
WORKFLOW_FILES: Final = frozenset(
    (directory / name).as_posix()
    for forge, directory in ciworkflowshape.WORKFLOW_DIRS.items()
    for name in ciworkflowshape.base_names(forge)
)


GENERATED: Final = frozenset(row.path for row in PROJECT_FILES.values() if row.generated) | WORKFLOW_FILES


#: Every renderer, read off :data:`PROJECT_FILES` in row order: the one list a relock re-runs (user ruling
#: 2026-11-07: a relock that moved dev-lab left every generated file stale and the consumer red). NOT here:
#: ``automode write``, whose file is machine-local and never committed, and the lock, which is the door's.
RENDERERS: Final = tuple(
    dict.fromkeys((*(row.renderer for row in PROJECT_FILES.values() if row.renderer), CIWORKFLOWS))
)
