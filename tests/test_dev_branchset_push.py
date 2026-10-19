"""ONE-BRANCH-PER-SESSION at PUSH TIME, driven on a REAL repository and a REAL bare origin.

The incident this answers was not a missing rule -- the rule, its census and its famtests have
existed since 2026-10-04 -- it was a rule whose every enforcement point ran AFTER the push. So the
tests below are about the moment the decision is still open, and they are driven through the REAL
``refusal`` and the REAL shipped script rather than through a restatement of the rule.

THE REFSPEC ARRIVES ON STDIN, git's own pre-push protocol, which the family runner pipes to every
pre-push hook; the module is driven over a real line through ``main``.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from lab_commons.dev.branchset import BranchSet
from lab_commons.dev.branchset_push import (
    ALLOWED,
    COULD_NOT_JUDGE,
    REFUSED,
    PushedRef,
    main,
    pushed_refs,
    refusal,
    undeclared,
)
from lab_commons.dev.githooks.table import base_rows

_GIT = shutil.which('git') or 'git'
_DECLARED = BranchSet(trunk='main', sessions=frozenset({'feat/session', 'integrate/main'}))
_ZERO = '0' * 40
_HEAD = 'a' * 40

_MANIFEST = """[project]
name = "planted"
version = "0"

[tool.lab_commons.branchset]
trunk = "main"
sessions = ["feat/session", "integrate/main"]

