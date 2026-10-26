"""The session-branch invariants, each through a REAL ``git push`` to a bare origin and a REAL pre-push hook.

P2 PUBLISH-IS-THE-LOCAL-REF, P3 SESSION-HISTORY-ONLY-GROWS, P4 INTEGRATION-IS-MERGES-ONLY -- and P1
ONE-WRITER-PER-SESSION-BRANCH, proved to be git's own mechanisms. Every refusal has its planted control: the
same push, made the right way, lands. Names are declared non-defaults (``int/line``, ``stable``, ``feat/s``).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from dev_lab.dev.branchset import branchset_from
from dev_lab.dev.breakglass import notices
from dev_lab.dev.componentbump import LANE
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.metrics import BYPASS, read
from dev_lab.dev.relock import branch_for
from dev_lab.dev.sessionbranch import P2, P3, P5, P6

_GIT = shutil.which('git') or 'git'
_DECL = (
    "[tool.lab_commons.branchset]\ntrunk = 'stable'\nsessions = ['int/line', 'feat/s']\n\n"
    "[tool.lab_commons.integrator]\nintegration = 'int/line'\ntrunk = 'stable'\n"
)
_TEST = 'def test_a():\n    assert True\n\n\ndef test_b():\n    assert 1\n'


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        [_GIT, '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'core.hooksPath=', *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=True,
        timeout=60,
    )
    return done.stdout.strip()


def _push(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """``git push origin <args>`` through the installed pre-push hook."""
    return subprocess.run(
        [_GIT, 'push', 'origin', *args],
        check=False,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=120,
    )


def _remote(cwd: Path, branch: str) -> str:
    out = _git(cwd, 'ls-remote', 'origin', f'refs/heads/{branch}')
    return out.split()[0] if out else ''


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A clone of origin with the three declared branches published, the hook installed."""
    origin = tmp_path / 'origin.git'
    _git(tmp_path, 'init', '--bare', '-b', 'stable', str(origin))
    work = tmp_path / 'work'
    _git(tmp_path, 'clone', str(origin), str(work))
    (work / 'pyproject.toml').write_text(_DECL, encoding='utf-8')
    (work / 'tests').mkdir()
    (work / 'tests' / 'test_a.py').write_text(_TEST, encoding='utf-8')
    _git(work, 'checkout', '-b', 'stable')
    _git(work, 'add', '.')
    _git(work, 'commit', '-m', 'chore: seed')
    for branch in ('int/line', 'feat/s', 'lane/x'):
        _git(work, 'branch', branch)
    _git(work, 'push', 'origin', 'stable', 'int/line', 'feat/s')
    hooks = tmp_path / 'hooks'
    hooks.mkdir()
    python = Path(sys.executable).as_posix()
    (hooks / 'pre-push').write_text(
        f'#!/bin/sh\nexec "{python}" -m dev_lab.dev.sessionbranch "$@"\n', encoding='utf-8', newline='\n'
    )
    (hooks / 'pre-push').chmod(0o755)
    _git(work, 'config', 'core.hooksPath', hooks.as_posix())
    _git(work, 'config', 'user.name', 't')
    _git(work, 'config', 'user.email', 't@t')
    return work


# --- P2 PUBLISH-IS-THE-LOCAL-REF --------------------------------------------------------------------


@pytest.mark.parametrize('spec', ['HEAD:feat/s', 'lane/x:feat/s', 'HEAD:int/line'])
def test_a_session_branch_published_from_another_ref_is_refused(repo: Path, spec: str) -> None:
    _git(repo, 'checkout', 'lane/x')
    _git(repo, 'commit', '--allow-empty', '-m', 'feat: unreviewed')
    done = _push(repo, spec)
    assert done.returncode != 0, done.stderr
    assert 'PUBLISH-IS-THE-LOCAL-REF' in done.stderr
    assert _remote(repo, spec.split(':')[1]) != _git(repo, 'rev-parse', 'HEAD')


def test_a_detached_head_is_refused_and_the_branchs_own_ref_lands(repo: Path) -> None:
    _git(repo, 'checkout', 'feat/s')
    _git(repo, 'commit', '--allow-empty', '-m', 'feat: s')
    _git(repo, 'checkout', '--detach')
    assert 'PUBLISH-IS-THE-LOCAL-REF' in _push(repo, 'HEAD:feat/s').stderr
    _git(repo, 'checkout', 'feat/s')
    done = _push(repo, 'HEAD:feat/s')
    assert done.returncode == 0, done.stderr
    assert _remote(repo, 'feat/s') == _git(repo, 'rev-parse', 'feat/s')


