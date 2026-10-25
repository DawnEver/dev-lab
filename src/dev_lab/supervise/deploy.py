"""The phases of a release: fetch, prove, activate, verify, roll back.

THE ORDER IS THE WHOLE POINT. The 2026-10-01 incident that this engine exists to prevent was a
commit that imported a banned dependency at module scope: it deployed cleanly, killed the service
on start, and took fifty minutes to notice because the only check after activation was a liveness
probe that never opened a data file. So a release here is PROVEN BEFORE IT IS ACTIVATED -- built in
its own tree, started on its own port, asked real questions -- and activation only happens once
something has answered them.

WHAT IS GENERIC AND WHAT IS NOT. Every phase is a command the configuration supplies and a URL the
configuration names. The engine knows the SHAPE -- worktree, install, start, probe, restart, verify,
roll back -- and nothing about winding data, Python packaging or systemd units beyond the process
manager it was handed. A target that deploys a Go binary configures different commands and the
engine does not change.

PRODUCTION IS NEVER LEFT BROKEN. The only phase that touches the live target is activation, and
every failure after it rolls back to the newest verified snapshot, restarts, and verifies the
rollback too -- a rollback that is assumed to have worked is how a bad afternoon becomes a bad day.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from lab_commons.outcomes import Status

from dev_lab.supervise.component import ActionContext
from dev_lab.supervise.process.base import Ran
from dev_lab.supervise.release import Snapshot
from dev_lab.supervise.transport import OK_CEILING, OK_FLOOR, Transport, fetch_json

__all__ = [
    'CANDIDATE',
    'PhaseResult',
    'Plan',
    'activate',
    'deploy',
    'fetch',
    'preflight',
    'probe',
    'rollback',
    'verify',
]

#: Where a candidate is built and started. Outside the target's tree so a failed candidate can be
#: removed without touching anything the live service reads, and under ``/var/tmp`` rather than
#: ``/tmp`` because a build in progress must not be swept by a reboot's temp cleanup.
CANDIDATE: Final = '/var/tmp/lab-supervise-candidate'  # noqa: S108

#: What a placeholder in a configured command may name. An explicit set rather than `format` with
#: the config's own dict: a command template is data, and data does not get to reach anything.
PLACEHOLDERS: Final = ('python', 'home', 'port', 'candidate', 'project')


@dataclass(frozen=True)
class Plan:
    """What a deployment's configuration says to do.

    Attributes:
        repositories: repository name to its checkout path.
        main: which repository the release is identified by.
        unit: the service to restart.
        health: the URL that says whether the target is up.
        health_timeout: how long to wait for it.
        install: the command that builds the target's environment, run in the candidate.
        venv: the command that GIVES the candidate an environment to install into, run in the
            candidate before ``install``. Empty for a target whose install makes its own.
        provision: the command that puts the deployment's OWN DEFINITION on the host -- unit files
            and anything else the release ships that the host has to read -- run at ACTIVATION
            only, after the fast-forward and before the restart. Empty for a target with none.
        prepare: the command that wires a candidate's DATA before it is started -- the config it
            reads and the library it serves. Without it a candidate would be started against an
            empty home, answer nothing, and be refused for the wrong reason.
        run: how to start a candidate, with placeholders.
        probe: URLs a candidate must answer before it may be activated.
        ceiling: the memory ceiling for every command this runs.
        keep: how many verified snapshots to retain.
        tolerance: how many consecutive failures of one release to tolerate.

    """

    repositories: Mapping[str, str]
    main: str
    unit: str
    health: str
    health_timeout: int
    install: str
    venv: str
    provision: str
    prepare: str
    run: str
    probe: Sequence[str]
    ceiling: str
    keep: int
    tolerance: int

    def missing(self) -> list[str]:
        """Return the fields a deployment cannot run without.

        AN INCOMPLETE PLAN MUST BE REFUSED RATHER THAN RUN. Every phase below is skipped when its
        command or URL is empty, so a plan with none of them set would build nothing, start
        nothing, probe nothing, and then verify against an empty URL -- passing every step and
        reporting a successful deployment of nothing at all. That is the same failure this kit
        refuses one level up, where a target with no components is not a healthy one.

        Returns:
            The names of the fields that are required and empty.

        """
        required = {
            'repositories': bool(self.repositories),
            'unit': bool(self.unit),
            'health': bool(self.health),
            'install': bool(self.install),
            'run': bool(self.run),
            'probe': bool(self.probe),
        }
        return [name for name, present in required.items() if not present]

    @classmethod
    def from_config(cls, config: Mapping[str, Any], project: Path) -> Plan:
        """Read a plan out of a component's configuration.

        Args:
            config: the ``components.deploy`` table.
            project: the target's directory, for relative checkouts.

        Returns:
            The plan.

        """
        repositories = {
            str(name): str(Path(path) if Path(path).is_absolute() else project / str(path))
            for name, path in dict(config.get('repositories', {})).items()
        }
        return cls(
            repositories=repositories,
            main=str(config.get('main', 'main')),
            unit=str(config.get('unit', '')),
            health=str(config.get('health', '')),
            health_timeout=int(config.get('health_timeout', 60)),
            install=str(config.get('install', '')),
            venv=str(config.get('venv', '')),
            provision=str(config.get('provision', '')),
            prepare=str(config.get('prepare', '')),
            run=str(config.get('run', '')),
            probe=tuple(str(one) for one in config.get('probe', [])),
            ceiling=str(config.get('ceiling', '600M')),
            keep=int(config.get('keep', 3)),
            tolerance=int(config.get('tolerance', 3)),
        )


@dataclass(frozen=True)
class PhaseResult:
    """What a phase did.

    Attributes:
        ok: whether it succeeded.
        detail: what happened, for a log line or an alert.
        commits: the release that ENDED UP LIVE, when the phase got far enough to know.
        tried: the release that was being tried, which is the one a failure is remembered by --
            recording the old release as the failure would make the circuit breaker count the
            wrong thing and never reach its threshold.

    """

    ok: bool
    detail: str = ''
    commits: dict[str, str] | None = None
    tried: dict[str, str] | None = None

    @property
    def status(self) -> Status:
        """The phase in the one vocabulary: ``OK``, or ``ERROR`` -- RETRYABLE, since the breaker retries it."""
        return Status.OK if self.ok else Status.ERROR


def _git(plan: Plan, ctx: ActionContext, repo: str, args: list[str], timeout: int = 120) -> Ran:
    """Run one git command in a repository.

    Args:
        plan: the deployment's plan.
        ctx: the acting context, for the process manager.
        repo: which repository.
        args: the git arguments.
        timeout: seconds to allow.

    Returns:
        What git said.

    """
    return ctx.manager.run_capped(['git', '-C', plan.repositories[repo], *args], memory_max='256M', timeout=timeout)


def fetch(plan: Plan, ctx: ActionContext, *, branch: str = 'main') -> PhaseResult:
    """Fetch every repository and read the commits the remote now holds.

    Args:
        plan: the deployment's plan.
        ctx: the acting context.
        branch: the branch a release is taken from.

    Returns:
        The commits by repository name, or a failure saying which fetch went wrong.

    """
    commits: dict[str, str] = {}
    for name in plan.repositories:
        if not _git(plan, ctx, name, ['fetch', 'origin', '--quiet'], timeout=300).ok:
            return PhaseResult(ok=False, detail=f'{name}: fetch failed')
        head = _git(plan, ctx, name, ['rev-parse', f'origin/{branch}'])
        if not head.ok:
            return PhaseResult(ok=False, detail=f'{name}: origin/{branch} does not resolve')
        commits[name] = head.out.strip()
    return PhaseResult(ok=True, commits=commits)


def probe(urls: Sequence[str], transport: Transport, timeout: float = 5.0) -> PhaseResult:
    """Ask a running candidate the questions that decide whether it may go live.

    Args:
        urls: what to fetch. A candidate that cannot answer these is not proven.
        transport: how a connection is made.
        timeout: seconds to allow each request.

    Returns:
        Whether every URL answered 2xx.

    """
    for url in urls:
        status, body, detail = fetch_json(transport, url, timeout)
        if not OK_FLOOR <= status < OK_CEILING:
            return PhaseResult(ok=False, detail=f'{url} answered {status or "nothing"}: {detail}')
        if body is None:
            return PhaseResult(ok=False, detail=f'{url} answered {status} but not with JSON')
    return PhaseResult(ok=True)


def preflight(
    plan: Plan, ctx: ActionContext, commits: dict[str, str], *, transport: Transport, port: int
) -> PhaseResult:
    """Build and start a candidate, ask it the configured questions, and tear it down.

    NOTHING HERE TOUCHES THE LIVE TARGET. The candidate gets its own worktree, its own environment
    and its own port, which is what lets a bad release be discovered without an outage.

    Args:
        plan: the deployment's plan.
        ctx: the acting context.
        commits: the release being tried.
        transport: how a connection is made, for the probes.
        port: the port to start the candidate on.

    Returns:
        Whether the candidate answered everything it was asked.

    """
    candidate = Path(CANDIDATE)
    home = candidate / 'home'
    _teardown(plan, ctx, candidate)
    if not _git(
        plan, ctx, plan.main, ['worktree', 'add', '--detach', '--force', str(candidate), commits[plan.main]]
    ).ok:
        return PhaseResult(ok=False, detail='the candidate worktree could not be created')
    try:
        home.mkdir(parents=True, exist_ok=True)
        if plan.venv:
            # THE CANDIDATE NEEDS AN ENVIRONMENT BEFORE IT CAN BE INSTALLED INTO, and this step
            # was missing: `preflight` starts the candidate with `{candidate}/.venv/bin/python`
            # and never created it, so an install of the `uv pip install -e .` kind refused with
            # "No virtual environment found" and EVERY release was rejected. It survived its first
            # rehearsal because the rehearsal built the venv by hand before calling in -- the
            # check was passing a precondition the real code path never established.
            made = ctx.manager.run_capped(
                ['sh', '-c', plan.venv], memory_max=plan.ceiling, timeout=600, cwd=str(candidate)
            )
            if not made.ok:
                return PhaseResult(ok=False, detail=f'the candidate environment was not built: {made.detail()}')
        built = ctx.manager.run_capped(
            ['sh', '-c', plan.install], memory_max=plan.ceiling, timeout=900, cwd=str(candidate)
        )
        if not built.ok:
            return PhaseResult(ok=False, detail=f'installing the candidate failed: {built.detail()}')
        if plan.prepare:
            wires = {
                'python': str(candidate / '.venv' / 'bin' / 'python'),
                'home': str(home),
                'port': str(port),
                'candidate': str(candidate),
                'project': str(ctx.project),
            }
            wired = ctx.manager.run_capped(
                ['sh', '-c', plan.prepare.format(**wires)], memory_max=plan.ceiling, timeout=300, cwd=str(candidate)
            )
            if not wired.ok:
                return PhaseResult(ok=False, detail=f'wiring the candidate failed: {wired.detail()}')
        command = plan.run.format(
            python=str(candidate / '.venv' / 'bin' / 'python'),
            home=str(home),
            port=str(port),
            candidate=str(candidate),
            project=str(ctx.project),
        )
        started = ctx.manager.start_capped(
            ['sh', '-c', command], memory_max=plan.ceiling, name='lab-supervise-candidate', cwd=str(candidate)
        )
        if not started.ok:
            return PhaseResult(ok=False, detail=f'the candidate would not start: {started.detail()}')
        try:
            return _wait_for_probe(plan, transport, port)
        finally:
            ctx.manager.stop_unit('lab-supervise-candidate')
    finally:
        _teardown(plan, ctx, candidate)


def _wait_for_probe(plan: Plan, transport: Transport, port: int) -> PhaseResult:
    """Poll the candidate's probes until they answer or the ceiling expires.

    Args:
        plan: the deployment's plan.
        transport: how a connection is made.
        port: the port the candidate was started on.

    Returns:
        The last probe's outcome.

    """
    deadline = time.monotonic() + max(20, plan.health_timeout // 2)
    outcome = PhaseResult(ok=False, detail='the candidate was never asked anything')
    while time.monotonic() < deadline:
        outcome = probe([url.format(port=port) for url in plan.probe], transport)
        if outcome.ok:
            return outcome
        time.sleep(2)
    return outcome


def _teardown(plan: Plan, ctx: ActionContext, candidate: Path) -> None:
    """Remove a candidate worktree and everything under it, tolerating a missing one.

    Args:
        plan: the deployment's plan.
        ctx: the acting context.
        candidate: the candidate's directory.

    """
    _git(plan, ctx, plan.main, ['worktree', 'remove', '--force', str(candidate)])
    _git(plan, ctx, plan.main, ['worktree', 'prune'])


def activate(plan: Plan, ctx: ActionContext, commits: dict[str, str]) -> PhaseResult:
    """Move every repository to the release, install it, and restart the service.

    Args:
        plan: the deployment's plan.
        ctx: the acting context.
        commits: the release to move to.

    Returns:
        Whether activation got as far as restarting.

    """
    for name, wanted in commits.items():
        if not _git(plan, ctx, name, ['merge', '--ff-only', 'origin/main']).ok:
            return PhaseResult(ok=False, detail=f'{name}: could not fast-forward to {wanted[:8]}')
        if not _git(plan, ctx, name, ['merge-base', '--is-ancestor', wanted, 'HEAD']).ok:
            return PhaseResult(ok=False, detail=f'{name}: HEAD is not {wanted[:8]} after the merge')
    if plan.install:
        installed = ctx.manager.run_capped(
            ['sh', '-c', plan.install], memory_max=plan.ceiling, timeout=900, cwd=str(ctx.project)
        )
        if not installed.ok:
            return PhaseResult(ok=False, detail=f'reinstalling failed: {installed.detail()}')
    if plan.provision:
        # THE DEPLOYMENT'S OWN DEFINITION HAS TO ARRIVE WITH THE RELEASE, AND ONLY HERE.
        #
        # Installed by hand at cutover -- which is the divergence this deployment exists to remove:
        # the units that ran were not necessarily the units in the commit, and a unit change in the
        # repository silently did nothing until somebody noticed.
        #
        # ACTIVATION ONLY. `install` runs in the candidate preflight as well, and a provisioning
        # command there would put a CANDIDATE's units on the host -- letting a release that is
        # about to be refused change the machine that refused it. A candidate is a build in a
        # scratch directory being asked whether it can start, and it may touch nothing outside it.
        #
        # After the fast-forward, so it installs this release's own files; before the restart, so
        # the service comes back under the new definition rather than the previous one.
        provisioned = ctx.manager.run_capped(
            ['sh', '-c', plan.provision], memory_max=plan.ceiling, timeout=300, cwd=str(ctx.project)
        )
        if not provisioned.ok:
            return PhaseResult(ok=False, detail=f'provisioning the host failed: {provisioned.detail()}')
    restarted = ctx.manager.restart(plan.unit)
    if not restarted.ok:
        return PhaseResult(ok=False, detail=f'restarting {plan.unit} failed: {restarted.detail()}')
    return PhaseResult(ok=True)


def verify(plan: Plan, commits: dict[str, str], *, transport: Transport) -> PhaseResult:
    """Wait for the live target to answer health, and to say it is running the release.

    Args:
        plan: the deployment's plan.
        commits: the release that should now be live.
        transport: how a connection is made.

    Returns:
        Whether the target came up running what was asked for.

    """
    deadline = time.monotonic() + plan.health_timeout
    detail = 'no answer'
    while time.monotonic() < deadline:
        status, body, detail = fetch_json(transport, plan.health, 5)
        if OK_FLOOR <= status < OK_CEILING and isinstance(body, dict) and body.get('status') == 'healthy':
            reported = str(body.get('commit', ''))
            if reported.startswith(commits.get(plan.main, '')[:8]):
                return PhaseResult(ok=True, detail=f'running {reported}')
            detail = f'reported {reported or "no commit"}, expected {commits.get(plan.main, "")[:8]}'
        time.sleep(2)
    return PhaseResult(ok=False, detail=detail)


def rollback(plan: Plan, ctx: ActionContext, snapshot: Snapshot, *, transport: Transport) -> PhaseResult:
    """Put every repository back at a verified snapshot and prove the service came back.

    Args:
        plan: the deployment's plan.
        ctx: the acting context.
        snapshot: the state to return to.
        transport: how a connection is made.

    Returns:
        Whether the rollback itself was verified -- a rollback assumed to have worked is how one
        bad afternoon becomes a bad day.

    """
    commits = {plan.main: snapshot.main}
    for pair in filter(None, snapshot.libs.split(',')):
        name, _, sha = pair.partition('=')
        if name:
            commits[name] = sha
    for name, sha in commits.items():
        if not _git(plan, ctx, name, ['reset', '--hard', sha]).ok:
            return PhaseResult(ok=False, detail=f'{name}: could not reset to {sha[:8]}')
    if plan.install:
        # THE REINSTALL'S OUTCOME IS CHECKED HERE TOO. `activate` aborts on a failed install; this
        # path ran the same command and threw the result away, so a rollback whose reinstall failed
        # restarted anyway and was reported as verified if the endpoint came up reporting the right
        # commit -- which it can do from the checkout alone, since /health/ reads the commit rather
        # than the code that loaded.
        reinstalled = ctx.manager.run_capped(
            ['sh', '-c', plan.install], memory_max=plan.ceiling, timeout=900, cwd=str(ctx.project)
        )
        if not reinstalled.ok:
            return PhaseResult(ok=False, detail=f'the rollback could not reinstall: {reinstalled.detail()}')
    restarted = ctx.manager.restart(plan.unit)
    if not restarted.ok:
        return PhaseResult(ok=False, detail=f'restarting {plan.unit} failed: {restarted.detail()}')
    return verify(plan, commits, transport=transport)


def deploy(
    plan: Plan,
    ctx: ActionContext,
    previous: Snapshot | None,
    *,
    transport: Transport,
    port: int,
) -> PhaseResult:
    """Run the whole sequence for whatever the remote now holds.

    EVERY FAILURE AFTER ACTIVATION ROLLS BACK, and the rollback is verified rather than assumed.
    A release that comes up wrong but leaves the target down is the only outcome this must never
    produce, and the way it happens is a rollback path nobody exercised.

    Args:
        plan: the deployment's plan.
        ctx: the acting context.
        previous: the newest verified snapshot, or None on a target that has never had one --
            in which case a failure can only be reported, not repaired.
        transport: how a connection is made.
        port: the spare port a candidate is proven on.

    Returns:
        The outcome, whose *commits* are the release that ended up live: the new one when it
        worked, the old one when it did not and the rollback did.

    """
    incomplete = plan.missing()
    if incomplete:
        return PhaseResult(ok=False, detail=f'the deploy plan is incomplete, missing: {", ".join(incomplete)}')
    fetched = fetch(plan, ctx)
    if not fetched.ok or fetched.commits is None:
        return fetched
    commits = fetched.commits
    proven = preflight(plan, ctx, commits, transport=transport, port=port)
    if not proven.ok:
        return PhaseResult(ok=False, detail=f'the candidate was refused: {proven.detail}', tried=commits)
    if not activate(plan, ctx, commits).ok:
        return _recover(plan, ctx, previous, 'activation failed', transport=transport, tried=commits)
    live = verify(plan, commits, transport=transport)
    if live.ok:
        return PhaseResult(ok=True, detail=live.detail, commits=commits, tried=commits)
    return _recover(
        plan, ctx, previous, f'the release came up wrong: {live.detail}', transport=transport, tried=commits
    )


def _recover(
    plan: Plan,
    ctx: ActionContext,
    previous: Snapshot | None,
    because: str,
    *,
    transport: Transport,
    tried: dict[str, str],
) -> PhaseResult:
    """Roll back to the last verified snapshot, or report that there is nothing to roll back to.

    Args:
        plan: the deployment's plan.
        ctx: the acting context.
        previous: the newest verified snapshot, or None.
        because: why the rollback is happening.
        transport: how a connection is made.
        tried: the release that failed, so the circuit breaker counts the right one.

    Returns:
        An outcome that says whether the target is serving again, and what it is serving.

    """
    if previous is None:
        return PhaseResult(
            ok=False, detail=f'{because}, and there is no verified snapshot to roll back to', tried=tried
        )
    back = rollback(plan, ctx, previous, transport=transport)
    if back.ok:
        return PhaseResult(
            ok=False,
            detail=f'{because}; rolled back to {previous.main[:8]} and it is serving',
            commits={'main': previous.main},
            tried=tried,
        )
    return PhaseResult(ok=False, detail=f'{because}; THE ROLLBACK ALSO FAILED: {back.detail}', tried=tried)
