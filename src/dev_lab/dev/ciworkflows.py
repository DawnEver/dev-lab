"""GitHub and Gitea Actions workflows, declared in TOML and RENDERED -- YAML only because the forges force it.

ONE SOURCE PER LAYER: the family base is ``ci_base.toml`` beside this module; a repo's layer is
``[tool.dev_lab.ci."<file>.yml"]`` in its ``pyproject.toml``. A repo opts in to a base workflow by
declaring its table (empty takes the base as is) and may declare workflows of its own. The layers are
deep-merged (tables key by key; anything else replaces) and each workflow is written to
``.github/workflows/<file>.yml`` as JSON -- JSON is YAML, so the stdlib renders it and no YAML library
is needed. Nothing ever parses a workflow back: the drift check compares RENDERED BYTES to the file,
and a workflow file the table does not declare is refused as hand-written.

A WORKFLOW NAMES ITS FORGE. A table's ``forge`` key (:data:`FORGE_KEY`, ``github`` when omitted) places it in that
forge's directory (:data:`WORKFLOW_DIRS`) and is never rendered: Gitea Actions runs ``.gitea/workflows`` and, once
that exists, ignores ``.github/workflows``. Both forges' workflows draw on the same ``_steps``, so a step the two
share -- the review itself -- has one source.

THE NIGHTLY TIME IS DECLARED ONCE (:data:`NIGHTLY_CRON`). A table's ``nightly = true`` (:data:`NIGHTLY_KEY`, never
rendered) schedules that workflow at it, so GitHub's ci.yml and Gitea's promote.yml promote on one clock.

SHARED STEPS ARE DECLARED ONCE. The top-level ``_steps`` table (the base's, the repo's ``[tool.dev_lab.ci._steps]``
merged over it) names step lists; a step ``{ use-steps = "<name>" }`` in any job is replaced by that list at render,
so the setup every job repeats has one source. ``_steps`` is never a workflow and never rendered.

A PART FED BY A SECRET gets its own job, cut from the matrix ``part`` job (:func:`dev_lab.dev.jobparts.hosted_jobs`):
the one place a repo's ``[tool.dev_lab.parts] hosted`` declaration reaches a workflow.

THE REVIEW TOOLING IS PINNED ONCE (:data:`PINS`): the ``method`` steps' ``AI_LAB_REF`` is the ai-lab commit and the
``door`` steps' ``DEV_LAB_REF`` the dev-lab commit every review job installs (:func:`pinned_ref`) -- never a floating
branch, and never the PR head's own lock (F-76c85dbc4b77); ``pin`` compares each with its repo's ``integrate/main``.

``python -m dev_lab.dev.ciworkflows render`` writes; ``check`` exits 1 naming every drift; ``pin`` exits 1 when
a declared ref is not its repo's head.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.family import declared_table
from dev_lab.dev.jobparts import hosted_jobs, hosted_parts
from dev_lab.dev.netverb import run_network_verb

__all__ = [
    'BASE_PATH',
    'FORGE_KEY',
    'NIGHTLY_CRON',
    'NIGHTLY_KEY',
    'PINS',
    'RENDER_COMMAND',
    'SHARED',
    'STAMP',
    'USE_STEPS',
    'WORKFLOW_DIRS',
    'drift',
    'expand',
    'merge',
    'pin_drift',
    'pinned_ref',
    'render',
    'workflows',
    'write',
]  # fmt: skip

BASE_PATH: Final = Path(__file__).resolve().parent / 'ci_base.toml'

#: The top-level table of named step lists; never a workflow.
SHARED: Final = '_steps'

#: The key of a step that stands for a named list of :data:`SHARED`.
USE_STEPS: Final = 'use-steps'
#: The directory each forge's Actions runs its workflows from.
WORKFLOW_DIRS: Final = {'github': Path('.github') / 'workflows', 'gitea': Path('.gitea') / 'workflows'}

#: The table key naming the forge a workflow is rendered for; a placement, never part of the rendered workflow.
FORGE_KEY: Final = 'forge'
#: The table key asking for the nightly schedule; a trigger, never part of the rendered workflow.
NIGHTLY_KEY: Final = 'nightly'
#: When every nightly workflow runs (D48-1A, user ruling 2026-11-01): 02:00 UTC.
NIGHTLY_CRON: Final = '0 2 * * *'
RENDER_COMMAND: Final = 'python -m dev_lab.dev.ciworkflows render'

#: Each pinned repo -> (the ``_steps`` list installing it, the env of its first step naming the commit). Declared ONCE,
#: as that env in ``ci_base.toml``; every workflow reads it there.
PINS: Final = {'ai-lab': ('method', 'AI_LAB_REF'), 'dev-lab': ('door', 'DEV_LAB_REF')}

#: The branch a pin is compared with: where a repo's reviewed changes land.
_PIN_BRANCH: Final = 'refs/heads/integrate/main'


def pinned_ref(repo: str) -> str:
    """The *repo* commit every review job installs: its install step's env in ``ci_base.toml`` (:data:`PINS`)."""
    steps, var = PINS[repo]
    (install, *_) = tomllib.loads(BASE_PATH.read_text(encoding='utf-8'))[SHARED][steps]
    return install['env'][var]