def test_a_branch_needs_no_checkout_to_be_published(repo: Path) -> None:
    """Not bound to a directory: ``git push origin feat/s`` from a checkout on another branch lands."""
    _git(repo, 'branch', '-f', 'feat/s', _git(repo, 'commit-tree', 'stable^{tree}', '-p', 'stable', '-m', 'feat: s'))
    _git(repo, 'checkout', 'lane/x')
    done = _push(repo, 'feat/s')
    assert done.returncode == 0, done.stderr


# --- P3 SESSION-HISTORY-ONLY-GROWS ------------------------------------------------------------------


def test_a_rewritten_session_branch_is_refused_even_forced(repo: Path) -> None:
    _git(repo, 'checkout', 'feat/s')
    _git(repo, 'commit', '--allow-empty', '-m', 'feat: one')
    assert _push(repo, 'feat/s').returncode == 0
    _git(repo, 'commit', '--amend', '--allow-empty', '-m', 'feat: one, rewritten')
    done = _push(repo, '--force', 'feat/s')
    assert done.returncode != 0
    assert 'SESSION-HISTORY-ONLY-GROWS' in done.stderr


def test_deleting_a_session_branch_is_refused(repo: Path) -> None:
    done = _push(repo, ':feat/s')
    assert done.returncode != 0
    assert 'SESSION-HISTORY-ONLY-GROWS' in done.stderr
    assert _remote(repo, 'feat/s')


def test_a_deletion_reads_the_branch_set_from_head_never_the_deleted_tip(repo: Path) -> None:
    """A deletion pushes no content: the deleted ref's old tip predating the table cannot refuse it.

    PLANTED control: the same HEAD declaration still refuses deleting a declared session branch.
    """
    empty = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'  # git's empty tree: no pyproject.toml at all
    _git(repo, 'branch', 'old/x', _git(repo, 'commit-tree', empty, '-m', 'chore: predates the table'))
    _git(repo.parent / 'origin.git', 'fetch', str(repo), 'old/x:refs/heads/old/x')
    assert _remote(repo, 'old/x')
    done = _push(repo, '--delete', 'old/x')
    assert done.returncode == 0, done.stderr
    assert not _remote(repo, 'old/x')
    refused = _push(repo, '--delete', 'feat/s')
    assert P3 in refused.stderr
    assert _remote(repo, 'feat/s')


def test_a_deletion_is_judged_by_the_integration_branch_never_a_stale_checkout(repo: Path) -> None:
    """The 2026-10-17 defect: a checkout whose manifest still declares a RETIRED key cannot judge a deletion.

    A deletion carries no content, so ``origin/<integration>``'s declaration judges it. PLANTED controls: the
    same stale checkout still cannot delete a session branch, and a CONTENT push of the stale tip is judged by
    that tip -- refused, naming the retired key.
    """
    _git(repo, 'checkout', '-b', 'old/x')
    stale = _DECL.replace("sessions = ['int/line', 'feat/s']", "sessions = ['int/line', 'feat/s']\nupdate = 'u/l'")
    (repo / 'pyproject.toml').write_text(stale, encoding='utf-8')
    _git(repo, 'commit', '-am', 'chore: a manifest from before the retirement')
    _git(repo.parent / 'origin.git', 'fetch', str(repo), 'old/x:refs/heads/old/x')
    done = _push(repo, '--delete', 'old/x')
    assert done.returncode == 0, done.stderr
    assert not _remote(repo, 'old/x')
    refused = _push(repo, '--delete', 'feat/s')
    assert P3 in refused.stderr
    assert _remote(repo, 'feat/s')
    _git(repo, 'branch', '-f', 'feat/s', 'HEAD')
    content = _push(repo, 'feat/s')
    assert content.returncode != 0
    assert 'update is retired' in content.stderr
    assert _remote(repo, 'feat/s') != _git(repo, 'rev-parse', 'HEAD')


# --- P4 INTEGRATION-IS-MERGES-ONLY ------------------------------------------------------------------


