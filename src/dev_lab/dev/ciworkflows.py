"""GitHub and Gitea Actions workflows, declared in TOML and RENDERED -- YAML only because the forges force it.

ONE SOURCE PER LAYER: the family base is ``ci_base.toml`` beside this module; a repo's layer is
``[tool.dev_lab.ci."<file>.yml"]`` in its ``pyproject.toml``. EVERY REPO RENDERS ITS FORGE'S WHOLE BASE
(:func:`base_names`: each base table placed on the forge :func:`repo_forge` reads from ``origin``, else from the
repo's declared tables) -- never an opt-in a repo can forget, which is how merge-tick and the comment-triggered
review workflow went undeployed outside dev-lab (2026-11-04). A repo's table layers over a base workflow, renders
another forge's base workflow, or declares one of its own. The layers are
deep-merged (tables key by key; anything else replaces) and each workflow is written to
``.github/workflows/<file>.yml`` as JSON -- JSON is YAML, so the stdlib renders it and no YAML library
is needed. Nothing ever parses a workflow back: the drift check compares RENDERED BYTES to the file,
and a workflow file the table does not declare is refused as hand-written. ``render`` removes a file an
earlier render stamped (:data:`RENDERED_BY`) that nothing declares now, and never a file without the stamp.

A WORKFLOW NAMES ITS FORGE. A table's ``forge`` key (:data:`FORGE_KEY`, ``github`` when omitted) places it in that
forge's directory (:data:`WORKFLOW_DIRS`) and is never rendered: Gitea Actions runs ``.gitea/workflows`` and, once
that exists, ignores ``.github/workflows``. Both forges' workflows draw on the same ``_steps``, so a step the two
share -- the review itself -- has one source. A workflow either forge may run keeps what differs in its
``by-forge`` table (:data:`BY_FORGE`, never rendered): the part named by the merged ``forge`` is merged over the rest.

THE NIGHTLY TIME IS DECLARED ONCE (:data:`NIGHTLY_CRON`). A table's ``nightly = true`` (:data:`NIGHTLY_KEY`, never
rendered) schedules that workflow at it. Gitea renders no promoter: the host's ``dev_lab.ops`` promote role owns it.

SHARED STEPS ARE DECLARED ONCE. The top-level ``_steps`` table (the base's, the repo's ``[tool.dev_lab.ci._steps]``
merged over it) names step lists; a step ``{ use-steps = "<name>" }`` in any job is replaced by that list at render,
so the setup every job repeats has one source. ``_steps`` is never a workflow and never rendered.

THE GITEA RUNNER LABELS ARE DECLARED ONCE: the top-level ``_runners`` table (:data:`RUNNERS`, :func:`runner_labels`)
names each label a Gitea job may run on -- ``review`` for the review job alone, :data:`LIGHT` for the jobs that hold
no review method and no key (user ruling 2026-11-02). It is never a workflow and never rendered.

A JUDGE REPO RENDERS ITS PREPARE WORKFLOW, undeclared: when the repo's ``[tool.dev_lab.review] where = "judge"``, the
base's :data:`PREPARE` table is rendered under :data:`~dev_lab.dev.reviewgate.PREPARE_WORKFLOW` -- the one
name the judge reads its runs by (:func:`~dev_lab.dev.forgereview_pointer.trusted_bundle`) -- a repo layer of that
name merged over it; the layer's ``forge`` picks the forge it runs on (Gitea by default). Any other repo renders
none, and a layer of that name there is refused. Such a repo renders no job the base marks ``served``
(:data:`SERVED_KEY`, :func:`served_only`): its verdict is the judge's, so a job reviewing on the runner could only
fail its check; a workflow left with no job is not rendered.

A DRAFT RUNS NOTHING (user ruling 2026-11-05): every job of a workflow a PR event starts (:data:`PR_EVENTS`) is
AND-guarded at render by :data:`~dev_lab.dev.forgedraft.READY_ONLY` (:func:`ready_only`) -- never typed per job.

A PART FED BY A SECRET gets its own job, cut from the matrix ``part`` job (:func:`dev_lab.dev.jobparts.hosted_jobs`):
the one place a repo's ``[tool.dev_lab.parts] hosted`` declaration reaches a workflow.

THE REVIEW TOOLING IS PINNED ONCE, BY LOCKS: the ``door`` steps install the dev-lab commit the BASE's ``uv.lock`` pins
(dev-lab #18), and the ``method`` steps the ai-lab commit THAT dev-lab's lock pins (its ``review`` group) --
never a floating branch, and never the PR head's own lock (F-76c85dbc4b77).

``python -m dev_lab.dev.ciworkflows render`` writes; ``check`` exits 1 naming every drift -- a base workflow
missing from disk among them.
"""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path
from typing import Any, Final

