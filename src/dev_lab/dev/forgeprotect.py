"""FORGE-PROTECTION-DECLARED: what the forge enforces on the integration branch and the trunk, rendered from config.

Parity gap 3 (2026-11-04): GitHub's integration branch required one context and the trunk three, neither enforced on
administrators, no approval, no ruleset -- any admin token pushed past every gate -- and Gitea's rules were clicked by
hand. Nothing said what either forge SHOULD hold, so nothing could notice it did not.

ONE SOURCE PER FACT. Nothing here restates a fact another declaration owns:

* the BRANCHES are ``[tool.dev_lab.integrator]``'s ``integration`` and ``trunk`` (:mod:`dev_lab.dev.lanepolicy`);
* the REQUIRED CONTEXTS are derived from the rendered workflows (:mod:`dev_lab.dev.ciworkflows`,
  :func:`required_contexts`): a forge whose workflows post the merge decision requires
  :data:`~dev_lab.dev.forgecontexts.MERGE_READY_CONTEXT` on integration; a forge whose serve host merges requires
  what that merge reads as statuses (``tests/base``, ``tests/security``, and ``tests/review`` where the review is a
  status). The trunk requires the base part's rows the promotion event runs (``tests/base`` and, where workflows fan
  parts out per OS, ``tests/base@<os>``) -- the floor every promotion stands on;
* the APPROVER is ``[tool.dev_lab.review] judge_login``: only a judge posts an approving PR review, so approvals
  are required only where one is declared -- a count with nobody to approve would hold every merge forever;
* a GitHub repo judged by an App (``judge_app``) requires the App's
  :data:`~dev_lab.dev.forgecontexts.JUDGE_CHECK` FROM THAT APP (``integration_id``) on integration, and no approval:
  the App posts a check run, never an approving review;
* what THIS table declares, once, is the rest -- per forge host, the ONE bypass identity (break-glass) and the
  identities that may push the trunk (promote)::

    [tool.dev_lab.protection]
    approvals = 1                                  # optional; default 1 with a judge, else 0 (more needs a judge)
    [tool.dev_lab.protection.forges."github.com"]
    breakglass = "role:admin"                      # GitHub: role:<admin|maintain|write> | app:<id> | team:<id>
    [tool.dev_lab.protection.forges."gitea.example"]
    breakglass = "breakglass-bot"                  # Gitea: a login
    promote = ["promote-bot"]                      # Gitea: who may push the trunk (its fast-forward)

``python -m dev_lab.dev.forge protect plan|check|apply`` renders the declaration onto the repository's forge
(:mod:`dev_lab.dev._protect_github`, :mod:`dev_lab.dev._protect_gitea`): ``plan`` prints every difference, ``check``
exits 1 on any, ``apply`` writes them and re-reads -- an administrator's verb, never CI's: the job token cannot and
must not change the rules that judge it.
"""

from __future__ import annotations

import argparse
import dataclasses
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol

from lab_commons.hpc.needsets import BASE
from lab_commons.log import emit

from dev_lab.dev import _protect_gitea, _protect_github
from dev_lab.dev._forgebackends import GITHUB, backend_for
from dev_lab.dev._protect_steps import Step
from dev_lab.dev.ciworkflows import WORKFLOW_DIRS, placed
from dev_lab.dev.family import declared_table
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgecontexts import CONTEXT_PREFIX, MERGE_READY_CONTEXT, REVIEW_CONTEXT, SECURITY_CONTEXT
from dev_lab.dev.forgereview_declared import JUDGE, SERVE, review_from
from dev_lab.dev.forgework import client_for
from dev_lab.dev.jobparts import rows
from dev_lab.dev.lanepolicy import policy_from

__all__ = [
    'INTEGRATION',
    'TRUNK',
    'Api',
    'Declaration',
    'Identities',
    'Step',
    'Target',
    'apply',
    'declaration_from',
    'main',
    'plan',
    'render',
    'required_contexts',
    'targets',
]

_TABLE: Final = 'protection'

