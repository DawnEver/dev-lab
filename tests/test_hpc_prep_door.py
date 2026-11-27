"""The prep job door (:mod:`dev_lab.dev.hpcaccount.prep`): a served repo's environment is built in a Slurm job.

ONE-LOGIN-POLLER (user ruling 2026-11-27): the login-node tick never builds. It reads whether the live environment
is stamped with the current key, and otherwise asks lab-commons' prep job to run this kit's ``prep-build``.
"""

from __future__ import annotations

import shlex
import sys
import types
from pathlib import Path
from typing import Final

import pytest
from lab_commons.hpc.builds import Builds

from dev_lab.dev.hpcaccount import prep, tick
from dev_lab.dev.hpcaccount import spec as deploy_spec
from dev_lab.dev.hpcaccount.steps import STAMP

FORGE: Final = 'https://forge.example/team'


def _live(checkout: Path, stamp: str | None) -> None:
    live = checkout / '.venv'
    live.mkdir(parents=True)
    if stamp is not None:
        (live / STAMP).write_text(stamp, encoding='utf-8')


def test_an_environment_stamped_with_the_key_is_prepared(tmp_path: Path) -> None:
    """PLANTED CONTROLS: another key, and no stamp at all, are not."""
    _live(tmp_path / 'a', 'k1')
    assert prep.prepared(tmp_path / 'a', 'k1')
    assert not prep.prepared(tmp_path / 'a', 'k2')
    _live(tmp_path / 'b', None)
    assert not prep.prepared(tmp_path / 'b', 'k1')
    assert not prep.prepared(tmp_path / 'c', 'k1'), 'no environment at all'


def test_a_lab_commons_without_the_prep_job_is_refused_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every wall teaches: the refusal names the missing function and the lane that provides it."""
    monkeypatch.setitem(sys.modules, 'lab_commons.hpc.prep', types.ModuleType('lab_commons.hpc.prep'))
    said = prep.submit(Path('/r/repos/alpha'), 'k1', python='3.13', root='/r', script='true')
    assert said == prep.ABSENT
    assert 'submit_env_prep' in said
    assert 'pr/toolchain/arch-prep-job' in said


def test_the_prep_job_is_asked_with_the_checkout_key_python_root_and_script(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[tuple[object, ...]] = []
    module = types.ModuleType('lab_commons.hpc.prep')

    def submit_env_prep(checkout: Path, key: str, *, python: str, root: str, script: str) -> str:
        asked.append((checkout, key, python, root, script))
        return 'submitted job 42'

    module.submit_env_prep = submit_env_prep  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, 'lab_commons.hpc.prep', module)
    assert prep.submit(Path('/r/repos/alpha'), 'k1', python='3.13', root='/r', script='x') == 'submitted job 42'
    assert asked == [(Path('/r/repos/alpha'), 'k1', '3.13', '/r', 'x')]


def _deployed(tmp_path: Path) -> tuple[deploy_spec.Deployment, Path]:
    repos = (
        deploy_spec.Repo(deploy_spec.KIT, f'{FORGE}/dev-lab.git', 'trunk'),
        deploy_spec.Repo('alpha', f'{FORGE}/alpha.git', 'trunk'),
    )
    spec = deploy_spec.Deployment('h', '/r/src', '3.13', repos, role=deploy_spec.VERIFICATION)
    machine = tmp_path / 'config.toml'
    machine.write_text(deploy_spec.render(spec), encoding='utf-8')
    return spec, machine


def test_the_job_runs_this_kits_prep_build_from_the_kit_checkout(tmp_path: Path) -> None:
    spec, _machine = _deployed(tmp_path)
    script = prep.job_script(spec, spec.repos[1])
    assert script.startswith(f'cd {shlex.quote(str(deploy_spec.checkout_of(spec, spec.repos[0])))} && ')
    assert script.endswith('-m dev_lab.dev.hpcaccount prep-build alpha')


def test_the_job_body_probes_its_tools_on_the_node_then_builds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The needs probe moved off the login node into the job (Ada 2026-10-25: a tool proven once was gone later).

    PLANTED CONTROL: a need that does not run refuses before any build; once it runs, the build runs.
    """
    _spec, machine = _deployed(tmp_path)
    built: list[str] = []
    pruned: list[str] = []
    runs = {'uv': True, 'rclone': True, 'cc': False}
    monkeypatch.setattr(tick, 'follow_uv', lambda: '')
    monkeypatch.setattr(tick, 'declared', lambda _c: Builds(install='uv sync', needs=('cc',)))
    monkeypatch.setattr(tick, '_runs', lambda _sh, _env, tool: runs[tool])
    monkeypatch.setattr(tick, 'build', lambda _step, _spec, _home, repo: built.append(repo.name) or 0)
    monkeypatch.setattr(tick, 'prune_uv', lambda _step, spec: pruned.append(spec.root) or 0)
    assert tick.prep_build('alpha', home=tmp_path, config=machine) == 2, 'cc has no installer: refused by name'
    assert built == []
    runs['cc'] = True
    assert tick.prep_build('alpha', home=tmp_path, config=machine) == 0
    assert built == ['alpha']
    assert pruned == ['/r/src'], 'the ONE uv cache is pruned after the build'
    assert tick.prep_build('gamma', home=tmp_path, config=machine) == 2, 'an undeclared repo is refused'
