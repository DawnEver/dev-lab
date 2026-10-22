"""PUSH ADMISSION, read off the FORGE: lanes and integration need no part, the trunk needs every part green.

Forge plan section 6 (user rulings 2026-10-09): parts are produced FROM pushed shas, so only the trunk
is judged, on HEAD's ``tests/<platform>`` statuses, from any workstation -- and when the forge cannot be
read the trunk WAITS; the local ledger is never consulted.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from lab_commons.outcomes import Conclusion

from dev_lab.dev import mergeaudit, pushgate
from dev_lab.dev.forge import NoCredential
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.platformparts import Part, part_context

_GIT = shutil.which('git') or 'git'
HEAD = 'abc1234' + 'd' * 33


def _status(
    platform: str, result: Conclusion = Conclusion.PASS, *, scope: str = 'full', hands: dict[str, int] | None = None
) -> CommitStatus:
    part = Part(platform, scope, result, ran=10, hands=hands or {})
    return CommitStatus(part_context(platform), part.state, part.description(), 'https://forge/attachments/1')


def _trunk(statuses: list[CommitStatus]) -> pushgate.Decision:
    return pushgate.decide(pushgate.TRUNK, head=HEAD, statuses=lambda: statuses)


@pytest.mark.parametrize('destination', [pushgate.LANE, pushgate.INTEGRATION])
def test_a_lane_and_an_integration_push_need_no_part(destination: str) -> None:
    """Parts are produced from pushed shas; asking for one before the push would deadlock."""

    def never() -> list[CommitStatus]:
        pytest.fail('a lane or integration push read the forge')

    decided = pushgate.decide(destination, head=HEAD, statuses=never)
    assert decided.allowed
    assert 'no part' in decided.message


@pytest.mark.parametrize('order', ['base first', 'windows first'])
def test_a_base_and_a_windows_part_compose_in_either_order(order: str) -> None:
    statuses = [_status('base', hands={'windows': 2}), _status('windows')]
    decided = _trunk(statuses if order == 'base first' else statuses[::-1])
    assert decided.allowed, decided.message
    assert 'base=PASS/full' in decided.message
    assert 'windows=PASS/full' in decided.message


def test_a_missing_part_is_refused_naming_the_part_and_its_producer() -> None:
    """PLANTED CONTROL: base hands two ids to windows, and no windows part was posted."""
    decided = _trunk([_status('base', hands={'windows': 2})])
    assert not decided.allowed
    assert 'missing the windows part (base hands 2)' in decided.message
    assert 'host having every resource it needs' in decided.message


@pytest.mark.parametrize(
    ('statuses', 'why'),
    [
        ([], 'no tests/base part is posted'),
        ([_status('jmag')], 'no tests/base part is posted'),
        ([_status('base', Conclusion.FAIL)], 'base is FAIL of scope full'),
        ([_status('base', scope='incremental')], 'base is PASS of scope incremental'),
        ([CommitStatus('tests/base', 'pending', 'claim machine=G login=a until=x', '')], 'not a settled part'),
        ([CommitStatus('tests/base', 'success', 'free text', '')], 'not a settled part'),
    ],
)
def test_the_trunk_refuses_anything_but_every_part_a_full_pass(statuses: list[CommitStatus], why: str) -> None:
    """PLANTED CONTROLS: nothing, a FAIL, an incremental part, a claim, a foreign description, no base."""
    decided = _trunk(statuses)
    assert not decided.allowed
    assert why in decided.message


def test_other_contexts_are_not_parts() -> None:
    assert _trunk([_status('base'), CommitStatus('ci/foreign', 'failure', 'not a part', '')]).allowed


@pytest.mark.parametrize('error', [NoCredential('no stored credential'), OSError('connection refused')])
def test_the_trunk_waits_when_the_forge_cannot_be_read(error: Exception) -> None:
    """Gitea down => main waits: no local fallback stands in for the forge."""

    def down() -> list[CommitStatus]:
        raise error

    decided = pushgate.decide(pushgate.TRUNK, head=HEAD, statuses=down)
    assert not decided.allowed
    assert 'WAITS' in decided.message
    assert 'no local fallback' in decided.message


def test_the_parser_reads_the_last_verdict_in_either_grammar() -> None:
    """The stamp grammar's ONE reader stays here: runners still stamp their logs as evidence."""
    line = f'[verdict tree={HEAD} env=e0 tier=heavy selector=12-paths] PASS -- detail'
    parsed = pushgate.parse_verdict_line('noise\n' + line)
    assert parsed is not None
    assert (parsed.env, parsed.tier, parsed.result) == ('e0', 'heavy', 'PASS')
    stamped = 'VERDICT result=inconclusive tree=t1 env=e1 log=sha256:00@3 selector=verify'
    flat = pushgate.parse_verdict_line(line + '\n' + stamped)
    assert flat is not None
    assert (flat.tree, flat.tier, flat.result) == ('t1', None, 'INCONCLUSIVE')
    assert pushgate.parse_verdict_line('no verdict here') is None


def _forge(monkeypatch: pytest.MonkeyPatch, statuses: list[CommitStatus]) -> None:
    monkeypatch.setattr(pushgate, '_head', lambda _root: HEAD)
    monkeypatch.setattr(pushgate, 'unprompted_client', lambda _root: None)
    monkeypatch.setattr(pushgate, 'status_list', lambda _client, _sha: statuses)