def pin_drift(repo: str, declared: str, head: str) -> str | None:
    """Why *repo*'s *declared* ref is stale against its *head*, naming the bump; ``None`` when it is the head."""
    if declared == head:
        return None
    var = PINS[repo][1]
    return (
        f'{var} pins {repo} {declared[:12]}, its head is {head[:12]}: set {var} = "{head}" in '
        f'dev_lab/dev/ci_base.toml, then `{RENDER_COMMAND}` in every repo'
    )


_LS_REMOTE_FIELDS: Final = 2  # git ls-remote: <sha> TAB <ref>


def _head(root: Path, repo: str) -> str:
    """*repo*'s head, read from the forge that holds *root*'s origin (*repo* beside it)."""
    origin = _door.run(['git', '-C', str(root), 'remote', 'get-url', 'origin'], capture_output=True, text=True,
                            encoding='utf-8', check=True).stdout.strip()  # fmt: skip
    url = origin.rsplit('/', 1)[0] + f'/{repo}.git'
    argv = ['git', 'ls-remote', url, _PIN_BRANCH]
    report = run_network_verb(argv)  # a transient is retried, a refusal is not
    if not report.ok:
        raise subprocess.CalledProcessError(report.returncode, argv, report.remedy)
    rows = (line.split() for line in report.attempts[-1].output.splitlines())
    return next((row[0] for row in rows if len(row) == _LS_REMOTE_FIELDS and row[1].endswith(_PIN_BRANCH)), '')


#: The first line of every rendered workflow -- a YAML comment, so the JSON body below stays valid YAML.
STAMP: Final = (
    f'# Rendered by dev_lab.dev.ciworkflows from TOML (dev_lab/dev/ci_base.toml + '
    f'[tool.dev_lab.ci] in pyproject.toml). Hand edits are refused; edit the TOML and run `{RENDER_COMMAND}`.'
)