from lab_commons.log import emit

from dev_lab.dev._forgebackends import backend_for
from dev_lab.dev.family import declared_table
from dev_lab.dev.forge import UnreadableRemote, forge_from_remote
from dev_lab.dev.forgedraft import READY_ONLY
from dev_lab.dev.forgereview_declared import JUDGE, review_from
from dev_lab.dev.jobparts import hosted_jobs, hosted_parts
from dev_lab.dev.reviewgate import PREPARE_WORKFLOW

__all__ = [
    'BASE_PATH',
    'BY_FORGE',
    'FORGE_KEY',
    'LIGHT',
    'NIGHTLY_CRON',
    'NIGHTLY_KEY',
    'PREPARE',
    'PR_EVENTS',
    'RENDERED_BY',
    'RENDER_COMMAND',
    'RUNNERS',
    'SHARED',
    'STAMP',
    'USE_STEPS',
    'WORKFLOW_DIRS',
    'base_names',
    'drift',
    'expand',
    'merge',
    'placed',
    'ready_only',
    'render',
    'repo_forge',
    'runner_labels',
    'workflows',
    'write',
]  # fmt: skip

BASE_PATH: Final = Path(__file__).resolve().parent / 'ci_base.toml'

#: The top-level table of named step lists; never a workflow.
SHARED: Final = '_steps'

#: The top-level table of a judge repo's prepare workflow, rendered as ``PREPARE_WORKFLOW``; never a repo's key.
PREPARE: Final = '_prepare'

#: The top-level table of Gitea runner labels; never a workflow.
RUNNERS: Final = '_runners'
#: The label of the small-memory runner every job that holds no review method nor key runs on.
LIGHT: Final = 'light'

#: The key of a step that stands for a named list of :data:`SHARED`.
USE_STEPS: Final = 'use-steps'
#: The directory each forge's Actions runs its workflows from.
WORKFLOW_DIRS: Final = {'github': Path('.github') / 'workflows', 'gitea': Path('.gitea') / 'workflows'}

#: The table key naming the forge a workflow is rendered for; a placement, never part of the rendered workflow.
FORGE_KEY: Final = 'forge'
#: The table key holding each forge's part of a workflow either may run; only the chosen forge's is merged in.
BY_FORGE: Final = 'by-forge'
#: The table key asking for the nightly schedule; a trigger, never part of the rendered workflow.
NIGHTLY_KEY: Final = 'nightly'
#: When every nightly workflow runs (D48-1A, user ruling 2026-11-01): 02:00 UTC.
NIGHTLY_CRON: Final = '0 2 * * *'
RENDER_COMMAND: Final = 'python -m dev_lab.dev.ciworkflows render'
#: A job key, never rendered: ``served = true`` marks a job that reviews on the runner (``forge review run``).
SERVED_KEY: Final = 'served'


def runner_labels() -> dict[str, str]:
    """Every Gitea runner label ``ci_base.toml`` declares, with what runs on it."""
    return dict(tomllib.loads(BASE_PATH.read_text(encoding='utf-8'))[RUNNERS])


#: How every rendered workflow's first line starts, whatever its stamp said then: the proof a file was rendered.
RENDERED_BY: Final = '# Rendered by dev_lab.dev.ciworkflows '
#: The first line of every rendered workflow -- a YAML comment, so the JSON body below stays valid YAML.
STAMP: Final = (
    f'{RENDERED_BY}from TOML (dev_lab/dev/ci_base.toml + '
    f'[tool.dev_lab.ci] in pyproject.toml). Hand edits are refused; edit the TOML and run `{RENDER_COMMAND}`.'
)


def merge(base: dict[str, Any], layer: dict[str, Any]) -> dict[str, Any]:
    """*layer* deep-merged over *base*: tables merge key by key, any other value replaces. PURE."""
    out = dict(base)
    for key, value in layer.items():
        out[key] = merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def _bare(expression: str) -> str:
    """*expression* without its ``${{ }}`` wrapper, so two guards compose into one."""
    text = expression.strip()
    return text[3:-2].strip() if text.startswith('${{') and text.endswith('}}') else text


