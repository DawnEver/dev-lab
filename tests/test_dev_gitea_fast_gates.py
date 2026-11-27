"""GITEA COLLABORATION v2 (user ruling 2026-11-27): the cluster owns tests/cargo, the light runner the fast gates.

(a) A Gitea commit tracking a Cargo workspace NEEDS ``tests/cargo`` -- derived at the candidate source, since no Actions
job derives it there -- and a cluster seat that cannot produce it yet posts an ``error`` naming the lab-commons gap,
never leaving it silently absent. (b) forge-a1's light runner posts security and the head gates through ``gates.yml``
(no pytest, no cargo), and the HPC serve tick then runs neither.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest
from _roles_fixtures import EVERY_CI, HPC_REPO, carry

from dev_lab.dev import cargostep, ciworkflows, forgeschedule, forgeservesteps, forgetake
from dev_lab.dev._forgebackends import GITEA, GITHUB
from dev_lab.dev.forgeclaim import DONE, Work
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.producer import Owner, owner_of

if TYPE_CHECKING:
    from dev_lab.dev.forgework import Client


def _git(root: Path, *args: str) -> str:
    git = shutil.which('git') or 'git'
    done = subprocess.run([git, '-C', str(root), *args], capture_output=True, text=True, check=True)
    return done.stdout.strip()


def _commit(root: Path, files: dict[str, str]) -> str:
    root.mkdir(parents=True, exist_ok=True)
    if not (root / '.git').exists():
        _git(root, 'init', '-q')
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding='utf-8')
    _git(root, 'add', '-A')
    _git(root, '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '-q', '--no-verify', '-m', 'c')
    return _git(root, 'rev-parse', 'HEAD')


_RUST = {'rust/Cargo.toml': '[workspace]\nmembers = ["crates/a"]\n', 'rust/crates/a/Cargo.toml': '[package]\n'}


def test_a_commit_s_workspaces_are_read_from_git_at_that_commit(tmp_path: Path) -> None:
    """PLANTED CONTROL, both sides: the same repo before and after Rust lands; an unknown sha reads none."""
    bare = _commit(tmp_path, {'pyproject.toml': ''})
    rust = _commit(tmp_path, _RUST)
    assert cargostep.workspaces_at(tmp_path, bare) == ()
    assert cargostep.workspaces_at(tmp_path, rust) == ('rust/Cargo.toml',)
    assert cargostep.workspaces_at(tmp_path, '0' * 40) == ()
    assert cargostep.items(tmp_path, rust) == [
        {'manifest': 'rust/Cargo.toml', 'command': command} for command in cargostep.COMMANDS
    ]


@pytest.mark.parametrize(
    ('backend', 'files', 'cargo'),
    [(GITEA, _RUST, True), (GITEA, {'pyproject.toml': ''}, False), (GITHUB, _RUST, False)],
    ids=['gitea-with-rust', 'gitea-without-rust', 'github-matrix-derives-it'],
)
def test_the_candidate_source_derives_cargo_for_a_gitea_rust_commit_alone(
    tmp_path: Path, backend: object, files: dict[str, str], *, cargo: bool
) -> None:
    sha = _commit(tmp_path, files)
    needed = forgeschedule._with_cargo(tmp_path, cast('Client', SimpleNamespace(backend=backend)), sha, ['base'])
    assert needed == (['base', cargostep.PART] if cargo else ['base'])


def _status(state: str, description: str) -> CommitStatus:
    return CommitStatus(context='tests/cargo', state=state, description=description, url='')


def test_an_unproduced_cargo_part_on_a_cluster_seat_posts_error_naming_the_gap_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never silently absent, never the author's red, and never re-said every tick."""
    posted: list[dict[str, Any]] = []
    monkeypatch.setattr(forgetake, 'status_post', lambda _client, sha, **kw: posted.append({'sha': sha, **kw}))
    history: list[CommitStatus] = []
    seat = SimpleNamespace(history=lambda _sha: history, dry_run=False, client=None)
    work = Work('pr/x', 'a' * 40, cargostep.PART, 'open')
    settled = forgetake.ClaimPass._cargo_gap(cast('forgetake.ClaimPass', seat), work)
    assert settled.state == DONE
    (said,) = posted
    assert (said['context'], said['state']) == ('tests/cargo', 'error')
    assert 'no cluster producer' in said['description']
    assert cargostep.ITEM_ENTRY in said['description']
    assert owner_of('error', said['description']) is Owner.ENVIRONMENT
    history.append(_status('error', said['description']))
    forgetake.ClaimPass._cargo_gap(cast('forgetake.ClaimPass', seat), work)
    assert len(posted) == 1, 'the gap already stands: not posted again'