[tool.lab_commons.hooks]
"""


def _planted(root: Path) -> Path:
    """A real checkout whose manifest declares the branch set, plus a real bare origin."""
    root.mkdir(parents=True, exist_ok=True)
    (root / 'pyproject.toml').write_text(_MANIFEST, encoding='utf-8')
    subprocess.run([_GIT, 'init', '-q', '-b', 'main', str(root)], check=True, capture_output=True, timeout=60)
    # A family repo commits its lock at the newest resolution, or the base `lock` row refuses the push.
    subprocess.run(
        [shutil.which('uv') or 'uv', 'lock', '--python', sys.executable],
        cwd=root,
        check=True,
        capture_output=True,
        timeout=300,
    )
    subprocess.run([_GIT, 'add', 'pyproject.toml', 'uv.lock'], cwd=root, check=True, capture_output=True, timeout=60)
    subprocess.run(
        [_GIT, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'c1'],
        cwd=root,
        check=True,
        capture_output=True,
        timeout=60,
    )
    return root


def _commit(root: Path, manifest: str) -> str:
    """Commit *manifest* as ``pyproject.toml`` in a repo at *root* (no lock, no hook) and return the sha."""
    root.mkdir(parents=True, exist_ok=True)
    if not (root / '.git').exists():
        subprocess.run([_GIT, 'init', '-q', '-b', 'main', str(root)], check=True, capture_output=True, timeout=60)
    (root / 'pyproject.toml').write_text(manifest, encoding='utf-8')
    subprocess.run([_GIT, 'add', 'pyproject.toml'], cwd=root, check=True, capture_output=True, timeout=60)
    return _commit_staged(root)


def _commit_staged(root: Path) -> str:
    subprocess.run(
        [_GIT, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'c', '--allow-empty'],
        cwd=root,
        check=True,
        capture_output=True,
        timeout=60,
    )
    return _sha(root)


def _sha(root: Path) -> str:
    return subprocess.run(
        [_GIT, 'rev-parse', 'HEAD'], cwd=root, check=True, capture_output=True, text=True, timeout=60
    ).stdout.strip()


def _ref(remote_ref: str, *, deleted: bool = False) -> PushedRef:
    return PushedRef(remote_ref, deleted=deleted)


# ---------------------------------------------------------------------------
# 1. THE RULE, as one expression
# ---------------------------------------------------------------------------


def test_a_declared_branch_is_not_a_violation() -> None:
    """The acquittal half. Without it every assertion below could be met by refusing everything."""
    assert undeclared([_ref('refs/heads/feat/session'), _ref('refs/heads/main')], _DECLARED) == ()


def test_an_undeclared_branch_is_a_violation() -> None:
    assert undeclared([_ref('refs/heads/work/foo')], _DECLARED) == ('work/foo',)


def test_a_deletion_is_never_a_violation() -> None:
    """The guard may not refuse its OWN remedy: the census tells a human to delete these."""
    assert undeclared([_ref('refs/heads/work/foo', deleted=True)], _DECLARED) == ()


def test_a_tag_or_a_machine_ref_is_not_judged() -> None:
    """A tag names a commit judged when its branch was pushed; ``refs/ci/**`` names no branch."""
    refs = [_ref('refs/tags/v1'), _ref('refs/ci/heartbeat/box/1')]
    assert undeclared(refs, _DECLARED) == ()


def test_every_ref_in_a_multi_ref_push_is_judged() -> None:
    """A raw hook is handed EVERY ref; judging only the first would pass the rest."""
    refs = [_ref('refs/heads/feat/session'), _ref('refs/heads/work/one'), _ref('refs/heads/work/two')]
    assert undeclared(refs, _DECLARED) == ('work/one', 'work/two')


# ---------------------------------------------------------------------------
# 2. THE TWO DOORS, and what each one can carry
# ---------------------------------------------------------------------------


def test_stdin_carries_the_refspec_and_the_deletion_flag() -> None:
    """Git's own protocol: four fields per line, and an all-zero local sha means DELETE."""
    lines = [
        f'HEAD {_HEAD} refs/heads/feat/session {_ZERO}',
        f'(delete) {_ZERO} refs/heads/work/foo {_HEAD}',
        f'refs/tags/v1 {_HEAD} refs/tags/v1 {_ZERO}',
        'malformed line with three fields',  # skipped, not crashed on
    ]
    assert pushed_refs(lines) == (
        PushedRef('refs/heads/feat/session', local_sha=_HEAD),
        PushedRef('refs/heads/work/foo', deleted=True, local_sha=_ZERO),
        PushedRef('refs/tags/v1', local_sha=_HEAD),
    )


def test_a_hook_handed_nothing_judges_nothing() -> None:
    """The FLOOR's other side: this is the state the assertion above must be able to tell apart."""
    assert pushed_refs([]) == ()


# ---------------------------------------------------------------------------
# 3. THE DECISION, on a planted checkout
# ---------------------------------------------------------------------------


def test_a_declared_branch_passes_on_a_planted_checkout(tmp_path: Path) -> None:
    root = _planted(tmp_path / 'declared')
    code, text = refusal(root, lines=[f'HEAD {_sha(root)} refs/heads/feat/session {_ZERO}'])
    assert code == ALLOWED, text


def test_an_undeclared_branch_is_refused_and_the_refusal_names_the_remedy(tmp_path: Path) -> None:
    """REFUSAL-NAMES-THE-REMEDY, asserted as such rather than as "it says no"."""
    root = _planted(tmp_path / 'undeclared')
    code, text = refusal(root, lines=[f'HEAD {_sha(root)} refs/heads/work/foo {_ZERO}'])
    assert code == REFUSED
    assert 'work/foo' in text, 'the refusal must name the branch it refuses'
    assert '[tool.lab_commons.branchset]' in text, 'the refusal must name where to declare it'
    assert 'merge' in text, 'the refusal must name what to do with the branch instead'


def test_a_push_that_deletes_an_undeclared_branch_passes(tmp_path: Path) -> None:
    root = _planted(tmp_path / 'delete')
    code, text = refusal(root, lines=[f'(delete) {_ZERO} refs/heads/work/foo {_HEAD}'])
    assert code == ALLOWED, text


def test_a_commit_with_no_declaration_is_refused_rather_than_passed(tmp_path: Path) -> None:
    """The silent-pass shape: a guard that cannot judge must not read as a guard that acquitted."""
    sha = _commit(tmp_path, '[project]\nname = "x"\nversion = "0"\n')
    code, text = refusal(tmp_path, lines=[f'HEAD {sha} refs/heads/work/foo {_ZERO}'])
    assert code == COULD_NOT_JUDGE
    assert sha in text, 'the refusal must name the commit whose declaration it read'
    assert '[tool.lab_commons.branchset]' in text


def test_a_commit_with_no_pyproject_at_all_is_refused_rather_than_passed(tmp_path: Path) -> None:
    _commit(tmp_path, _MANIFEST)
    subprocess.run([_GIT, 'rm', '-q', 'pyproject.toml'], cwd=tmp_path, check=True, capture_output=True, timeout=60)
    sha = _commit_staged(tmp_path)
    code, text = refusal(tmp_path, lines=[f'HEAD {sha} refs/heads/feat/session {_ZERO}'])
    assert code == COULD_NOT_JUDGE, text


def test_the_pushed_commit_declares_the_ref_not_the_pushing_checkout(tmp_path: Path) -> None:
    """The verdict reads the PUSHED commit's declaration, never the pushing checkout's working tree.

    The 2026-10-19 defect: a checkout on ``main`` declaring ``sessions = []`` refused pushing ``integrate/main``
    whose OWN commit declared it -- the verdict depended on which checkout pushed.

    PLANTED CONTROL: the working tree declares the ref while the pushed commit does not, and that push is
    refused -- so the working tree is provably not consulted.
    """
    nothing = '[tool.lab_commons.branchset]\ntrunk = "main"\nsessions = []\n'
    carries = _commit(tmp_path, _MANIFEST)  # declares feat/session and integrate/main
    bare = _commit(tmp_path, nothing)  # HEAD, and the working tree, declare nothing
    line = 'refs/heads/{0} {1} refs/heads/{0} ' + _ZERO
    assert refusal(tmp_path, lines=[line.format('integrate/main', carries)]) == (ALLOWED, '')
    code, text = refusal(tmp_path, lines=[line.format('work/foo', carries)])
    assert code == REFUSED
    assert 'work/foo' in text
    (tmp_path / 'pyproject.toml').write_text(_MANIFEST, encoding='utf-8')  # the tree declares it; the commit not
    code, text = refusal(tmp_path, lines=[line.format('integrate/main', bare)])
    assert code == REFUSED, 'the working tree was consulted instead of the pushed commit'
    assert 'integrate/main' in text


# ---------------------------------------------------------------------------
# 4. THE PLANTED CONTROL: the shipped script, the real hook, a real push
# ---------------------------------------------------------------------------


def _wire_hook(root: Path) -> None:
    """Install the family RUNNER as git's own pre-push hook -- the base table decides what it runs.

    THE INCIDENT THIS SHAPE ANSWERS (2026-10-13): this control used to write ``branchset_push`` into
    the hook BY HAND, so it proved the module and never the wiring -- and the wiring was missing. When
    hooks moved to TOML (2026-10-11) the base table carried no ``branchset-push`` row, every consumer's
    pre-push ran without it, and an agent pushed ten lane branches to origin. What runs here is what
    a consumer's installed shim runs: ``githooks run pre-push`` over the merged base + repo table.
    The interpreter is THIS PROCESS's: a planted checkout has no ``.venv`` of its own.
    """
    hook = root / '.git' / 'hooks' / 'pre-push'
    runner = f'"{Path(sys.executable).as_posix()}" -m lab_commons.dev.githooks run pre-push "$@"'
    hook.write_text(f'#!/usr/bin/env bash\n{runner}\n')
    hook.chmod(0o755)


def test_the_planted_control_pushes_both_ways(tmp_path: Path) -> None:
    """PLANTED-CONTROL: a real ``git push`` to a real bare origin, refused and then allowed.

    Driven through the INSTALLED package rather than through the source path, so what is proven is
    the thing a consumer runs. The push that should pass is asserted FIRST: a hook that refused
    everything would satisfy the refusal alone.
    """
    origin = tmp_path / 'origin.git'
    subprocess.run([_GIT, 'init', '-q', '--bare', str(origin)], check=True, capture_output=True, timeout=60)
    root = _planted(tmp_path / 'control')
    subprocess.run(
        [_GIT, 'remote', 'add', 'origin', str(origin)],
        cwd=root,
        check=True,
        capture_output=True,
        timeout=60,
    )
    _wire_hook(root)

    def push(*refspec: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [_GIT, 'push', 'origin', *refspec],
            cwd=root,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=120,
            check=False,
        )

    subprocess.run([_GIT, 'branch', 'feat/session'], cwd=root, check=True, capture_output=True, timeout=60)
    subprocess.run([_GIT, 'branch', 'work/foo'], cwd=root, check=True, capture_output=True, timeout=60)
    allowed = push('feat/session')  # PUBLISH-IS-THE-LOCAL-REF: a declared branch goes out from its own ref
    assert allowed.returncode == 0, f'the declared branch was refused: {allowed.stderr}'
    refused = push('work/foo')
    assert refused.returncode != 0, 'an undeclared branch was accepted by the real hook'
    assert 'REFUSED' in refused.stderr
    assert 'work/foo' in refused.stderr
    landed = subprocess.run(
        [_GIT, 'ls-remote', '--heads', 'origin'],
        cwd=root,
        capture_output=True,
        text=True,
        encoding='utf-8',
        timeout=60,
        check=True,
    ).stdout
    assert 'refs/heads/work/foo' not in landed, 'the refused branch reached origin anyway'


# ---------------------------------------------------------------------------
# 5. THE WIRING: the family base table, the one place a pre-push check is declared
# ---------------------------------------------------------------------------


def test_the_base_table_runs_the_check_at_pre_push_for_every_consumer() -> None:
    """The row IS the wiring: a consumer opting into the base table gets the check without a line of its own."""
    rows = {row['id']: row for row in base_rows()['pre-push']}
    assert 'branchset-push' in rows, sorted(rows)
    row = rows['branchset-push']
    assert row['run'] == ['python', '-m', 'lab_commons.dev.branchset_push'], row['run']
    assert row.get('always_run'), 'a push that changes no path still moves a ref; the check must run for it'


def test_the_module_refuses_an_undeclared_branch_read_from_stdin(tmp_path: Path) -> None:
    """``main`` reads git's refspec line off stdin and refuses the undeclared branch it names."""
    root = _planted(tmp_path / 'main-door')
    monkeypatched = pytest.MonkeyPatch()
    line = f'refs/heads/work/foo {_sha(root)} refs/heads/work/foo {"0" * 40}\n'
    monkeypatched.setattr(sys, 'stdin', io.StringIO(line))
    monkeypatched.chdir(root)
    try:
        assert main([]) == REFUSED
    finally:
        monkeypatched.undo()


def test_a_kit_older_than_the_checkout_says_rebuild_the_venv_not_unreadable(tmp_path: Path) -> None:
    """A key the installed kit does not know is a NEWER schema: the remedy is the venv, never the manifest.

    PLANTED CONTROL: a declaration missing its trunk is still the unreadable-branch-set refusal.
    """
    newer = '[tool.lab_commons.branchset]\ntrunk = "main"\nsessions = []\nfuture_key = 1\n'
    code, text = refusal(tmp_path, lines=[f'HEAD {_commit(tmp_path, newer)} refs/heads/x {_ZERO}'])
    assert code == COULD_NOT_JUDGE
    assert 'your kit is older than this checkout' in text
    assert 'rebuild' in text
    assert 'readable branch set' not in text
    sha = _commit(tmp_path, '[tool.lab_commons.branchset]\nsessions = []\n')
    assert 'no readable branch set' in refusal(tmp_path, lines=[f'HEAD {sha} refs/heads/x {_ZERO}'])[1]


def test_a_deletion_from_a_stale_commit_passes_and_a_content_push_is_still_judged(tmp_path: Path) -> None:
    """The 2026-10-17 defect: a checkout still declaring the RETIRED ``update`` key refused a deletion.

    A deletion carries no content, so the pushed declaration has nothing to judge. PLANTED CONTROL: the
    same checkout's content push is still refused, naming the key as retired rather than unknown.
    """
    stale = '[tool.lab_commons.branchset]\ntrunk = "main"\nsessions = []\nupdate = "u/l"\n'
    sha = _commit(tmp_path, stale)
    code, text = refusal(tmp_path, lines=[f'(delete) {_ZERO} refs/heads/work/foo {_HEAD}'])
    assert code == ALLOWED, text
    code, text = refusal(tmp_path, lines=[f'HEAD {sha} refs/heads/work/foo {_ZERO}'])
    assert code == COULD_NOT_JUDGE
    assert 'update is retired' in text


def test_a_retired_key_is_named_retired_with_its_remedy_never_unknown(tmp_path: Path) -> None:
    """RETIRED-NAMES-REGISTERED: the branchset ``update`` key is refused as retired; its remedy deletes the key.

    PLANTED CONTROL: a key nobody ever declared is still the kit-older refusal, not a retirement.
    """
    stale = '[tool.lab_commons.branchset]\ntrunk = "main"\nsessions = []\nupdate = "u/l"\n'
    code, text = refusal(tmp_path, lines=[f'HEAD {_commit(tmp_path, stale)} refs/heads/x {_ZERO}'])
    assert code == COULD_NOT_JUDGE
    assert 'update is retired' in text
    assert 'delete the retired key' in text
    assert 'unknown' not in text
    assert 'kit is older' not in text
    sha = _commit(tmp_path, stale.replace('update', 'future_key'))
    assert 'kit is older' in refusal(tmp_path, lines=[f'HEAD {sha} refs/heads/x {_ZERO}'])[1]