def expand(workflow: dict[str, Any], shared: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """*workflow* with every ``{use-steps = <name>}`` step replaced by *shared*'s list of that name. PURE.

    A ``use-steps`` entry's ``if`` guards every step it expands to, AND-ed with a step's own.

    Raises:
        KeyError: a step names a list no ``_steps`` table declares.

    """

    def guarded(step: dict[str, Any], guard: str | None) -> dict[str, Any]:
        if guard is None:
            return step
        if 'if' not in step:
            return {**step, 'if': guard}
        return {**step, 'if': f'${{{{ ({_bare(guard)}) && ({_bare(step["if"])}) }}}}'}

    def steps(job: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            guarded(one, step.get('if')) if USE_STEPS in step else step
            for step in job['steps']
            for one in (shared[step[USE_STEPS]] if USE_STEPS in step else [step])
        ]

    if 'jobs' not in workflow:
        return workflow
    jobs = {name: {**job, 'steps': steps(job)} if 'steps' in job else job for name, job in workflow['jobs'].items()}
    return {**workflow, 'jobs': jobs}


#: The events that start a workflow for a pull request.
PR_EVENTS: Final = frozenset({'pull_request', 'pull_request_target'})


def ready_only(workflow: dict[str, Any]) -> dict[str, Any]:
    """*workflow* with every job AND-guarded by :data:`~dev_lab.dev.forgedraft.READY_ONLY` when a PR starts it. PURE."""
    if not PR_EVENTS & set(workflow.get('on', {})) or 'jobs' not in workflow:
        return workflow

    def guarded(job: dict[str, Any]) -> dict[str, Any]:
        own = f' && ({_bare(job["if"])})' if 'if' in job else ''
        return {**job, 'if': f'${{{{ ({READY_ONLY}){own} }}}}'}

    return {**workflow, 'jobs': {name: guarded(job) for name, job in workflow['jobs'].items()}}


def needs(job: dict[str, Any]) -> set[str]:
    """The jobs *job* ``needs``: Actions takes one name or a list."""
    named = job.get('needs', [])
    return {named} if isinstance(named, str) else set(named)


def served_only(workflow: dict[str, Any], *, judge: bool) -> dict[str, Any]:
    """*workflow* without its :data:`SERVED_KEY` marks; for a *judge* repo, without the jobs they mark either. PURE.

    A judge repo's verdict is the judge host's, so a job reviewing on the runner could only say "not reviewed
    here" and fail its check. A job that ``needs`` a dropped job is dropped with it.
    """
    if 'jobs' not in workflow:
        return workflow
    jobs = dict(workflow['jobs'])
    dropped = {name for name, job in jobs.items() if judge and job.get(SERVED_KEY)}
    while grown := {n for n, job in jobs.items() if n not in dropped and dropped & needs(job)}:
        dropped |= grown
    kept = {
        name: {k: v for k, v in job.items() if k != SERVED_KEY} for name, job in jobs.items() if name not in dropped
    }
    return {**workflow, 'jobs': kept}


def _declared(root: Path) -> tuple[str, dict[str, Any]]:
    """*root*'s ``pyproject.toml`` text (empty when absent) and its ``[tool.dev_lab.ci]`` tables."""
    pyproject = root / 'pyproject.toml'
    text = pyproject.read_text(encoding='utf-8') if pyproject.is_file() else ''
    return text, dict(declared_table(tomllib.loads(text), 'ci', {}))


def repo_forge(root: Path) -> str:
    """The forge *root* is hosted on (``github`` or ``gitea``): its ``origin`` remote, else its declarations.

    With no ``origin`` (a checkout before its push, a scratch repo) the forge is the one every workflow the repo
    declares is placed on (its own ``forge`` key, else the base table's). None, or more than one, is refused.

    Raises:
        ValueError: no ``origin`` and the declarations name no single forge.

    """
    try:
        return backend_for(forge_from_remote(root)).name
    except UnreadableRemote:
        pass
    base = tomllib.loads(BASE_PATH.read_text(encoding='utf-8'))
    forges = {
        layer.get(FORGE_KEY, base.get(name, {}).get(FORGE_KEY, 'github'))
        for name, layer in _declared(root)[1].items()
        if name != SHARED
    }
    if len(forges) != 1:
        msg = (
            f'{root}: no `origin` remote and its [tool.dev_lab.ci] tables name {sorted(forges) or "no"} forge(s) -- '
            f'add the `origin` remote, or declare a workflow placed on the one forge it is hosted on'
        )
        raise ValueError(msg)
    (forge,) = forges
    return forge


def base_names(forge: str) -> set[str]:
    """Every base workflow placed on *forge*: what every repo hosted there renders, declared or not."""
    base = tomllib.loads(BASE_PATH.read_text(encoding='utf-8'))
    return {
        name
        for name, table in base.items()
        if not name.startswith('_') and isinstance(table, dict) and table.get(FORGE_KEY, 'github') == forge
    }


def _placed(root: Path) -> dict[str, tuple[Path, dict[str, Any]]]:
    """Every workflow *root*'s working tree declares (:func:`placed`), on the forge it is hosted on."""
    text, _ = _declared(root)
    return placed(text, str(root / 'pyproject.toml'), repo_forge(root))


def placed(text: str, origin: str, forge: str) -> dict[str, tuple[Path, dict[str, Any]]]:
    """Every workflow pyproject *text* declares on *forge*, by file name: its directory and the workflow, base under.

    Every base workflow placed on *forge* is rendered, declared or not. *origin* names the text in a refusal; a
    reader with no checkout (the protection door) passes the forge's copy.
    """
    base = tomllib.loads(BASE_PATH.read_text(encoding='utf-8'))
    declared = dict(declared_table(tomllib.loads(text), 'ci', {}))
    for name in base_names(forge):
        declared.setdefault(name, {})
    shared = merge(base.get(SHARED, {}), declared.pop(SHARED, {}))
    prepare = base.pop(PREPARE)
    judge = review_from(text, origin).where == JUDGE
    if judge:
        base[PREPARE_WORKFLOW] = prepare
        declared.setdefault(PREPARE_WORKFLOW, {})
    elif PREPARE_WORKFLOW in declared:
        msg = f'[tool.dev_lab.ci."{PREPARE_WORKFLOW}"]: rendered only for [tool.dev_lab.review] where = "{JUDGE}"'
        raise ValueError(msg)
    hosted = hosted_parts(text)
    out = {}
    for name, layer in sorted(declared.items()):
        merged = merge(base.get(name, {}), layer)
        forge = merged.pop(FORGE_KEY, 'github')
        merged = merge(merged, merged.pop(BY_FORGE, {}).get(forge, {}))
        workflow = ready_only(hosted_jobs(expand(served_only(merged, judge=judge), shared), hosted))
        if 'jobs' in workflow and not workflow['jobs']:
            continue  # every job reviewed on the runner, in a judge repo: nothing to render
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
    base = base_names(repo_forge(root))
    out = []
    for name, (directory, workflow) in declared.items():
        path = root / directory / name
        if not path.is_file():
            out.append(f'{path}: {"a base workflow" if name in base else "declared"} and not rendered')
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


def _rendered_here(path: Path) -> bool:
    """Whether *path*'s first line is a render's stamp (:data:`RENDERED_BY`) -- never true of a hand-written file."""
    with path.open(encoding='utf-8') as text:
        return text.readline().startswith(RENDERED_BY)


def write(root: Path) -> list[Path]:
    """Render every declared workflow of *root* to its forge's directory; returns the paths written.

    A workflow file an earlier render wrote (its stamp says so) and no table declares now is removed and named: left
    behind, :func:`drift` would call it hand-written. A file without the stamp is never touched.
    """
    written = []
    for name, (directory, workflow) in _placed(root).items():
        path = root / directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(workflow), encoding='utf-8', newline='\n')
        written.append(path)
    for directory in WORKFLOW_DIRS.values():
        if (root / directory).is_dir():
            for path in sorted((root / directory).iterdir()):
                if path.suffix in {'.yml', '.yaml'} and path not in written and _rendered_here(path):
                    path.unlink()
                    emit(f'[ciworkflows] removed {path}: rendered before, declared no longer')
    return written


def main(argv: list[str] | None = None) -> int:
    """``render`` writes the workflows; ``check`` exits 1 naming each drift."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.ciworkflows', description=__doc__.splitlines()[0])
    parser.add_argument('verb', choices=('render', 'check'))
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
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
