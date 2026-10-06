"""ONE-BRANCH-PER-SESSION at PUSH TIME, driven on a REAL repository and a REAL bare origin.

The incident this answers was not a missing rule -- the rule, its census and its famtests have
existed since 2026-10-04 -- it was a rule whose every enforcement point ran AFTER the push. So the
tests below are about the moment the decision is still open, and they are driven through the REAL
``refusal`` and the REAL shipped script rather than through a restatement of the rule.

BOTH DOORS ARE COVERED, because they are different mechanisms and only one of them is the one the
family wires up: a raw hook gets git's refspec on stdin (measured on a real push), and a pre-commit
hook gets an empty stdin and ``PRE_COMMIT_REMOTE_BRANCH`` instead. A test that covered one and
assumed the other would have said nothing about the door the four repos actually push through.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from lab_commons.dev import githooks
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
from lab_commons.dev.githooks import HOOK, PYTHON_ENV, hook_path, kind, run_hook

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
"""


def _planted(root: Path) -> Path:
    """A real checkout whose manifest declares the branch set, plus a real bare origin."""
    root.mkdir(parents=True, exist_ok=True)
    (root / 'pyproject.toml').write_text(_MANIFEST, encoding='utf-8')
    subprocess.run([_GIT, 'init', '-q', '-b', 'main', str(root)], check=True, capture_output=True, timeout=60)
    subprocess.run([_GIT, 'add', 'pyproject.toml'], cwd=root, check=True, capture_output=True, timeout=60)
    subprocess.run(
        [_GIT, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'c1'],
        cwd=root,
        check=True,
        capture_output=True,
        timeout=60,
    )
    return root


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
        _ref('refs/heads/feat/session'),
        _ref('refs/heads/work/foo', deleted=True),
        _ref('refs/tags/v1'),
    )


def test_the_environment_door_is_the_pre_commit_one() -> None:
    """MEASURED: under pre-commit stdin reads EOF and only this variable names the ref."""
    assert pushed_refs([], {'PRE_COMMIT_REMOTE_BRANCH': 'refs/heads/work/bar'}) == (_ref('refs/heads/work/bar'),)


def test_stdin_wins_over_the_environment() -> None:
    """A raw hook is handed several refs; the environment names at most one. Order matters."""
    environ = {'PRE_COMMIT_REMOTE_BRANCH': 'refs/heads/feat/session'}
    lines = [f'HEAD {_HEAD} refs/heads/work/foo {_ZERO}']
    assert pushed_refs(lines, environ) == (_ref('refs/heads/work/foo'),)


def test_a_hook_handed_nothing_judges_nothing() -> None:
    """The FLOOR's other side: this is the state the assertion above must be able to tell apart."""
    assert pushed_refs([], {}) == ()


# ---------------------------------------------------------------------------
# 3. THE DECISION, on a planted checkout
# ---------------------------------------------------------------------------


def test_a_declared_branch_passes_on_a_planted_checkout(tmp_path: Path) -> None:
    root = _planted(tmp_path / 'declared')
    code, text = refusal(root, lines=[f'HEAD {_HEAD} refs/heads/feat/session {_ZERO}'])
    assert code == ALLOWED, text


def test_an_undeclared_branch_is_refused_and_the_refusal_names_the_remedy(tmp_path: Path) -> None:
    """REFUSAL-NAMES-THE-REMEDY, asserted as such rather than as "it says no"."""
    root = _planted(tmp_path / 'undeclared')
    code, text = refusal(root, lines=[f'HEAD {_HEAD} refs/heads/work/foo {_ZERO}'])
    assert code == REFUSED
    assert 'work/foo' in text, 'the refusal must name the branch it refuses'
    assert '[tool.lab_commons.branchset]' in text, 'the refusal must name where to declare it'
    assert 'merge' in text, 'the refusal must name what to do with the branch instead'


def test_a_push_that_deletes_an_undeclared_branch_passes(tmp_path: Path) -> None:
    root = _planted(tmp_path / 'delete')
    code, text = refusal(root, lines=[f'(delete) {_ZERO} refs/heads/work/foo {_HEAD}'])
    assert code == ALLOWED, text


