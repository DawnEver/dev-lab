"""``prep-retry``: the door to a failed environment prep job -- one job asked over the failure, never a build.

Measured 2026-11-28 (Ada, ezxmw9/ezztz): a served repo's envprep jobs failed before the kit installed cargo, and every
tick reported the failure with no door to retry it.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
from lab_commons.hpc.builds import Builds

from dev_lab.dev import hpcaccount
from dev_lab.dev.hpcaccount import prep, prepretry, tick
from dev_lab.dev.hpcaccount import spec as deploy_spec
from dev_lab.dev.hpcaccount.fleet import Target
from dev_lab.dev.hpcaccount.steps import STAMP

FORGE = 'https://forge.example/team'


def _machine(tmp_path: Path) -> tuple[deploy_spec.Deployment, Path]:
    repos = (
        deploy_spec.Repo(deploy_spec.KIT, f'{FORGE}/dev-lab.git', 'trunk'),
        deploy_spec.Repo('alpha', f'{FORGE}/alpha.git', 'trunk'),
    )
    spec = deploy_spec.Deployment('h', tmp_path.as_posix(), '3.13', repos, role=deploy_spec.VERIFICATION)
    machine = tmp_path / 'config.toml'
    machine.write_text(deploy_spec.render(spec), encoding='utf-8')
    return spec, machine


def test_the_retry_asks_the_prep_job_with_retry_for_the_current_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PLANTED CONTROLS: a current environment submits nothing; an undeclared repo is refused."""
    spec, machine = _machine(tmp_path)
    monkeypatch.setattr(tick, 'declared', lambda _c: Builds(install='uv sync'))
    monkeypatch.setattr(tick, 'env_key', lambda *_a: 'k' * 40)
    monkeypatch.setattr(prep, 'kit_of', lambda _s: 'c0ffee')
    asked: list[dict[str, object]] = []

    def submit(_checkout: Path, key: str, **kw: object) -> str:
        asked.append({'key': key, **kw})
        return 'job 600 failed; retry asked: submitted job 777'

    said: list[str] = []
    assert tick.prep_retry('alpha', config=machine, submit=submit, say=said.append) == 0
    [one] = asked
    assert (one['key'], one['kit'], one['retry']) == ('k' * 40, 'c0ffee', True)
    assert str(one['script']).endswith('prep-build alpha')
    assert said == [f'prep-retry: alpha: key {"k" * 12}: job 600 failed; retry asked: submitted job 777']

    live = deploy_spec.checkout_of(spec, spec.repos[1]) / '.venv'
    live.mkdir(parents=True)
    (live / STAMP).write_text('k' * 40, encoding='utf-8')
    prep.stamp_tools(live.parent, ())
    assert tick.prep_retry('alpha', config=machine, submit=submit, say=said.append) == 0
    assert len(asked) == 1, 'a current environment is never resubmitted'
    assert 'is current' in said[-1]
    assert tick.prep_retry('gamma', config=machine, submit=submit, say=said.append) == 2
    assert len(asked) == 1


def test_the_workstation_door_runs_the_accounts_own_kit_on_its_declared_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Through the transport, never raw ssh. PLANTED CONTROL: a repo that is not a name runs nothing."""
    grant = SimpleNamespace(user='u1')
    monkeypatch.setattr(prepretry.look, 'reached_machine', lambda _u: SimpleNamespace(grants=[grant]))
    monkeypatch.setattr(prepretry, 'declared_target', lambda _g, _s: Target('login1', '/r'))
    ran: list[tuple[str, str]] = []

    def pin(_grant: object, host: str) -> Callable[[str, str | None], str]:
        return lambda command, _stdin: ran.append((host, command)) or 'prep-retry: alpha: submitted job 7\nrc=0\n'

    said: list[str] = []
    assert prepretry.retry('u1', 'alpha', connect=lambda _g: lambda _c, _s: '', pin=pin, say=said.append) == 0
    [(host, command)] = ran
    assert host == 'login1'
    assert 'dev_lab.dev.hpcaccount prep-retry-here alpha' in command
    assert said == ['prep-retry: alpha: submitted job 7']
    assert prepretry.retry('u1', 'a;rm -rf ~', connect=lambda _g: lambda _c, _s: '', pin=pin, say=said.append) == 2
    assert len(ran) == 1


def test_the_verbs_are_dispatched(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, ...]] = []
    monkeypatch.setattr(prepretry, 'retry', lambda user, repo: seen.append((user, repo)) or 0)
    monkeypatch.setattr(tick, 'prep_retry', lambda repo: seen.append((repo,)) or 0)
    assert hpcaccount.main(['prep-retry', '--account', 'ezxmw9', 'alpha']) == 0
    assert hpcaccount.main(['prep-retry-here', 'alpha']) == 0
    assert seen == [('ezxmw9', 'alpha'), ('alpha',)]
