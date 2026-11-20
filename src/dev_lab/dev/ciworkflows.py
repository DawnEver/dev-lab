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

THE NIGHTLY TIME DEFAULTS ONCE (:data:`~dev_lab.dev.nightlycron.NIGHTLY_CRON`). A table's ``nightly = true`` (never
rendered) schedules that workflow at it; ``nightly = "<5-field cron>"`` in a repo's layer schedules it at that time
instead (user ruling D63, 2026-11-18: the time is a per-repo setting); a malformed cron is refused by name.
Gitea renders no promoter: the host's ``dev_lab.ops`` promote role owns it.

THE BRANCHES ARE THE REPO'S DECLARATION: :data:`INTEGRATION_PLACEHOLDER` in any string renders as the repo's
``[tool.dev_lab.integrator] integration`` (user ruling 2026-11-12: a one-branch repo merges into ``main``).

SHARED STEPS ARE DECLARED ONCE. The top-level ``_steps`` table (the base's, the repo's ``[tool.dev_lab.ci._steps]``
merged over it) names step lists; a step ``{ use-steps = "<name>" }`` in any job is replaced by that list at render,
so the setup every job repeats has one source. ``_steps`` is never a workflow and never rendered.

THE GITEA RUNNER LABELS ARE DECLARED ONCE: the top-level ``_runners`` table (:data:`RUNNERS`, :func:`runner_labels`)
names each label a Gitea job may run on -- ``review`` for the review job alone, :data:`LIGHT` for the jobs that hold
no review method and no key (user ruling 2026-11-02). It is never a workflow and never rendered.

EVERY JOB NAMES ITS ROLE, AND RENDERS ONLY WHERE THE FAMILY BINDS THAT ROLE TO ITS KIND (D73,
:mod:`dev_lab.dev.roles`): a job's ``role`` (:data:`ROLE_KEY`) is one of :data:`~dev_lab.dev.roles.ROLES` (a list
for a job doing one role's work after another's), its ``by`` (:data:`BY_KEY`, ``ci`` when omitted) the executor kind
it works for; neither is rendered. A job renders only where the repo's roles bind every role it names to its ``by``
(:func:`role_jobs`); a step may name its own ``role`` (the sweep inside the promote job) and renders only where that
role is on ``ci``. A kept job that ``needs`` a job whose role is elsewhere is refused by name: that mix of executors
has no workflow. A workflow left with no job is not rendered, so a repo with no role on ``ci`` renders none at all.
Every rendered workflow carries the repo's kinds as :data:`~dev_lab.dev.roles.ROLES_ENV`, so a job -- which holds no
family layer -- reads the same binding the render did.

THE JUDGE NEEDS NO WORKFLOW (D77): where ``review`` is bound to a ``host`` (a judge), that host fetches each head and
prepares its bundle itself (:func:`~dev_lab.dev.reviewbundle.fetched`), so nothing is rendered for it; the forge
must still wire the judge as a producer (:func:`placed`).

A DRAFT RUNS NOTHING (user ruling 2026-11-05): every job of a workflow a PR event starts (:data:`PR_EVENTS`) is
AND-guarded at render by :data:`~dev_lab.dev.forgedraft.READY_ONLY` (:func:`ready_only`) -- never typed per job.

WHO PRODUCES IS THE FORGE'S DATA (:attr:`~dev_lab.dev._forgebackends.Backend.producers`, user ruling 2026-11-11):
a repo whose review is a producer its forge does not wire is refused at render (:func:`placed`). The judge host is
wired on both forges, and ADVISORY: its verdict never gates a merge (:data:`~dev_lab.dev._forgebackends.ADVISORY`).

A HOSTED PART (a setup, secrets or both) gets its own job, cut from the matrix ``part`` job
(:func:`dev_lab.dev.jobparts.hosted_jobs`): the one place a repo's
``[tool.dev_lab.parts] hosted`` declaration reaches a workflow.

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
from typing import Any, Final, cast

from lab_commons.log import emit

from dev_lab.dev import hostedparts, jobparts
from dev_lab.dev._forgebackends import BACKENDS, JUDGE_HOST, backend_for, require_producer
from dev_lab.dev.ciworkflowshape import (
    expand,
    measurement_isolated,
    merge,
    ready_only,
    role_jobs,
)
from dev_lab.dev.family import declared_table
from dev_lab.dev.forge import UnreadableRemote, forge_from_remote
from dev_lab.dev.lanepolicy import FAMILY_INTEGRATION, policy_from
from dev_lab.dev.nightlycron import scheduled
from dev_lab.dev.roles import HOST, REVIEW, ROLES_ENV, Roles, roles_at
from dev_lab.dev.verifybox import wall_of

