"""The SHAPE of a rendered workflow: layers merged, shared steps expanded, PR runs narrowed, jobs placed by role.

Split out of :mod:`dev_lab.dev.ciworkflows` (2026-11-20, MODULE-SIZE-ALARM) along its own seam: that module reads a
repo's declaration and writes files; this one holds the pure transforms of one workflow mapping it applies.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from dev_lab.dev.forgedraft import READY_ONLY
from dev_lab.dev.roles import CI, ROLES

if TYPE_CHECKING:
    from dev_lab.dev.roles import Roles

__all__ = ['BASE_PATH', 'BY_KEY', 'FORGE_KEY', 'PR_EVENTS', 'ROLE_KEY', 'USE_STEPS', 'WORKFLOW_DIRS', 'base_names',
           'expand', 'measurement_isolated', 'merge', 'needs', 'ready_only', 'role_jobs']  # fmt: skip

#: The family's base workflows: every repo renders the ones placed on its forge.
BASE_PATH: Final = Path(__file__).resolve().parent / 'ci_base.toml'
#: The directory each forge's Actions runs its workflows from.
WORKFLOW_DIRS: Final = {'github': Path('.github') / 'workflows', 'gitea': Path('.gitea') / 'workflows'}
#: The table key naming the forge a workflow is rendered for; a placement, never part of the rendered workflow.
FORGE_KEY: Final = 'forge'

#: The key of a step that stands for a named list of :data:`SHARED`.
USE_STEPS: Final = 'use-steps'
#: A job or step key, never rendered: the role (:data:`~dev_lab.dev.roles.ROLES`) its work belongs to.
ROLE_KEY: Final = 'role'
#: A job key, never rendered: the executor kind the job works for (``ci`` when omitted).
BY_KEY: Final = 'by'


def base_names(forge: str) -> set[str]:
    """Every base workflow placed on *forge*: what every repo hosted there renders, declared or not."""
    base = tomllib.loads(BASE_PATH.read_text(encoding='utf-8'))
    return {
        name
        for name, table in base.items()
        if not name.startswith('_') and isinstance(table, dict) and table.get(FORGE_KEY, 'github') == forge
    }


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


def measurement_isolated(workflow: dict[str, Any]) -> dict[str, Any]:
    """A measurement dispatch cannot run ANY normal job, including a consumer-added job. PURE.

    Applied after shared setup expansion so every consumer retains its own environment profile,
    while this job alone leaves no checkout credential for tested code to inherit.
    """
    if 'measurement' not in workflow.get('jobs', {}):
        return workflow
    guard = "inputs.measurement_paths == '' && inputs.measurement_sha == ''"
    jobs = {}
    for name, job in workflow['jobs'].items():
        if name == 'measurement':
            if job.get('permissions') != {'contents': 'read'}:
                msg = 'measurement requires exactly contents: read, never status or merge authority'
                raise ValueError(msg)
            environments = [job.get('env', {}), *(step.get('env', {}) for step in job['steps'])]
            if any({'GITHUB_TOKEN', 'GH_TOKEN'} & set(env) for env in environments) or re.search(
                r'\$\{\{[^}]*\bsecrets\.', json.dumps(job)
            ):
                msg = 'measurement setup may not receive forge tokens or family secrets'
                raise ValueError(msg)
            steps = [
                {**step, 'with': {**step.get('with', {}), 'persist-credentials': False}}
                if step.get('uses', '').startswith('actions/checkout@')
                else step
                for step in job['steps']
            ]
            jobs[name] = {**job, 'steps': steps}
        else:
            own = f' && ({_bare(job["if"])})' if 'if' in job else ''
            jobs[name] = {**job, 'if': f'${{{{ ({guard}){own} }}}}'}
    return {**workflow, 'jobs': jobs}


def needs(job: dict[str, Any]) -> set[str]:
    """The jobs *job* ``needs``: Actions takes one name or a list."""
    named = job.get('needs', [])
    return {named} if isinstance(named, str) else set(named)


def _job_roles(name: str, job: dict[str, Any], where: str) -> tuple[str, ...]:
    """The roles job *name* names (one, or a list for a job doing one role's work after another's)."""
    named = job.get(ROLE_KEY)
    roles = (named,) if isinstance(named, str) else tuple(named) if isinstance(named, list) else ()
    if not roles or any(role not in ROLES for role in roles):
        msg = f'{where} job {name!r} names role = {named!r}: every job names one or more of {list(ROLES)} (D70)'
        raise ValueError(msg)
    return roles


def role_jobs(workflow: dict[str, Any], roles: Roles, where: str) -> dict[str, Any]:
    """*workflow* with only the jobs and steps *roles* binds to their kind, the role marks removed. PURE.

    A job renders where *roles* binds every role it names (:data:`ROLE_KEY`) to its :data:`BY_KEY` kind (``ci`` when
    omitted); a step naming a role renders where that role is on ``ci``. *where* names the workflow in a refusal.

    Raises:
        ValueError: a job names no role or an unknown one, or a kept job ``needs`` a job whose role is elsewhere.

    """
    if 'jobs' not in workflow:
        return workflow
    named = {name: _job_roles(name, job, where) for name, job in workflow['jobs'].items()}
    kept: dict[str, Any] = {}
    for name, job in workflow['jobs'].items():
        if any(roles.kind(role) != job.get(BY_KEY, CI) for role in named[name]):
            continue
        out = {key: value for key, value in job.items() if key not in {ROLE_KEY, BY_KEY}}
        if 'steps' in out:
            out['steps'] = [
                {key: value for key, value in step.items() if key != ROLE_KEY} if isinstance(step, dict) else step
                for step in out['steps']
                if not isinstance(step, dict) or ROLE_KEY not in step or roles.kind(step[ROLE_KEY]) == CI
            ]
        kept[name] = out
    for name, job in kept.items():
        if lacking := sorted(needs(job) - set(kept)):
            theirs = sorted({role for other in lacking for role in named.get(other, ())})
            msg = (
                f'{where} job {name!r} ({"+".join(named[name])}) needs {lacking}, whose role {theirs} is not on '
                f'ci here: the family binds {"+".join(named[name])} to "ci", so it needs {theirs} there too -- that '
                'mix of executors has no workflow'
            )
            raise ValueError(msg)
    return {**workflow, 'jobs': kept}
