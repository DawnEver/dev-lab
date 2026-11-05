"""A TASK CARRIES ITS KEY BUNDLE: one derived secret name per ai-lab task, and the bundle only ever on stdin."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from dev_lab.dev import forgesecrets, taskkeys
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgesecrets import Target

_BUNDLE = '[keys]\nplanted = ["sk-planted-bundle-value-0001", "sk-planted-bundle-value-0002"]\n'


@pytest.mark.parametrize(('task', 'name'), [('pr-review', 'AI_LAB_KEYS_PR_REVIEW'), ('live', 'AI_LAB_KEYS_LIVE')])
def test_a_task_s_secret_name_is_derived(task: str, name: str) -> None:
    assert taskkeys.secret_name(task) == name


@pytest.mark.parametrize('task', ['', 'PR-REVIEW', 'pr_x', 'pr review', 'live; echo', '-live'])
def test_a_malformed_task_is_refused_before_it_names_anything(task: str) -> None:
    with pytest.raises(ValueError, match='task name'):
        taskkeys.secret_name(task)


def _recording(code: int = 0) -> tuple[list[dict[str, Any]], Any]:
    calls: list[dict[str, Any]] = []

    def run(argv: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        calls.append({'argv': list(argv), **kw})
        return subprocess.CompletedProcess(argv, code, stdout=_BUNDLE, stderr=_BUNDLE)

    return calls, run


def test_the_loader_takes_the_bundle_on_stdin_never_argv() -> None:
    """PLANTED CONTROL: a refusing loader raises, and its message (whatever ai-lab echoed) holds no key."""
    calls, run = _recording()
    taskkeys.load(_BUNDLE, 'pr-review', '/opt/ai-lab/bin/python', run=run)
    (call,) = calls
    assert call['argv'] == ['/opt/ai-lab/bin/python', '-I', '-m', 'ai_lab.auth', 'login', '--task', 'pr-review',
                            '--bundle', '-']  # fmt: skip
    assert call['input'] == _BUNDLE
    assert all('sk-planted' not in word for word in call['argv'])
    assert call['capture_output'] is True, 'what ai-lab prints is never echoed'
    _, refusing = _recording(1)
    with pytest.raises(OSError, match='pr-review') as refused:
        taskkeys.load(_BUNDLE, 'pr-review', 'python', run=refusing)
    assert 'sk-planted' not in str(refused.value)


def test_the_review_door_loads_the_named_bundle_and_unsets_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED CONTROL: unset or empty (a fork PR) loads nothing and reports the secret absent."""
    loaded: list[tuple[str, ...]] = []
    monkeypatch.setattr(taskkeys, 'load', lambda *given: loaded.append(given))
    monkeypatch.setenv('AI_LAB_KEYS_PR_REVIEW', _BUNDLE)
    assert taskkeys.keys_loaded('AI_LAB_KEYS_PR_REVIEW', {'ai_lab': {'python': 'py'}}) is True
    assert loaded == [(_BUNDLE, 'pr-review', 'py')]
    assert 'AI_LAB_KEYS_PR_REVIEW' not in os.environ, 'no reviewer inherits it'
    assert taskkeys.keys_loaded('AI_LAB_KEYS_PR_REVIEW', {}) is False
    monkeypatch.setenv('AI_LAB_KEYS_PR_REVIEW', '')
    assert taskkeys.keys_loaded('AI_LAB_KEYS_PR_REVIEW', {}) is False
    assert taskkeys.keys_loaded(None, {}) is True, "no --keys-env: the host's own store holds"
    assert len(loaded) == 1


def _repos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    forges = {'hub': Forge('github.com', 'o', 'hub'), 'tea': Forge('forge.example', 'o', 'tea')}
    monkeypatch.setattr(forgesecrets, 'forge_from_remote', lambda checkout: forges[checkout.name])
    for name in forges:
        (tmp_path / name).mkdir()
    return {name: tmp_path / name for name in forges}