#: The two branch roles a repository declares (``[tool.dev_lab.integrator]``).
INTEGRATION: Final = 'integration'
TRUNK: Final = 'trunk'

#: The job every GitHub ``ci.yml`` fans the parts out under: its name is the part's context.
_PART_JOB: Final = f'{CONTEXT_PREFIX}${{{{ matrix.part }}}}'

#: The event a promotion's parts run under: not a pull request, so every OS row.
_PROMOTION_EVENT: Final = 'push'


class Api(Protocol):
    """The forge calls the protection door makes: :class:`~dev_lab.dev.forgework.Client` is one."""

    @property
    def repo(self) -> str:
        """The repository's API collection path."""
        ...

    def call(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> object:
        """One REST call; an error status raises :class:`~dev_lab.dev.forgefailure.ForgeCallFailed`."""
        ...


@dataclass(frozen=True)
class Identities:
    """One forge's identities: the ONE bypass actor (break-glass) and who may push the trunk (promote)."""

    breakglass: str
    promote: tuple[str, ...] = ()


@dataclass(frozen=True)
class Declaration:
    """``[tool.dev_lab.protection]``: the approvals count and, per forge host, its :class:`Identities`."""

    approvals: int
    forges: Mapping[str, Identities]


@dataclass(frozen=True)
class Target:
    """One branch's rule, backend-neutral: every field derived (module docstring) or declared once."""

    role: str
    branch: str
    contexts: tuple[str, ...]
    bypass: str
    pushers: tuple[str, ...] = ()
    approvals: int = 0
    approver: str = ''
    judge_app: int = 0  # the GitHub App whose JUDGE_CHECK this branch requires from it alone; 0: none

    @property
    def via_pull_request(self) -> bool:
        """Whether the branch moves only by a merged pull request: the integration branch (the trunk fast-forwards)."""
        return self.role == INTEGRATION


def declaration_from(text: str, origin: str) -> Declaration:
    """The table *text* declares; refused naming *origin* when absent, unknown-keyed or approving with no judge."""
    table = declared_table(tomllib.loads(text), _TABLE, None)
    if not isinstance(table, dict) or not table.get('forges'):
        msg = f'[tool.dev_lab.{_TABLE}] in {origin} declares no forges: whose identity bypasses is undecided'
        raise ValueError(msg)
    if unknown := sorted(set(table) - {'approvals', 'forges'}):
        msg = f'[tool.dev_lab.{_TABLE}] in {origin} has unknown key(s) {unknown}; the keys are approvals, forges'
        raise ValueError(msg)
    forges = {}
    for host, entry in table['forges'].items():
        if unknown := sorted(set(entry) - {field.name for field in dataclasses.fields(Identities)}):
            msg = f'[tool.dev_lab.{_TABLE}.forges."{host}"] in {origin} has unknown key(s) {unknown}'
            raise ValueError(msg)
        if not entry.get('breakglass'):
            msg = f'[tool.dev_lab.{_TABLE}.forges."{host}"] in {origin} names no breakglass: the bypass is undecided'
            raise ValueError(msg)
        forges[host] = Identities(str(entry['breakglass']), tuple(entry.get('promote', ())))
    review = review_from(text, origin)
    judged = review.where == JUDGE and not review.judge_app
    approvals = int(table.get('approvals', 1 if judged else 0))
    if approvals and review.judge_app:
        msg = f'[tool.dev_lab.{_TABLE}] in {origin}: approvals = {approvals} with judge_app -- the App posts a check'
        raise ValueError(msg)
    if approvals and not judged:
        msg = (
            f'[tool.dev_lab.{_TABLE}] in {origin}: approvals = {approvals} with no [tool.dev_lab.review] '
            f'where = "{JUDGE}" -- nobody posts an approving review, so every merge would wait forever'
        )
        raise ValueError(msg)
    if approvals < 0:
        msg = f'[tool.dev_lab.{_TABLE}] in {origin}: approvals = {approvals} is below zero'
        raise ValueError(msg)
    return Declaration(approvals, forges)


def required_contexts(text: str, origin: str, forge: Forge) -> dict[str, tuple[str, ...]]:
    """Each role's required status contexts on *forge*, derived from the workflows *text* renders for it."""
    directory = WORKFLOW_DIRS[backend_for(forge).name]
    flows = [flow for where, flow in placed(text, origin, backend_for(forge).name).values() if where == directory]
    jobs = [job for flow in flows for job in flow.get('jobs', {}).values()]
    steps = {step.get('name') for job in jobs for step in job.get('steps', ())}
    if MERGE_READY_CONTEXT in steps:
        integration: tuple[str, ...] = (MERGE_READY_CONTEXT,)
    else:
        reviewed = (REVIEW_CONTEXT,) if review_from(text, origin).where == SERVE else ()
        integration = tuple(sorted({f'{CONTEXT_PREFIX}{BASE}', SECURITY_CONTEXT, *reviewed}))
    if any(job.get('name') == _PART_JOB for job in jobs):
        trunk = tuple(sorted(f'{CONTEXT_PREFIX}{row["part"]}' for row in rows(BASE, _PROMOTION_EVENT, {})))
    else:
        trunk = (f'{CONTEXT_PREFIX}{BASE}',)
    return {INTEGRATION: integration, TRUNK: trunk}


def targets(text: str, origin: str, forge: Forge) -> tuple[Target, ...]:
    """The integration branch's and the trunk's :class:`Target` on *forge*, from pyproject *text* alone."""
    policy = policy_from(text, origin)
    declared = declaration_from(text, origin)
    ours = declared.forges.get(forge.host)
    if ours is None:
        msg = f'[tool.dev_lab.{_TABLE}.forges] in {origin} names no "{forge.host}": its bypass identity is undecided'
        raise ValueError(msg)
    contexts = required_contexts(text, origin, forge)
    review = review_from(text, origin)
    approver = review.judge_login if declared.approvals else ''
    return (
        Target(INTEGRATION, policy.integration, contexts[INTEGRATION], ours.breakglass, (),
               declared.approvals, approver, review.judge_app),
        Target(TRUNK, policy.trunk, contexts[TRUNK], ours.breakglass, ours.promote),
    )  # fmt: skip


def plan(api: Api, forge: Forge, wanted: Sequence[Target]) -> list[Step]:
    """Every :class:`Step` that would make *forge* hold *wanted*; empty when it already does."""
    backend = _protect_github if backend_for(forge) is GITHUB else _protect_gitea
    return backend.plan(api, wanted)


def apply(api: Api, forge: Forge, wanted: Sequence[Target]) -> list[Step]:
    """Write every step of :func:`plan`, then plan again: what the forge still lacks (empty when it took them all)."""
    for step in plan(api, forge, wanted):
        step.write()
    return plan(api, forge, wanted)


def render(steps: Sequence[Step]) -> list[str]:
    """The lines a reader acts on: each subject, then its differences."""
    return [line for step in steps for line in (step.subject, *(f'    {said}' for said in step.lines))]


def main(argv: Sequence[str] | None = None) -> int:
    """``plan`` prints the differences; ``check`` exits 1 on any; ``apply`` writes them (an administrator's verb)."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.forge protect', description=main.__doc__)
    parser.add_argument('verb', choices=('plan', 'check', 'apply'))
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='the checkout whose declaration is rendered')
    parser.add_argument('--url', default='', help="another forge's copy of the repository (default: origin)")
    args = parser.parse_args(argv)
    manifest = args.root / 'pyproject.toml'
    text = manifest.read_text(encoding='utf-8') if manifest.is_file() else ''
    client = client_for(args.root, url=args.url)
    try:
        wanted = targets(text, str(manifest), client.forge)
    except ValueError as refused:
        emit(f'[protect] {refused}', err=True)
        return 2
    steps = apply(client, client.forge, wanted) if args.verb == 'apply' else plan(client, client.forge, wanted)
    emit(f'[protect] {client.forge.identity}: ' + (f'{len(steps)} difference(s)' if steps else 'as declared'))
    for line in render(steps):
        emit(f'  {line}')
    return 1 if steps and args.verb != 'plan' else 0