__all__ = [
    'BASE_PATH',
    'BY_FORGE',
    'FORGE_KEY',
    'INTEGRATION_PLACEHOLDER',
    'LIGHT',
    'PART_MARGIN_MIN',
    'PART_TIMEOUT_PLACEHOLDER',
    'RENDERED_BY',
    'RENDER_COMMAND',
    'RETIRED_WORKFLOWS',
    'RUNNERS',
    'SHARED',
    'STAMP',
    'WORKFLOW_DIRS',
    'base_names',
    'declared_forge',
    'drift',
    'follow_checks',
    'part_timeout_minutes',
    'placed',
    'render',
    'repo_forge',
    'runner_labels',
    'workflows',
    'write',
]  # fmt: skip

BASE_PATH: Final = Path(__file__).resolve().parent / 'ci_base.toml'

#: The top-level table of named step lists; never a workflow.
SHARED: Final = '_steps'


#: The top-level table of Gitea runner labels; never a workflow.
RUNNERS: Final = '_runners'
#: The label of the small-memory runner every job that holds no review method nor key runs on.
LIGHT: Final = 'light'

#: In any base or layer string, the repo's declared integration branch (``[tool.dev_lab.integrator]``), at render.
INTEGRATION_PLACEHOLDER: Final = '@integration@'
#: A base value that IS this string renders as :func:`part_timeout_minutes` of the repo's selection wall (an int).
PART_TIMEOUT_PLACEHOLDER: Final = '@part-timeout-minutes@'
#: Minutes a part spends outside its selection wall: checkout, sync, posting and the log upload.
PART_MARGIN_MIN: Final = 30
#: The directory each forge's Actions runs its workflows from.
WORKFLOW_DIRS: Final = {'github': Path('.github') / 'workflows', 'gitea': Path('.gitea') / 'workflows'}

#: The table key naming the forge a workflow is rendered for; a placement, never part of the rendered workflow.
FORGE_KEY: Final = 'forge'
#: The table key holding each forge's part of a workflow either may run; only the chosen forge's is merged in.
BY_FORGE: Final = 'by-forge'
RENDER_COMMAND: Final = 'python -m dev_lab.dev.ciworkflows render'

#: A workflow the base no longer renders, each with why; a repo still declaring one is refused by name (migrate once).
RETIRED_WORKFLOWS: Final = {
    'review-prepare.yml': 'the judge fetches each head and prepares its bundle itself (D77)',
}


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
    return declared_forge(_declared(root)[0], str(root))