def test_the_targets_are_the_serve_repos_at_their_serve_checkouts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PLANTED CONTROL: a declared name with no checkout is skipped with its reason, never fatal."""
    _repos(tmp_path / 'repos', monkeypatch) if (tmp_path / 'repos').mkdir() is None else None
    monkeypatch.setattr(forgesecrets, 'forge_home', lambda: tmp_path)
    monkeypatch.setattr(
        forgesecrets, 'section', lambda name: {'repos': ['hub', 'gone', 'tea']} if name == 'serve' else {}
    )
    found, skipped = forgesecrets.targets(forgesecrets.declared())
    assert [t.name for t in found] == ['hub', 'tea']
    assert [t.checkout for t in found] == [tmp_path / 'repos' / 'hub', tmp_path / 'repos' / 'tea']
    assert skipped == [f'gone: no checkout at {tmp_path / "repos" / "gone"}'], 'PLANTED CONTROL'


def test_sync_sets_the_derived_secret_on_every_declared_repo_and_logs_no_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repos = _repos(tmp_path, monkeypatch)
    wrote: list[tuple[str, str, str]] = []
    code = forgesecrets.main(
        ['sync', '--task', 'pr-review'], stdin=lambda: _BUNDLE, repos=lambda: repos,
        write=lambda target, name, bundle: wrote.append((target.forge.identity, name, bundle)),
    )  # fmt: skip
    assert code == 0
    assert wrote == [
        ('github.com/o/hub', 'AI_LAB_KEYS_PR_REVIEW', _BUNDLE),
        ('forge.example/o/tea', 'AI_LAB_KEYS_PR_REVIEW', _BUNDLE),
    ]
    said = capsys.readouterr()
    assert 'sk-planted' not in said.out + said.err
    assert said.out.count('AI_LAB_KEYS_PR_REVIEW set (sha256 ') == 2


def test_sync_dry_run_lists_targets_and_touches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """PLANTED CONTROL: the same call without --dry-run reads stdin and writes."""
    repos = _repos(tmp_path, monkeypatch)
    touched: list[str] = []

    def stdin() -> str:
        touched.append('stdin')
        return _BUNDLE

    def write(*_: object) -> None:
        touched.append('write')

    assert forgesecrets.main(['sync', '--task', 'live', '--dry-run'], stdin=stdin, repos=lambda: repos,
                             write=write) == 0  # fmt: skip
    assert touched == []
    out = capsys.readouterr().out
    assert 'would set AI_LAB_KEYS_LIVE on github.com/o/hub' in out
    assert 'would set AI_LAB_KEYS_LIVE on forge.example/o/tea' in out
    assert forgesecrets.main(['sync', '--task', 'live'], stdin=stdin, repos=lambda: repos, write=write) == 0
    assert touched == ['stdin', 'write', 'write'], 'PLANTED CONTROL'


def test_sync_refuses_an_empty_bundle_and_a_bad_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repos = _repos(tmp_path, monkeypatch)

    def never(*_: object) -> None:
        pytest.fail('nothing is written')

    assert forgesecrets.main(['sync', '--task', 'live'], stdin=lambda: ' \n', repos=lambda: repos, write=never) == 2
    assert forgesecrets.main(['sync', '--task', 'Live'], stdin=lambda: _BUNDLE, repos=lambda: repos, write=never) == 2


def test_github_takes_the_bundle_through_gh_on_stdin_never_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    calls, run = _recording()
    monkeypatch.setattr(forgesecrets._door, 'run', run)
    forgesecrets.set_secret(Target('hub', Path(), Forge('github.com', 'o', 'hub')), 'AI_LAB_KEYS_LIVE', _BUNDLE)
    (call,) = calls
    assert call['argv'] == ['gh', 'secret', 'set', 'AI_LAB_KEYS_LIVE', '-R', 'o/hub']
    assert call['input'] == _BUNDLE


def test_gitea_takes_the_bundle_through_the_unjournaled_door(monkeypatch: pytest.MonkeyPatch) -> None:
    """A journaled write keeps its body on disk to replay it: the bundle's client has no journal."""
    seen: list[tuple[Any, ...]] = []

    class _Client:
        repo = 'repos/o/tea'
        journal = None

        def call(self, *given: object) -> None:
            seen.append(given)

    def client(_forge: Forge, **kw: object) -> _Client:
        assert 'journal' not in kw, 'never journaled'
        return _Client()

    monkeypatch.setattr(forgesecrets, 'stored_client', client)
    forgesecrets.set_secret(Target('tea', Path(), Forge('forge.example', 'o', 'tea')), 'AI_LAB_KEYS_LIVE', _BUNDLE)
    assert seen == [('PUT', 'repos/o/tea/actions/secrets/AI_LAB_KEYS_LIVE', {'data': _BUNDLE})]