def _merge(repo: Path, branch: str, message: str) -> str:
    """A two-parent commit of ``int/line`` and *branch* on the merged tree, moved onto ``int/line``."""
    tree = _git(repo, 'merge-tree', '--write-tree', 'int/line', branch).splitlines()[0]
    sha = _git(repo, 'commit-tree', tree, '-p', 'int/line', '-p', branch, '-m', message)
    _git(repo, 'branch', '-f', 'int/line', sha)
    return sha


def test_a_plain_commit_on_the_integration_branch_is_refused(repo: Path) -> None:
    _git(repo, 'checkout', 'int/line')
    _git(repo, 'commit', '--allow-empty', '-m', 'feat: straight onto integration')
    done = _push(repo, 'int/line')
    assert done.returncode != 0
    assert 'INTEGRATION-IS-MERGES-ONLY' in done.stderr
    assert 'not a merge' in done.stderr


def test_a_merge_naming_its_branch_lands_and_one_naming_none_is_refused(repo: Path) -> None:
    _git(repo, 'checkout', 'lane/x')
    (repo / 'x.txt').write_text('x\n', encoding='utf-8')
    _git(repo, 'add', 'x.txt')
    _git(repo, 'commit', '-m', 'feat: x')
    _git(repo, 'checkout', 'stable')
    _merge(repo, 'lane/x', 'chore(merge): lane/x into int/line')
    done = _push(repo, 'int/line')
    assert done.returncode != 0
    assert 'Merged-Branch' in done.stderr
    _git(repo, 'branch', '-f', 'int/line', 'int/line^1')
    _merge(repo, 'lane/x', 'chore(merge): lane/x into int/line\n\nMerged-Branch: lane/x\n')
    done = _push(repo, 'int/line')
    assert done.returncode == 0, done.stderr


def test_a_merge_that_loses_a_test_unnamed_is_refused_and_lands_once_named(repo: Path) -> None:
    _git(repo, 'checkout', 'lane/x')
    (repo / 'tests' / 'test_a.py').write_text('def test_a():\n    assert True\n', encoding='utf-8')
    _git(repo, 'commit', '-am', 'test: drop b')
    _git(repo, 'checkout', 'feat/s')
    (repo / 'feat.txt').write_text('f\n', encoding='utf-8')
    _git(repo, 'add', 'feat.txt')
    _git(repo, 'commit', '-m', 'feat: f')
    _git(repo, 'checkout', 'stable')
    base = _git(repo, 'rev-parse', 'int/line')
    message = 'chore(merge): feat/s into int/line\n\nMerged-Branch: feat/s\n'
    lost = _git(repo, 'commit-tree', 'lane/x^{tree}', '-p', base, '-p', 'feat/s', '-m', message)
    _git(repo, 'branch', '-f', 'int/line', lost)
    done = _push(repo, 'int/line')
    assert done.returncode != 0
    assert 'LOST test_b' in done.stderr
    named = message + 'Merge-Audit: LOST test_b -- dropped on purpose\n'
    _git(
        repo,
        'branch',
        '-f',
        'int/line',
        _git(repo, 'commit-tree', 'lane/x^{tree}', '-p', base, '-p', 'feat/s', '-m', named),
    )
    done = _push(repo, 'int/line')
    assert done.returncode == 0, done.stderr


def test_creating_the_integration_branch_judges_only_commits_after_the_declared_start(
    repo: Path, tmp_path: Path
) -> None:
    _git(tmp_path / 'origin.git', 'update-ref', '-d', 'refs/heads/int/line')
    _git(repo, 'checkout', 'stable')
    done = _push(repo, 'int/line')
    assert done.returncode != 0
    assert 'merges_only_since' in done.stderr
    seed = _git(repo, 'rev-parse', 'stable')
    _git(repo, 'checkout', 'lane/x')
    text = (repo / 'pyproject.toml').read_text(encoding='utf-8')
    (repo / 'pyproject.toml').write_text(text + f"merges_only_since = '{seed}'\n", encoding='utf-8')
    _git(repo, 'commit', '-am', 'chore: start INTEGRATION-IS-MERGES-ONLY at the seed')
    message = 'chore(merge): lane/x into int/line\n\nMerged-Branch: lane/x\n'
    merge = _git(repo, 'commit-tree', 'lane/x^{tree}', '-p', seed, '-p', 'lane/x', '-m', message)
    _git(repo, 'branch', '-f', 'int/line', merge)
    _git(repo, 'checkout', 'stable')
    done = _push(repo, 'int/line')
    assert done.returncode == 0, done.stderr