def declared_forge(text: str, origin: str) -> str:
    """The one forge every workflow pyproject *text* declares is placed on (its own ``forge`` key, else the base's).

    Raises:
        ValueError: the declarations name no single forge; *origin* names the text in the refusal.

    """
    base = tomllib.loads(BASE_PATH.read_text(encoding='utf-8'))
    forges = {
        layer.get(FORGE_KEY, base.get(name, {}).get(FORGE_KEY, 'github'))
        for name, layer in declared_table(tomllib.loads(text), 'ci', {}).items()
        if name != SHARED
    }
    if len(forges) != 1:
        msg = (
            f'{origin}: no `origin` remote and its [tool.dev_lab.ci] tables name {sorted(forges) or "no"} forge(s) -- '
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
    """Every workflow *root*'s working tree declares (:func:`placed`), on its forge, under its family roles."""
    text, _ = _declared(root)
    return placed(text, str(root / 'pyproject.toml'), repo_forge(root), roles_at(root))


def placed(text: str, origin: str, forge: str, roles: Roles) -> dict[str, tuple[Path, dict[str, Any]]]:
    """Every workflow pyproject *text* declares on *forge* under *roles*, by file name: its directory and workflow.

    Every base workflow placed on *forge* is rendered, declared or not, keeping the jobs *roles* binds to their kind
    (:func:`role_jobs`). *origin* names the text in a refusal; a reader with no checkout (the protection door)
    passes the forge's copy.
    """
    base = tomllib.loads(BASE_PATH.read_text(encoding='utf-8'))
    declared = dict(declared_table(tomllib.loads(text), 'ci', {}))
    if stale := sorted(set(declared) & set(RETIRED_WORKFLOWS)):
        why = '; '.join(f'{name}: {RETIRED_WORKFLOWS[name]}' for name in stale)
        msg = f'{origin}: [tool.dev_lab.ci] declares a retired workflow -- {why}; delete the table and its file'
        raise ValueError(msg)
    for name in base_names(forge):
        declared.setdefault(name, {})
    shared = merge(base.get(SHARED, {}), declared.pop(SHARED, {}))
    if roles.kind(REVIEW) == HOST:
        require_producer(BACKENDS[forge], JUDGE_HOST, f'{origin}: review bound to a host (a judge)')
    hosted = hostedparts.hosted_parts(text)
    integration = _integration(text, origin)
    timeout = part_timeout_minutes(wall_of(declared_table(tomllib.loads(text), 'verify', {}), origin))
    out = {}
    for name, layer in sorted(declared.items()):
        merged = merge(base.get(name, {}), layer)
        forge = merged.pop(FORGE_KEY, 'github')
        merged = merge(merged, merged.pop(BY_FORGE, {}).get(forge, {}))
        expanded = jobparts.hosted_jobs(expand(role_jobs(merged, roles, f'{origin} {name}'), shared), hosted)
        workflow = ready_only(measurement_isolated(expanded))
        if 'jobs' in workflow and not workflow['jobs']:
            continue  # no job's role is on its executor here: the forge's CI runs nothing of this workflow
        workflow['env'] = {**workflow.get('env', {}), ROLES_ENV: roles.env()}
        workflow = scheduled(workflow, f'[tool.dev_lab.ci."{name}"]')
        if forge not in WORKFLOW_DIRS:
            msg = f'[tool.dev_lab.ci."{name}"] {FORGE_KEY} = {forge!r}: the forges are {sorted(WORKFLOW_DIRS)}'
            raise ValueError(msg)
        out[name] = (WORKFLOW_DIRS[forge], cast('dict[str, Any]', _named(workflow, integration, timeout)))
    return follow_checks(out)


def follow_checks(rendered: dict[str, tuple[Path, dict[str, Any]]]) -> dict[str, tuple[Path, dict[str, Any]]]:
    """*rendered* with each ``workflow_run`` trigger following the CHECK workflows rendered beside it. PURE.

    A check workflow is one a PR runs (a ``pull_request``-family event) in the same forge directory; the trigger
    names exactly those, so a repo without the Review workflow fires its merger on its own checks. With none, the
    ``workflow_run`` trigger is dropped and the workflow's other triggers (the schedule) stand.
    """
    out = dict(rendered)
    for name, (where, workflow) in rendered.items():
        run = workflow.get('on', {}).get('workflow_run')
        if run is None:
            continue
        checks = sorted(
            other['name']
            for key, (there, other) in rendered.items()
            if key != name and there == where and any(e.startswith('pull_request') for e in other.get('on', {}))
        )
        on = {event: value for event, value in workflow['on'].items() if event != 'workflow_run'}
        if checks:
            on = {'workflow_run': {'workflows': checks, **run}, **on}
        out[name] = (where, {**workflow, 'on': on})
    return out


def _integration(text: str, origin: str) -> str:
    """The integration branch pyproject *text* declares; :data:`FAMILY_INTEGRATION` when it declares no table."""
    if not declared_table(tomllib.loads(text), 'integrator', {}):
        return FAMILY_INTEGRATION
    return policy_from(text, origin).integration


def part_timeout_minutes(wall_s: int) -> int:
    """A hosted part's job timeout: its selection wall *wall_s*, in whole minutes up, plus :data:`PART_MARGIN_MIN`.

    Without one a hung part ran to GitHub's 360-minute default and its run never reached promote (2026-11-20).
    """
    return -(-wall_s // 60) + PART_MARGIN_MIN


def _named(value: object, integration: str, timeout: int) -> object:
    """*value* with its placeholders rendered (the repo's integration branch, the part timeout). PURE.

    :data:`INTEGRATION_PLACEHOLDER` in every string becomes *integration*; a string that IS
    :data:`PART_TIMEOUT_PLACEHOLDER` becomes the int *timeout*.
    """
    if value == PART_TIMEOUT_PLACEHOLDER:
        return timeout
    if isinstance(value, str):
        return value.replace(INTEGRATION_PLACEHOLDER, integration)
    if isinstance(value, dict):
        return {key: _named(item, integration, timeout) for key, item in value.items()}
    if isinstance(value, list):
        return [_named(item, integration, timeout) for item in value]
    return value


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