def test_the_cli_reads_the_forge_and_routes_each_destination(tmp_path: Path, monkeypatch) -> None:
    _forge(monkeypatch, [_status('base', Conclusion.FAIL)])
    base = ['--root', str(tmp_path), '--trunk-ref', 'refs/heads/main']
    assert pushgate.main([*base, '--remote-ref', 'refs/heads/feat/x']) == 0
    assert pushgate.main([*base, '--remote-ref', 'refs/heads/integrate/main']) == 0
    assert pushgate.main([*base, '--remote-ref', 'refs/heads/main']) == 1
    _forge(monkeypatch, [_status('base')])
    assert pushgate.main([*base, '--remote-ref', 'refs/heads/main']) == 0


def test_the_hook_spelling_reads_git_s_pre_push_lines_on_stdin(tmp_path: Path, monkeypatch) -> None:
    """A pre-push hook gets the pushed refs on stdin, one line each, judged at the sha being pushed.

    PLANTED: the trunk with NO part posted is refused through the hook spelling -- the vacuous case.
    """
    _forge(monkeypatch, [])
    base = ['--root', str(tmp_path), '--trunk-ref', 'refs/heads/main']
    sha = 'a' * 40
    monkeypatch.setattr(sys, 'stdin', io.StringIO(f'refs/heads/main {sha} refs/heads/main {"0" * 40}\n'))
    assert pushgate.main(base) == 1
    monkeypatch.setattr(sys, 'stdin', io.StringIO(f'refs/heads/x {sha} refs/heads/lane/x {"0" * 40}\n'))
    assert pushgate.main(base) == 0


def test_no_remote_ref_anywhere_is_a_refused_argv_and_never_an_admission(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(sys, 'stdin', io.StringIO(''))
    with pytest.raises(SystemExit) as refused:
        pushgate.main(['--root', str(tmp_path), '--trunk-ref', 'refs/heads/main'])
    assert refused.value.code == 2


def test_a_push_that_only_deletes_refs_admits_nothing_and_passes(tmp_path: Path, monkeypatch) -> None:
    """``git push origin --delete <b>`` publishes no commit, so there is nothing to judge and nothing to refuse.

    PLANTED CONTROL: the empty-stdin case above stays a refused argv; only git's deletion lines pass.
    """
    _forge(monkeypatch, [])
    zero = '0' * 40
    lines = f'(delete) {zero} refs/heads/lane/a {"b" * 40}\n(delete) {zero} refs/heads/lane/b {"c" * 40}\n'
    monkeypatch.setattr(sys, 'stdin', io.StringIO(lines))
    assert pushgate.main(['--root', str(tmp_path), '--trunk-ref', 'refs/heads/main']) == 0


def _git(root: Path, *args: str) -> None:
    command = [_GIT, '-C', str(root), '-c', 'user.email=t@t', '-c', 'user.name=t', *args]
    subprocess.run(command, check=True, capture_output=True, timeout=60)


def test_a_push_publishing_many_unnamed_merges_does_no_audit_work(tmp_path: Path, monkeypatch) -> None:
    """MERGE-DEVIATIONS-NAMED is checked when a merge is COMMITTED; a push never blocks on it.

    The planted control: twenty unpublished merges, each LOSING a lane's test with no trailer -- the
    exact history the push-time audit refused -- and every audit entry booby-trapped. Lane and
    integration pushes admit; the trunk reads the forge alone.
    """
    _git(tmp_path, 'init', '-q', '-b', 'main')
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests' / 'test_a.py').write_text('def test_a():\n    assert 1\n', encoding='utf-8')
    _git(tmp_path, 'add', '-A')
    _git(tmp_path, 'commit', '-q', '-m', 'base')
    for i in range(20):
        _git(tmp_path, 'checkout', '-q', '-b', f'lane{i}')
        (tmp_path / 'tests' / f'test_l{i}.py').write_text(f'def test_l{i}():\n    assert 1\n', encoding='utf-8')
        _git(tmp_path, 'add', '-A')
        _git(tmp_path, 'commit', '-q', '-m', f'lane {i}')
        _git(tmp_path, 'checkout', '-q', 'main')
        _git(tmp_path, 'commit', '-q', '--allow-empty', '-m', f'main {i}')
        _git(tmp_path, 'merge', '-q', '--no-ff', '--no-commit', f'lane{i}')
        (tmp_path / 'tests' / f'test_l{i}.py').unlink()
        _git(tmp_path, 'add', '-A')
        _git(tmp_path, 'commit', '-q', '-m', f'merge {i}')

    def trap(*_a: object, **_k: object) -> None:
        pytest.fail('a push ran the merge audit')

    for name in ('audit', '_audit', 'unnamed', 'classify'):
        monkeypatch.setattr(mergeaudit, name, trap)
    monkeypatch.setattr(pushgate, 'unprompted_client', lambda _root: None)
    monkeypatch.setattr(pushgate, 'status_list', lambda _client, _sha: [_status('base')])
    base = ['--root', str(tmp_path), '--trunk-ref', 'refs/heads/main']
    for ref in ('refs/heads/feat/x', 'refs/heads/integrate/main', 'refs/heads/main'):
        assert pushgate.main([*base, '--remote-ref', ref]) == 0