def test_a_push_is_judged_by_its_pushed_tip_never_the_working_tree(repo: Path) -> None:
    """PLANTED: a working tree holding garbage and a retired key changes no verdict either way."""
    (repo / 'pyproject.toml').write_text(
        'this is [not toml\n[tool.lab_commons.integrator]\nhost = "G"\n', encoding='utf-8'
    )
    _git(repo, 'branch', '-f', 'feat/s', _git(repo, 'commit-tree', 'stable^{tree}', '-p', 'feat/s', '-m', 'feat: s'))
    done = _push(repo, 'feat/s')
    assert done.returncode == 0, done.stderr
    _git(
        repo, 'branch', '-f', 'lane/x', _git(repo, 'commit-tree', 'stable^{tree}', '-p', 'feat/s', '-m', 'feat: other')
    )
    refused = _push(repo, 'lane/x:feat/s')
    assert P2 in refused.stderr, 'the guard still judges, from the pushed tip'


def test_two_sessions_in_two_worktrees_of_one_repo_on_one_host_never_share_a_writer(repo: Path, tmp_path: Path) -> None:
    """ONE-WRITER-PER-SESSION-BRANCH is git's own: one checkout per branch locally, compare-and-swap remotely."""
    _git(repo, 'checkout', 'stable')
    first, second = tmp_path / 'wt-a', tmp_path / 'wt-b'
    _git(repo, 'worktree', 'add', str(first), 'feat/s')
    taken = subprocess.run(
        [_GIT, 'worktree', 'add', str(second), 'feat/s'],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
    )
    assert taken.returncode != 0, 'a second worktree checked out a branch another session holds'
    _git(repo, 'worktree', 'add', str(second), 'lane/x')
    _git(second, 'commit', '--allow-empty', '-m', 'feat: the other session')
    assert _push(second, 'lane/x:feat/s').returncode != 0, 'publishing onto the other session branch'
    other = tmp_path / 'other-host'
    _git(tmp_path, 'clone', '-q', '-b', 'feat/s', str(tmp_path / 'origin.git'), str(other))
    _git(other, 'commit', '--allow-empty', '-m', 'feat: a clone that went first')
    assert (
        subprocess.run([_GIT, 'push', 'origin', 'feat/s'], cwd=other, capture_output=True, check=False).returncode == 0
    )
    _git(first, 'commit', '--allow-empty', '-m', 'feat: on a stale tip')
    stale = _push(first, 'feat/s')
    assert stale.returncode != 0, 'a stale tip overwrote the other writer'
    assert P3 in stale.stderr, 'git hands the hook the real remote tip: the stale push is judged before it is sent'
    assert P3 in _push(first, '--force', 'feat/s').stderr, 'the force that would bypass it'
    _git(first, 'pull', '-q', '--no-rebase', '--no-edit', 'origin', 'feat/s')
    landed = _push(first, 'feat/s')
    assert landed.returncode == 0, landed.stderr


# --- P5 INTEGRATION-TAKES-ONLY-FORGE-MERGES ---------------------------------------------------------


def test_with_forge_merges_declared_even_an_audited_merge_push_is_refused(repo: Path, tmp_path: Path) -> None:
    """Integration moves only by the forge's server-side PR merge; a client push adding any commit is refused.

    PLANTED controls: the SAME audited merge lands when the declaration is absent (P4 alone); and once the
    forge's merge is on origin, pushing the integration branch at that tip adds nothing and passes.
    """
    seed = _git(repo, 'rev-parse', 'stable')
    _git(repo, 'checkout', 'lane/x')
    (repo / 'x.txt').write_text('x\n', encoding='utf-8')
    _git(repo, 'add', 'x.txt')
    _git(repo, 'commit', '-m', 'feat: x')
    _git(repo, 'checkout', 'stable')
    message = 'chore(merge): lane/x into int/line\n\nMerged-Branch: lane/x\n'
    control = _merge(repo, 'lane/x', message)
    assert _push(repo, 'int/line').returncode == 0, 'P4 alone admits the audited merge'
    _git(repo, 'checkout', 'lane/x')
    text = (repo / 'pyproject.toml').read_text(encoding='utf-8')
    (repo / 'pyproject.toml').write_text(text + f"pr_merges_since = '{seed}'\n", encoding='utf-8')
    _git(repo, 'commit', '-am', 'chore: integration takes only forge merges')
    _git(repo, 'checkout', 'stable')
    refused_sha = _merge(repo, 'lane/x', message.replace('lane/x into', 'lane/x again into'))
    done = _push(repo, 'int/line')
    assert done.returncode != 0
    assert P5 in done.stderr
    assert _remote(repo, 'int/line') == control
    origin = tmp_path / 'origin.git'
    _git(repo, 'push', 'origin', f'{refused_sha}:refs/forge/merged')  # the objects reach the forge ...
    _git(origin, 'update-ref', 'refs/heads/int/line', refused_sha)  # ... and it merges server-side
    _git(repo, 'fetch', 'origin')
    passed = _push(repo, 'int/line')
    assert passed.returncode == 0, passed.stderr


