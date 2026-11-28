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
from lab_commons import launch
from lab_commons.hpc.builds import Builds

from dev_lab.dev.hpcaccount import prep, tick
from dev_lab.dev.hpcaccount import spec as deploy_spec
from dev_lab.dev.hpcaccount.checks import PINNED_RUST
from dev_lab.dev.hpcaccount.steps import STAMP
from dev_lab.dev.lockcheck import TOOLCHAIN

FORGE: Final = 'https://forge.example/team'


def _live(checkout: Path, stamp: str | None, *, tools: bool = True) -> None:
    live = checkout / '.venv'
    live.mkdir(parents=True)
    if stamp is not None:
        (live / STAMP).write_text(stamp, encoding='utf-8')
    if tools:
        prep.stamp_tools(checkout, ())


def test_an_environment_stamped_with_the_key_is_prepared(tmp_path: Path) -> None:
    """PLANTED CONTROLS: another key, no stamp at all, and a key stamp with no tools stamp, are not."""
    _live(tmp_path / 'a', 'k1')
    assert prep.prepared(tmp_path / 'a', 'k1')
    assert not prep.prepared(tmp_path / 'a', 'k2')
    _live(tmp_path / 'b', None)
    assert not prep.prepared(tmp_path / 'b', 'k1')
    assert not prep.prepared(tmp_path / 'c', 'k1'), 'no environment at all'
    _live(tmp_path / 'd', 'k1', tools=False)
    assert not prep.prepared(tmp_path / 'd', 'k1'), 'built before its needs were proven on a node: the job runs again'


def test_a_lab_commons_without_the_prep_job_is_refused_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every wall teaches: the refusal names the missing function and the lane that provides it."""
    monkeypatch.setitem(sys.modules, 'lab_commons.hpc.prep', types.ModuleType('lab_commons.hpc.prep'))
    said = prep.submit(Path('/r/repos/alpha'), 'k1', python='3.13', root='/r', script='true', kit='c0ffee')
    assert said == prep.ABSENT
    assert 'submit_env_prep' in said
    assert 'pr/toolchain/arch-prep-job' in said


def test_the_prep_job_is_asked_with_the_checkout_key_python_root_and_script(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[tuple[object, ...]] = []
    module = types.ModuleType('lab_commons.hpc.prep')

    def submit_env_prep(checkout: Path, key: str, *, python: str, root: str, script: str, kit: str, retry: bool) -> str:
        asked.append((checkout, key, python, root, script, kit, retry))
        return 'submitted job 42'

    module.submit_env_prep = submit_env_prep  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, 'lab_commons.hpc.prep', module)
    said = prep.submit(Path('/r/repos/alpha'), 'k1', python='3.13', root='/r', script='x', kit='c0ffee')
    assert said == 'submitted job 42'
    assert asked == [(Path('/r/repos/alpha'), 'k1', '3.13', '/r', 'x', 'c0ffee', False)]


def test_a_failed_prep_job_line_names_its_retry_door(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every wall teaches: Ada 2026-11-28, a failed envprep job was reported every tick with no door to retry it.

    PLANTED CONTROL: a submitted line, and a stale failure the job door resubmitted itself, name no door.
    """
    answer = ['job 600 failed: /r/jobs/envprep/k1/prep.log: FAILED: no cargo']
    module = types.ModuleType('lab_commons.hpc.prep')
    module.submit_env_prep = lambda *_a, **_kw: answer[0]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, 'lab_commons.hpc.prep', module)
    monkeypatch.setattr(prep.getpass, 'getuser', lambda: 'ezxmw9')
    said = prep.submit(Path('/r/repos/alpha'), 'k1', python='3.13', root='/r', script='x', kit='c0ffee')
    assert said.endswith('retry: python -m dev_lab.dev.hpcaccount prep-retry --account ezxmw9 alpha')
    for quiet in ('submitted job 7', 'job 600 failed under kit old, not c0ffee: submitted job 7'):
        answer[0] = quiet
        assert prep.submit(Path('/r/repos/alpha'), 'k1', python='3', root='/r', script='x', kit='c0ffee') == quiet


def test_the_kit_is_its_checkouts_commit(tmp_path: Path) -> None:
    """What builds the env: the kit checkout's HEAD. PLANTED CONTROL: no checkout gives a stable placeholder."""
    spec, _machine = _deployed(tmp_path, root=tmp_path.as_posix())
    assert prep.kit_of(spec).startswith('unreadable:')
    kit = deploy_spec.checkout_of(spec, spec.repos[0])
    kit.mkdir(parents=True)
    git = ['git', '-C', str(kit), '-c', 'user.name=t', '-c', 'user.email=t@t']
    for argv in (['init', '-q'], ['commit', '-q', '--allow-empty', '-m', 'x']):
        launch.run([*git, *argv], check=True)
    head = launch.run(
        [*git, 'rev-parse', 'HEAD'], check=True, capture_output=True, text=True, encoding='utf-8'
    ).stdout.strip()
    assert prep.kit_of(spec) == head