def test_the_cargo_item_runs_one_command_and_reports_its_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED CONTROL: a red exit rides back as the item's ``exit`` (the array's ERROR); no cargo raises."""
    seen: list[list[str]] = []
    monkeypatch.setattr(cargostep.shutil, 'which', lambda name: f'/bin/{name}')
    monkeypatch.setattr(cargostep._door, 'run', lambda argv, **_: seen.append(argv) or SimpleNamespace(returncode=101))
    out = cargostep.run_item({'manifest': 'rust/Cargo.toml', 'command': 'clippy'})
    assert out == {'exit': 101, 'node': 'cargo clippy rust/Cargo.toml'}
    assert seen == [cargostep.argv('/bin/cargo', 'rust/Cargo.toml', 'clippy')]
    monkeypatch.setattr(cargostep.shutil, 'which', lambda _name: None)
    with pytest.raises(FileNotFoundError, match='no cargo'):
        cargostep.run_item({'manifest': 'rust/Cargo.toml', 'command': 'test'})


def _gitea_repo(root: Path, layer: str = '') -> Path:
    (root / 'pyproject.toml').write_text('[tool.dev_lab.ci."review.yml"]\n' + layer, encoding='utf-8')
    return root


def _heavy_words(workflow: dict[str, Any]) -> set[str]:
    text = json.dumps(workflow)
    return {word for word in ('pytest', 'cargo', 'dev_lab.dev.verify', 'jobparts') if word in text}


def test_the_gates_workflow_runs_the_fast_gates_on_light_and_never_pytest_or_cargo(tmp_path: Path) -> None:
    gates = ciworkflows.workflows(_gitea_repo(tmp_path))[ciworkflows.GATES]
    (job,) = gates['jobs'].values()
    assert job['runs-on'] == ciworkflows.LIGHT
    assert set(gates['on']) == {'pull_request_target'}, 'the BASE workflow runs: a PR cannot post its own gates'
    runs = '\n'.join(step.get('run', '') for step in job['steps'])
    for gate in ('ruff" check', 'ruff" format --check', 'typos', 'ciworkflows check', 'headgate run', 'security run'):
        assert gate in runs, gate
    assert _heavy_words(gates) == set()


def test_the_heavy_word_detector_says_no_on_a_planted_pytest_step(tmp_path: Path) -> None:
    """PLANTED CONTROL for the test above: a layer slipping pytest and cargo into the gates job is caught."""
    layer = '[tool.dev_lab.ci."gates.yml".jobs.gates.env]\nSLIPPED = "uv run pytest && cargo test"\n'
    gates = ciworkflows.workflows(_gitea_repo(tmp_path, layer))[ciworkflows.GATES]
    assert _heavy_words(gates) == {'pytest', 'cargo'}


def test_the_merger_follows_the_gates_workflow_too(tmp_path: Path) -> None:
    rendered = ciworkflows.workflows(_gitea_repo(tmp_path))
    assert 'Gates' in rendered['merge.yml']['on']['workflow_run']['workflows']


def test_light_gates_is_a_gitea_repo_whose_merge_is_on_ci(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED CONTROL, both sides: merge bound to the HPC executor renders no gates, so the serve keeps them."""
    root = _gitea_repo(tmp_path)
    carry(monkeypatch, EVERY_CI)
    assert ciworkflows.light_gates(root)
    carry(monkeypatch, HPC_REPO)
    assert not ciworkflows.light_gates(root)
    github = tmp_path / 'gh'
    github.mkdir()
    (github / 'pyproject.toml').write_text('[tool.dev_lab.ci."ci.yml"]\n', encoding='utf-8')
    carry(monkeypatch, EVERY_CI)
    assert not ciworkflows.light_gates(github)


@pytest.mark.parametrize('light', [True, False])
def test_the_serve_tick_runs_security_and_head_gates_only_without_the_light_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, light: bool
) -> None:
    calls: dict[str, Any] = {}
    monkeypatch.setattr(forgeservesteps.ciworkflows, 'light_gates', lambda _root: light)
    monkeypatch.setattr(forgeservesteps, 'observe', lambda *_a, **_k: [])
    monkeypatch.setattr(forgeservesteps, 'load_policy', lambda _root: SimpleNamespace(integration='integrate/main'))

    def ticked(*_a: object, **kw: object) -> object:
        calls['head_gates'] = kw['head_gates']
        return SimpleNamespace(lines=(), said=())

    monkeypatch.setattr(forgeservesteps, 'integration_tick', ticked)
    monkeypatch.setattr(forgeservesteps, 'ready_when_current', lambda *_a, **_k: [])
    monkeypatch.setattr(forgeservesteps, 'security_step', lambda *_a, **_k: calls.setdefault('security', True))
    for name in ('break_glass', 'scarce_red', 'sync_alarms', 'idle_drafts', 'orphans', 'late_reviews'):
        monkeypatch.setattr(forgeservesteps, name, lambda *_a, **_k: [])
    monkeypatch.setattr(forgeservesteps, 'forge_now', lambda _b: None)
    monkeypatch.setattr(forgeservesteps, 'declared_wait', lambda _r: None)
    said: list[str] = []
    forgeservesteps.prompt(tmp_path, 'o/r', cast('Client', None), say=said.append, alarm=lambda _a: None, host='h')
    assert calls['head_gates'] is not light
    assert calls.get('security', False) is not light
    assert any('light runner' in line for line in said) is light


def test_an_unreadable_gates_render_keeps_the_gates_on_the_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_root: Path) -> bool:
        msg = 'no family layer'
        raise ValueError(msg)

    monkeypatch.setattr(forgeservesteps.ciworkflows, 'light_gates', broken)
    said: list[str] = []
    assert forgeservesteps.gates_on_light(Path(), say=said.append) is False
    assert 'no family layer' in said[0]