def _forge_merges_declared(repo: Path) -> str:
    """Declare ``pr_merges_since`` at the seed and publish it as the forge would (no hook); the new tip."""
    seed = _git(repo, 'rev-parse', 'stable')
    text = (repo / 'pyproject.toml').read_text(encoding='utf-8')
    (repo / 'pyproject.toml').write_text(text + f"pr_merges_since = '{seed}'\n", encoding='utf-8')
    _git(repo, 'commit', '-am', 'chore: integration takes only forge merges')
    _git(repo, 'branch', '-f', 'int/line', 'stable')
    _git(repo, 'push', 'origin', 'int/line')
    _git(repo, 'checkout', 'int/line')
    return _git(repo, 'rev-parse', 'HEAD')


@pytest.mark.parametrize(
    ('messages', 'admitted'),
    [
        (['fix: hot'], False),  # PLANTED: no trailer
        (['fix: hot\n\nBreak-Glass:'], False),  # an empty reason
        (['fix: a\n\nBreak-Glass: forge down', 'fix: b'], False),  # one new commit without it
        (['fix: a\n\nBreak-Glass: forge down', 'fix: b\n\nBreak-Glass: auto-merge broken'], True),
    ],
)
def test_break_glass_admits_a_direct_push_only_when_every_new_commit_names_its_reason(
    repo: Path, messages: list[str], *, admitted: bool
) -> None:
    """The one bypass of P5: a non-empty ``Break-Glass:`` trailer on EVERY new first-parent commit."""
    before = _forge_merges_declared(repo)
    for n, message in enumerate(messages):
        (repo / f'hot{n}.txt').write_text('x\n', encoding='utf-8')
        _git(repo, 'add', '.')
        _git(repo, 'commit', '-m', message)
    done = _push(repo, 'int/line')
    assert (done.returncode == 0) is admitted, done.stderr
    assert _remote(repo, 'int/line') == (_git(repo, 'rev-parse', 'HEAD') if admitted else before)
    assert [line['lab.rule.id'] for line in read(BYPASS, root=repo)] == (['session-branch'] if admitted else [])
    if not admitted:
        assert P5 in done.stderr
        assert 'Break-Glass: <reason>' in done.stderr


def test_every_break_glass_commit_past_the_declared_start_is_one_notice_naming_its_reason(repo: Path) -> None:
    """The bypass stays visible: one integration notice per break-glass commit. PLANTED: a plain one is none."""
    _forge_merges_declared(repo)
    _git(repo, 'commit', '--allow-empty', '-m', 'fix: plain')
    _git(repo, 'commit', '--allow-empty', '-m', 'fix: hot\n\nBreak-Glass: forge down since 09:00')
    glass = _git(repo, 'rev-parse', 'HEAD')
    _git(repo, 'push', 'origin', 'int/line')
    _git(repo, 'fetch', 'origin')
    (one,) = notices(repo, load_policy(repo), 'o/r')
    assert glass[:12] in one.subject
    assert 'forge down since 09:00' in one.body
    assert f'by {_git(repo, "log", "-1", "--format=%an")}' in one.body  # who, beside why
    assert one.kind == 'integration'


@pytest.mark.parametrize('spec', ['lane/x:lane/y', 'HEAD:lane/y'])
def test_any_branch_published_under_another_name_is_refused(repo: Path, spec: str) -> None:
    """P2 covers EVERY branch: a lane tracking another name never lands there by a bare push."""
    _git(repo, 'checkout', 'lane/x')
    _git(repo, 'commit', '--allow-empty', '-m', 'feat: x')
    done = _push(repo, spec)
    assert done.returncode != 0, done.stderr
    assert P2 in done.stderr
    assert _remote(repo, 'lane/y') == ''