def _deployed(tmp_path: Path, root: str = '/r/src') -> tuple[deploy_spec.Deployment, Path]:
    repos = (
        deploy_spec.Repo(deploy_spec.KIT, f'{FORGE}/dev-lab.git', 'trunk'),
        deploy_spec.Repo('alpha', f'{FORGE}/alpha.git', 'trunk'),
    )
    spec = deploy_spec.Deployment('h', root, '3.13', repos, role=deploy_spec.VERIFICATION)
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
    stamped: list[tuple[str, ...]] = []
    monkeypatch.setattr(prep, 'stamp_tools', lambda _checkout, tools: stamped.append(tuple(tools)))
    assert tick.prep_build('alpha', home=tmp_path, config=machine) == 2, 'cc has no installer: refused by name'
    assert built == []
    runs['cc'] = True
    assert tick.prep_build('alpha', home=tmp_path, config=machine) == 0
    assert built == ['alpha']
    assert pruned == ['/r/src'], 'the ONE uv cache is pruned after the build'
    assert stamped == [('cc',)], 'the needs proven on the node are stamped once the build published'
    assert tick.prep_build('gamma', home=tmp_path, config=machine) == 2, 'an undeclared repo is refused'


def _cargo_node(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, built: int = 0) -> tuple[Path, Path, list[str]]:
    """A node where cargo does not run until its installer ran; every shell line the job runs is recorded."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    spec, machine = _deployed(tmp_path, root=tmp_path.as_posix())
    checkout = deploy_spec.checkout_of(spec, spec.repos[1])
    (checkout / '.venv').mkdir(parents=True)
    ran: list[str] = []
    installed = {'uv': True, 'rclone': True, 'cargo': False}

    def change(_step: object, _what: str, argv: list[str], **_kw: object) -> int:
        ran.append(argv[-1])
        if 'sh.rustup.rs' in argv[-1]:
            installed['cargo'] = True
        return 0

    def runs(_sh: object, env: str, tool: str) -> bool:
        ran.append(f'{env}; {tool} --version')
        return installed[tool]

    monkeypatch.setattr(tick, 'follow_uv', lambda: '')
    monkeypatch.setattr(tick, 'declared', lambda _c: Builds(install='uv sync', needs=('cargo',)))
    monkeypatch.setattr(tick, '_runs', runs)
    monkeypatch.setattr(tick.Step, 'change', change)
    monkeypatch.setattr(tick, 'build', lambda *_a: built)
    monkeypatch.setattr(tick, 'prune_uv', lambda *_a: 0)
    return checkout, machine, ran


def test_the_job_installs_cargo_pinned_in_the_checkout_and_stamps_it_proven(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ada 2026-11-28: v1's cargo part waited ``lacking cargo``. The job installs it, pinned, and stamps it proven.

    Every probe runs IN THE CHECKOUT, so its ``rust-toolchain.toml`` applies; with the file, ``rustup toolchain
    install`` runs there. PLANTED CONTROLS: no toolchain file, no pin step; a failed build stamps nothing.
    """
    checkout, machine, ran = _cargo_node(tmp_path, monkeypatch)
    (checkout / TOOLCHAIN).write_text('[toolchain]\nchannel = "1.100.0"\n', encoding='utf-8')
    assert prep.proven(checkout) == frozenset()
    assert tick.prep_build('alpha', home=tmp_path, config=machine) == 0
    here = f'cd {shlex.quote(str(checkout))}'
    assert any('sh.rustup.rs' in line for line in ran), ran
    assert f'{here} && {PINNED_RUST}' in ran
    assert ran[-1] == f'{here}; cargo --version', 'proven again after the installs, in the checkout'
    assert prep.proven(checkout) == {'cargo'}

    unpinned, machine, ran = _cargo_node(tmp_path / 'b', monkeypatch)
    assert tick.prep_build('alpha', home=tmp_path, config=machine) == 0
    assert not any(PINNED_RUST in line for line in ran)
    assert prep.proven(unpinned) == {'cargo'}

    failed, machine, _ran = _cargo_node(tmp_path / 'c', monkeypatch, built=1)
    assert tick.prep_build('alpha', home=tmp_path, config=machine) == 1
    assert prep.proven(failed) == frozenset()


def test_a_need_that_still_does_not_run_after_its_installer_is_refused_unstamped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An installer exiting 0 is not a cargo: the re-probe decides. PLANTED CONTROL: the stamp stays absent."""
    checkout, machine, _ran = _cargo_node(tmp_path, monkeypatch)
    monkeypatch.setattr(tick.Step, 'change', lambda *_a, **_kw: 0)
    assert tick.prep_build('alpha', home=tmp_path, config=machine) == 2
    assert 'lacks cargo' in capsys.readouterr().err
    assert prep.proven(checkout) == frozenset()


def test_the_login_tick_never_runs_rustup_or_cargo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ONE-LOGIN-POLLER: a tick whose environment lacks its tools stamp ASKS the job; it probes and installs nothing.

    PLANTED CONTROL: the job body itself, on the same seams, does run the installer and the probe.
    """
    checkout, machine, ran = _cargo_node(tmp_path, monkeypatch)
    (checkout / '.venv' / STAMP).write_text('k1', encoding='utf-8')  # built for the key, never proven: no TOOLS
    asked: list[str] = []
    monkeypatch.setattr(tick, 'update', lambda *_a: 0)
    monkeypatch.setattr(tick, 'env_key', lambda *_a: 'k1')

    def submit(_checkout: Path, _key: str, **kw: str) -> str:
        asked.append(kw['script'])
        return 'submitted job 7'

    assert tick.tick('alpha', home=tmp_path, config=machine, submit=submit) == 2
    assert ran == [], 'the login node ran a tool'
    assert len(asked) == 1
    assert asked[0].endswith('prep-build alpha')
    assert tick.prep_build('alpha', home=tmp_path, config=machine) == 0
    assert any('rustup' in line for line in ran)
    assert any('cargo --version' in line for line in ran)
