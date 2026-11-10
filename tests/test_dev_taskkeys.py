"""A TASK CARRIES ITS KEY BUNDLE: one derived secret name per ai-lab task, and the bundle only ever on stdin."""

from __future__ import annotations

import os
import shutil
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


def test_the_targets_are_the_family_members_at_their_checkouts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The targets DERIVE from the family list, ``[repos]`` (:mod:`dev_lab.dev.family.members`).

    PLANTED CONTROL: a declared name with no checkout is skipped with its reason, never fatal.
    """
    _repos(tmp_path / 'repos', monkeypatch) if (tmp_path / 'repos').mkdir() is None else None
    monkeypatch.setattr(forgesecrets, 'repos', lambda: {n: tmp_path / 'repos' / n for n in ('hub', 'gone', 'tea')})
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
        ['sync', '--task', 'pr-review'], stdin=lambda: _BUNDLE, members=lambda: repos,
        write=lambda target, name, bundle: wrote.append((target.forge.identity, name, bundle)),
    )  # fmt: skip
    assert code == 0, 'a withheld member is no failure'
    assert wrote == [('github.com/o/hub', 'AI_LAB_KEYS_PR_REVIEW', _BUNDLE)], 'ruling 2026-11-03: never a Gitea member'
    said = capsys.readouterr()
    assert 'sk-planted' not in said.out + said.err
    assert said.out.count('AI_LAB_KEYS_PR_REVIEW set (sha256 ') == 1
    assert 'tea: withheld -- forge.example runs a PR branch with its secrets readable' in said.out


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

    assert forgesecrets.main(['sync', '--task', 'live', '--dry-run'], stdin=stdin, members=lambda: repos,
                             write=write) == 0  # fmt: skip
    assert touched == []
    out = capsys.readouterr().out
    assert 'would set AI_LAB_KEYS_LIVE on github.com/o/hub' in out
    assert 'would set AI_LAB_KEYS_LIVE on forge.example/o/tea' not in out
    assert forgesecrets.main(['sync', '--task', 'live'], stdin=stdin, members=lambda: repos, write=write) == 0
    assert touched == ['stdin', 'write'], 'PLANTED CONTROL'


def test_sync_refuses_an_empty_bundle_and_a_bad_task(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repos = _repos(tmp_path, monkeypatch)

    def never(*_: object) -> None:
        pytest.fail('nothing is written')

    assert forgesecrets.main(['sync', '--task', 'live'], stdin=lambda: ' \n', stored=lambda _t: '',
                             members=lambda: repos, write=never) == 2  # fmt: skip
    assert forgesecrets.main(['sync', '--task', 'Live'], stdin=lambda: _BUNDLE, members=lambda: repos, write=never) == 2


def test_the_bundle_is_stored_once_and_sync_reads_it_when_nothing_is_piped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """User 2026-11-09: the bundle was asked for again on every sync; it is kept ONCE, in the credential store.

    PLANTED CONTROLS: the bundle reaches the store base64-encoded (the credential protocol is line-based) under the
    secret's name and nowhere else -- no output line, no file under the test root -- and a sync with nothing piped
    reaches every member from it; a piped bundle still wins (a one-off override).
    """
    kept: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(
        forgesecrets, 'store_credential', lambda host, user, secret: kept.update({(host, user): secret})
    )
    monkeypatch.setattr(forgesecrets, 'credential_for', lambda host, username: (username, kept[host, username]))
    assert forgesecrets.main(['store', '--task', 'pr-review'], stdin=lambda: _BUNDLE) == 0
    assert list(kept) == [(forgesecrets.BUNDLE_HOST, 'AI_LAB_KEYS_PR_REVIEW')]
    assert '\n' not in next(iter(kept.values()))
    assert forgesecrets.stored_bundle('pr-review') == _BUNDLE
    repos = _repos(tmp_path, monkeypatch)
    wrote: list[str] = []
    assert forgesecrets.main(['sync', '--task', 'pr-review'], stdin=lambda: '', members=lambda: repos,
                             write=lambda _t, _n, bundle: wrote.append(bundle)) == 0  # fmt: skip
    assert wrote == [_BUNDLE]
    said = capsys.readouterr()
    assert 'sk-planted' not in said.out + said.err
    assert not [p for p in tmp_path.rglob('*') if p.is_file() and 'sk-planted' in p.read_text(errors='ignore')]
    assert forgesecrets.main(['sync', '--task', 'pr-review'], stdin=lambda: 'other', members=lambda: repos,
                             write=lambda _t, _n, bundle: wrote.append(bundle)) == 0  # fmt: skip
    assert wrote[-1] == 'other'


def test_github_takes_the_bundle_through_gh_on_stdin_never_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    calls, run = _recording()
    monkeypatch.setattr(forgesecrets._door, 'run', run)
    forgesecrets.set_secret(Target('hub', Path(), Forge('github.com', 'o', 'hub')), 'AI_LAB_KEYS_LIVE', _BUNDLE)
    (call,) = calls
    assert call['argv'] == ['gh', 'secret', 'set', 'AI_LAB_KEYS_LIVE', '-R', 'o/hub']
    assert call['input'] == _BUNDLE


def test_set_secret_refuses_a_gitea_member_and_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ruling 2026-11-03: Gitea's PR workflow runs the PR branch with its secrets readable.

    PLANTED CONTROL: the same call on a GitHub member writes through ``gh``.
    """
    calls, run = _recording()
    monkeypatch.setattr(forgesecrets._door, 'run', run)
    with pytest.raises(OSError, match='withheld'):
        forgesecrets.set_secret(Target('tea', Path(), Forge('forge.example', 'o', 'tea')), 'AI_LAB_KEYS_LIVE', _BUNDLE)
    assert calls == []
    forgesecrets.set_secret(Target('hub', Path(), Forge('github.com', 'o', 'hub')), 'AI_LAB_KEYS_LIVE', _BUNDLE)
    assert len(calls) == 1