def test_a_checkout_with_no_declaration_is_refused_rather_than_passed(tmp_path: Path) -> None:
    """The silent-pass shape: a guard that cannot judge must not read as a guard that acquitted."""
    root = tmp_path / 'bare-of-declaration'
    root.mkdir()
    (root / 'pyproject.toml').write_text('[project]\nname = "x"\nversion = "0"\n', encoding='utf-8')
    code, text = refusal(root, lines=[f'HEAD {_HEAD} refs/heads/work/foo {_ZERO}'])
    assert code == COULD_NOT_JUDGE
    assert 'branchset' in text


# ---------------------------------------------------------------------------
# 4. THE PLANTED CONTROL: the shipped script, the real hook, a real push
# ---------------------------------------------------------------------------


def _wire_hook(root: Path) -> None:
    """Install the SHIPPED script as git's own pre-push hook, the way a consumer's git calls it.

    The interpreter is THIS PROCESS's (``sys.executable``), not one resolved from ``PATH``: the test
    runs in the environment that can import ``lab_commons``, and a hook wired to a different one
    would refuse the declared branch for a reason that has nothing to do with the rule -- which is
    precisely the misattribution ``branchset-push.sh``'s own header refuses to make.
    """
    hook = root / '.git' / 'hooks' / 'pre-push'
    hook.write_text(f'#!/usr/bin/env bash\n"{sys.executable}" -m lab_commons.dev.branchset_push\n')
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
            timeout=120,
            check=False,
        )

    allowed = push('HEAD:refs/heads/feat/session')
    assert allowed.returncode == 0, f'the declared branch was refused: {allowed.stderr}'
    refused = push('HEAD:refs/heads/work/foo')
    assert refused.returncode != 0, 'an undeclared branch was accepted by the real hook'
    assert 'REFUSED' in refused.stderr
    assert 'work/foo' in refused.stderr
    landed = subprocess.run(
        [_GIT, 'ls-remote', '--heads', 'origin'],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout
    assert 'refs/heads/work/foo' not in landed, 'the refused branch reached origin anyway'


# ---------------------------------------------------------------------------
# 5. THE HANDSHAKE, and the registry the hook has to be in to be wired at all
# ---------------------------------------------------------------------------


def test_the_hook_is_registered_and_shipped() -> None:
    """A hook the registry does not name cannot be wired: ``--list`` is how a consumer finds it."""
    shipped = set(githooks.SCRIPTS)
    assert 'branchset-push' in shipped, shipped
    assert kind('branchset-push') == HOOK
    assert hook_path('branchset-push').is_file()


def test_the_dispatcher_hands_the_hook_its_own_interpreter(tmp_path: Path) -> None:
    """LAB_PYTHON is what stops a shipped script guessing an interpreter from PATH."""
    code = run_hook('branchset-push', cwd=tmp_path)
    # The planted checkout above has no manifest here, so the hook REFUSES; what this asserts is
    # that it RAN and reached its own module -- exit 2, not a bash "command not found" and not 0.
    assert code in {REFUSED, COULD_NOT_JUDGE}, f'the shipped script did not reach its module: rc={code}'
    assert PYTHON_ENV == 'LAB_PYTHON'


def test_the_module_refuses_when_it_is_handed_nothing_on_stdin(tmp_path: Path) -> None:
    """``main`` over an empty stdin and a pre-commit environment still judges the checkout.

    The stdin is a STRING, not the terminal and not pytest's captured stream: ``main`` reads the
    refspec from stdin by design, and handing it a real one here is what exercises the environment
    door rather than the read.
    """
    root = _planted(tmp_path / 'main-door')
    monkeypatched = pytest.MonkeyPatch()
    monkeypatched.setenv('PRE_COMMIT_REMOTE_BRANCH', 'refs/heads/work/foo')
    monkeypatched.setattr(sys, 'stdin', io.StringIO(''))
    monkeypatched.chdir(root)
    try:
        assert main([]) == REFUSED
    finally:
        monkeypatched.undo()