def test_a_branch_lands_under_its_own_name_and_a_detached_tip_under_any(repo: Path) -> None:
    """PLANTED CONTROL: a pr/ branch pushed as itself lands; a detached machine push (relock) is not a branch."""
    _git(repo, 'checkout', '-b', 'pr/x', 'lane/x')
    _git(repo, 'commit', '--allow-empty', '-m', 'feat: x')
    assert _push(repo, 'pr/x').returncode == 0
    _git(repo, 'checkout', '--detach')
    done = _push(repo, 'HEAD:refs/heads/pr/relock-x')
    assert done.returncode == 0, done.stderr


# --- P6 ORIGIN-HOLDS-ONLY-DECLARED-BRANCHES ---------------------------------------------------------


def test_a_fan_out_branch_pushed_as_itself_is_refused_naming_the_declaration_and_the_remedy(repo: Path) -> None:
    _git(repo, 'checkout', 'lane/x')
    _git(repo, 'commit', '--allow-empty', '-m', 'feat: x')
    done = _push(repo, 'lane/x')
    assert done.returncode != 0, done.stderr
    assert P6 in done.stderr
    for named in ('lane/x', 'feat/s', 'int/line', 'stable', 'pr/*', 'pr/<feature>', 'keep lane/x local'):
        assert named in done.stderr
    assert _remote(repo, 'lane/x') == ''


def test_a_detached_machine_push_outside_the_namespaces_is_refused(repo: Path) -> None:
    _git(repo, 'checkout', '--detach')
    done = _push(repo, 'HEAD:refs/heads/relock/x')
    assert P6 in done.stderr
    assert _remote(repo, 'relock/x') == ''


def test_an_existing_undeclared_origin_branch_takes_no_new_push_but_may_be_deleted(repo: Path) -> None:
    """Origin's existing junk is untouched by the rule: an update is refused, a deletion is P3's business."""
    _git(repo.parent / 'origin.git', 'fetch', str(repo), 'lane/x:refs/heads/lane/x')
    _git(repo, 'checkout', 'lane/x')
    _git(repo, 'commit', '--allow-empty', '-m', 'feat: x')
    assert P6 in _push(repo, 'lane/x').stderr
    assert _remote(repo, 'lane/x') != _git(repo, 'rev-parse', 'HEAD')
    done = _push(repo, '--delete', 'lane/x')
    assert done.returncode == 0, done.stderr
    assert _remote(repo, 'lane/x') == ''


def test_a_tag_push_is_not_judged(repo: Path) -> None:
    _git(repo, 'tag', 'v0.1.0')
    done = _push(repo, 'refs/tags/v0.1.0')
    assert done.returncode == 0, done.stderr


def test_the_namespace_is_the_declaration_the_pushed_tip_carries(repo: Path) -> None:
    """A tip declaring ``ephemeral = ['bot/*']`` admits bot/x and no longer pr/x."""
    _git(repo, 'checkout', '-b', 'bot/x', 'lane/x')
    (repo / 'pyproject.toml').write_text(
        _DECL.replace("'feat/s']\n", "'feat/s']\nephemeral = ['bot/*']\n"), encoding='utf-8'
    )
    _git(repo, 'commit', '-am', 'chore: bot namespace')
    done = _push(repo, 'bot/x')
    assert done.returncode == 0, done.stderr
    _git(repo, 'checkout', '-b', 'pr/y')
    assert P6 in _push(repo, 'pr/y').stderr


def test_the_declared_branches_land(repo: Path) -> None:
    """PLANTED CONTROL: the trunk and every session branch are origin's by declaration."""
    _git(repo, 'checkout', 'feat/s')
    _git(repo, 'commit', '--allow-empty', '-m', 'feat: s')
    _git(repo, 'checkout', 'stable')
    _git(repo, 'merge', '--ff-only', 'feat/s')
    done = _push(repo, 'feat/s', 'stable')
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize('branch', [LANE, branch_for('lab-commons', 'a' * 40), 'integrate/main', 'main'])
def test_every_machine_pusher_targets_a_branch_the_family_default_admits(branch: str) -> None:
    """The forge's own pushers (component bump, relock; autosync pushes only pr/ heads) and the declared pair."""
    declared = branchset_from("[tool.lab_commons.branchset]\ntrunk = 'main'\nsessions = ['integrate/main']\n", 'p')
    assert declared.admits(branch)