def _keeping(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], str]:
    kept: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(
        forgesecrets, 'store_credential', lambda host, user, secret: kept.update({(host, user): secret})
    )
    monkeypatch.setattr(forgesecrets, 'credential_for', lambda host, username: (username, kept[host, username]))
    return kept


def _outside_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A key file's home with no ``.git`` above it: a checkout ABOVE the test root is not the test's to see."""
    real = forgesecrets._in_checkout

    def within(path: Path) -> Path | None:
        found = real(path)
        return found if found is not None and found.is_relative_to(tmp_path) else None

    monkeypatch.setattr(forgesecrets, '_in_checkout', within)
    return tmp_path


def test_store_from_a_file_keeps_the_bundle_deletes_the_file_and_never_says_a_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """User ruling 2026-11-10: the user places the bundle as a FILE; ``--from`` stores it, then unlinks it.

    PLANTED CONTROL: the fake key values reach the store and nothing else -- no output line, no file left.
    """
    kept = _keeping(monkeypatch)
    source = _outside_git(tmp_path, monkeypatch) / 'keys.toml'
    source.write_text(_BUNDLE, encoding='utf-8')
    assert forgesecrets.main(['store', '--task', 'pr-review', '--from', str(source)], stdin=lambda: '') == 0
    assert forgesecrets.stored_bundle('pr-review') == _BUNDLE
    assert list(kept) == [(forgesecrets.BUNDLE_HOST, 'AI_LAB_KEYS_PR_REVIEW')]
    assert not source.exists()
    said = capsys.readouterr()
    assert 'sk-planted' not in said.out + said.err
    assert not [p for p in tmp_path.rglob('*') if p.is_file() and 'sk-planted' in p.read_text(errors='ignore')]


def test_store_from_a_file_refuses_a_directory_a_checkout_and_a_failed_store_keeping_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    kept = _keeping(monkeypatch)
    root = _outside_git(tmp_path, monkeypatch)
    assert forgesecrets.main(['store', '--task', 'pr-review', '--from', str(root)], stdin=lambda: '') == 2
    checkout = root / 'checkout'
    subprocess.run([shutil.which('git') or 'git', 'init', '-q', str(checkout)], check=True, capture_output=True)
    inside = checkout / 'sub' / 'keys.toml'
    inside.parent.mkdir()
    inside.write_text(_BUNDLE, encoding='utf-8')
    assert forgesecrets.main(['store', '--task', 'pr-review', '--from', str(inside)], stdin=lambda: '') == 2
    assert inside.exists()
    assert not kept

    def refuse(*_given: str) -> None:
        unavailable = 'credential store unavailable'
        raise OSError(unavailable)

    monkeypatch.setattr(forgesecrets, 'store_credential', refuse)
    source = root / 'keys.toml'
    source.write_text(_BUNDLE, encoding='utf-8')
    assert forgesecrets.main(['store', '--task', 'pr-review', '--from', str(source)], stdin=lambda: '') == 2
    assert source.exists()
    said = capsys.readouterr()
    assert str(source) in said.err
    assert str(inside) in said.err
    assert 'sk-planted' not in said.out + said.err