def merge(base: dict[str, Any], layer: dict[str, Any]) -> dict[str, Any]:
    """*layer* deep-merged over *base*: tables merge key by key, any other value replaces. PURE."""
    out = dict(base)
    for key, value in layer.items():
        out[key] = merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def expand(workflow: dict[str, Any], shared: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """*workflow* with every ``{use-steps = <name>}`` step replaced by *shared*'s list of that name. PURE.

    Raises:
        KeyError: a step names a list no ``_steps`` table declares.

    """

    def steps(job: dict[str, Any]) -> list[dict[str, Any]]:
        return [one for step in job['steps'] for one in (shared[step[USE_STEPS]] if USE_STEPS in step else [step])]

    if 'jobs' not in workflow:
        return workflow
    jobs = {name: {**job, 'steps': steps(job)} if 'steps' in job else job for name, job in workflow['jobs'].items()}
    return {**workflow, 'jobs': jobs}


def _placed(root: Path) -> dict[str, tuple[Path, dict[str, Any]]]:
    """Every workflow *root* declares, by file name: its forge's directory and the workflow, base merged under."""
    base = tomllib.loads(BASE_PATH.read_text(encoding='utf-8'))
    pyproject = root / 'pyproject.toml'
    text = pyproject.read_text(encoding='utf-8') if pyproject.is_file() else ''
    declared = dict(declared_table(tomllib.loads(text), 'ci', {}))
    shared = merge(base.get(SHARED, {}), declared.pop(SHARED, {}))
    hosted = hosted_parts(text)
    out = {}
    for name, layer in sorted(declared.items()):
        workflow = hosted_jobs(expand(merge(base.get(name, {}), layer), shared), hosted)
        forge = workflow.pop(FORGE_KEY, 'github')
        if workflow.pop(NIGHTLY_KEY, False):
            workflow['on'] = {**workflow['on'], 'schedule': [{'cron': NIGHTLY_CRON}]}
        if forge not in WORKFLOW_DIRS:
            msg = f'[tool.dev_lab.ci."{name}"] {FORGE_KEY} = {forge!r}: the forges are {sorted(WORKFLOW_DIRS)}'
            raise ValueError(msg)
        out[name] = (WORKFLOW_DIRS[forge], workflow)
    return out


def workflows(root: Path) -> dict[str, dict[str, Any]]:
    """Every workflow *root* declares, by file name, with the base merged under the ones it names."""
    return {name: workflow for name, (_, workflow) in _placed(root).items()}


def render(workflow: dict[str, Any]) -> str:
    """The file's bytes: the stamp, then the workflow as indented JSON (which GitHub reads as YAML)."""
    return f'{STAMP}\n{json.dumps(workflow, indent=2, ensure_ascii=False)}\n'


def drift(root: Path) -> list[str]:
    """Every rendered workflow that differs from its file, and every workflow file nobody declared."""
    declared = _placed(root)
    out = []
    for name, (directory, workflow) in declared.items():
        path = root / directory / name
        if not path.is_file():
            out.append(f'{path}: declared and not rendered')
        elif path.read_text(encoding='utf-8') != render(workflow):
            out.append(f'{path}: differs from its TOML (hand-edited, or the TOML moved without a render)')
    for directory in WORKFLOW_DIRS.values():
        if (root / directory).is_dir():
            out += [
                f'{path}: a workflow no [tool.dev_lab.ci] table declares -- hand-written; declare it in TOML'
                for path in sorted((root / directory).iterdir())
                if path.suffix in {'.yml', '.yaml'} and declared.get(path.name, (None,))[0] != directory
            ]
    return out


def write(root: Path) -> list[Path]:
    """Render every declared workflow of *root* to its forge's directory; returns the paths written."""
    written = []
    for name, (directory, workflow) in _placed(root).items():
        path = root / directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(workflow), encoding='utf-8', newline='\n')
        written.append(path)
    return written


def main(argv: list[str] | None = None, *, head: Callable[[str], str] | None = None) -> int:
    """``render`` writes the workflows; ``check`` exits 1 naming each drift; ``pin`` exits 1 on any stale pin."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.ciworkflows', description=__doc__.splitlines()[0])
    parser.add_argument('verb', choices=('render', 'check', 'pin'))
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    if args.verb == 'pin':
        read = head if head is not None else (lambda repo: _head(args.root, repo))
        verdicts = [(repo, pin_drift(repo, pinned_ref(repo), read(repo))) for repo in PINS]
        for repo, stale in verdicts:
            emit(f'[ciworkflows] {stale or f"{PINS[repo][1]} is {repo} head {pinned_ref(repo)[:12]}"}')
        return 1 if any(stale for _, stale in verdicts) else 0
    if args.verb == 'render':
        for path in write(args.root):
            emit(f'[ciworkflows] rendered {path}')
        return 0
    found = drift(args.root)
    for line in found:
        emit(f'[ciworkflows] {line}')
    if found:
        emit(f'[ciworkflows] REFUSED -- edit the TOML, then run `{RENDER_COMMAND}`.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
