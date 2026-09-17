"""The shipped hook payload, and the properties the wdg-lab fork did not have.

WHY THESE ARMS AND NOT OTHERS. Every arm below is a difference MEASURED between the two copies of
``bump-version.sh`` that existed on 2026-09-16 (motronics-studio's 134-line version and wdg-lab's
27-line one), plus the one property that makes the shared file shareable -- that it takes its
repo-specific decisions from the environment. A test that only proved "the script runs" would pass
over every one of them.

THE REACHABILITY HALF IS AS IMPORTANT AS THE BEHAVIOUR HALF. A "shared" script each repo copies is
the fork it claims to remove, so :func:`test_the_hook_resolves_through_the_installed_package` pins
that the payload is reached by NAME through the installed package rather than by a path a consumer
wrote down.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from lab_commons.dev import githooks

GIT = shutil.which('git')

# ASSERTED AT MODULE SCOPE RATHER THAN SKIPPED: this family's hooks all start with `bash`, so a box
# without bash or git runs no hooks at all -- a finding, not a reason to report green.
assert GIT is not None, 'no git on this box; nothing in this family can be verified here'
BASH = githooks.bash_executable()


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        [GIT, '-c', 'user.email=t@example.invalid', '-c', 'user.name=t', *args],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real single-commit git repo on ``main``, with no remote that resolves."""
    root = tmp_path / 'r'
    root.mkdir()
    _git(root, 'init', '-b', 'main')
    (root / 'f.txt').write_text('x', encoding='utf-8')
    _git(root, 'add', '-A')
    _git(root, 'commit', '-m', 'feat: seed')
    _git(root, 'remote', 'add', 'origin', str(tmp_path / 'nonexistent-remote.git'))
    return root


def _run(repo: Path, **env_overrides: str) -> subprocess.CompletedProcess[str]:
    import os  # noqa: PLC0415 -- only this helper needs the ambient environment

    env = {**os.environ, 'LAB_BUMP_RELEASE_BRANCH': 'main', **env_overrides}
    return subprocess.run(
        [BASH, str(githooks.hook_path('bump-version')), 'origin'],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        # THE TIMEOUT IS THE ASSERTION for the hang arm: if the hook waits on a credential prompt
        # this must fail rather than take the worker down with it.
        timeout=180,
        env=env,
    )


def test_the_hook_resolves_through_the_installed_package() -> None:
    """The reachability property: a NAME, resolved by the running interpreter, not a written path."""
    assert 'bump-version' in githooks.HOOKS
    path = githooks.hook_path('bump-version')
    assert path.is_file()
    assert path.parent == Path(githooks.__file__).resolve().parent, 'the payload must ship inside the package'
    printed = subprocess.run(
        [sys.executable, '-m', 'lab_commons.dev.githooks', '--path', 'bump-version'],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    ).stdout.strip()
    assert Path(printed) == path


def test_a_hook_this_package_does_not_ship_is_refused() -> None:
    """The floor on the lookup: a typo must NAME what is shipped, never silently resolve."""
    with pytest.raises(githooks.HookNotShipped) as caught:
        githooks.hook_path('no-such-hook')
    assert 'bump-version' in str(caught.value), 'the refusal must name the shipped set'


@pytest.mark.parametrize(('key', 'value'), [('GIT_TERMINAL_PROMPT', '0'), ('GCM_INTERACTIVE', 'never')])
def test_the_hook_makes_a_credential_prompt_impossible(key: str, value: str) -> None:
    """Asserted AT THE SOURCE, because a file:// remote never asks for credentials.

    A caller that happened to export these would make the hook look safe while leaving it unsafe for
    every other caller, so the scope claim is checked where the scope is. Both doors, because they
    are different mechanisms: git's own terminal prompt, and Git Credential Manager's GUI, which no
    terminal setting reaches and which is the one that fires on Windows.
    """
    src = githooks.hook_path('bump-version').read_text(encoding='utf-8')
    assert f'{key}={value}' in src


def test_a_topic_branch_mints_no_tag(repo: Path) -> None:
    """The namespace guard the fork lacked: only the release branch may mint a release tag."""
    _git(repo, 'checkout', '-q', '-b', 'feat/topic')
    done = _run(repo)
    assert done.returncode == 0
    assert 'not release branch' in done.stdout
    assert _git(repo, 'tag', '--list') == '', 'a topic branch push must not pollute the tag namespace'


def test_the_collision_scan_walks_CONSECUTIVE_versions(repo: Path) -> None:
    """The measured fork defect: one taken tag cost two version numbers.

    wdg-lab's copy incremented ``PATCH`` in the loop body AND computed ``PATCH + 1`` in the
    candidate, so a single collision skipped a version. Two tags are planted so the scan must walk
    twice; the honest answer is the next FREE number, not the next-but-two.
    """
    _git(repo, 'tag', 'v0.2.4', 'HEAD')
    _git(repo, 'tag', 'v0.2.5', 'HEAD~0')
    # Both tags point at HEAD, so clear the "HEAD already tagged" short-circuit by adding a commit.
    (repo / 'g.txt').write_text('y', encoding='utf-8')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-m', 'feat: next')
    done = _run(repo)
    assert done.returncode == 0, done.stderr
    assert 'v0.2.6' in done.stdout, done.stdout + done.stderr
    assert 'v0.2.7' not in done.stdout, 'the scan skipped a version'


def test_multi_digit_patches_sort_NUMERICALLY(repo: Path) -> None:
    """``v0.2.9`` must not outrank ``v0.2.90``.

    The fork sorted with ``git tag --sort=-version:refname``, which needs a recent git plus
    versionsort config; the numeric field sort here is portable to every git that has ``git tag``.
    """
    for tag in ('v0.2.9', 'v0.2.89', 'v0.2.90'):
        _git(repo, 'tag', tag, 'HEAD')
    (repo / 'g.txt').write_text('y', encoding='utf-8')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-m', 'feat: next')
    done = _run(repo)
    assert 'v0.2.91' in done.stdout, done.stdout + done.stderr


def test_a_failed_proof_declines_the_tag_AND_exits_0(repo: Path) -> None:
    """BOTH halves in one test, because either alone is the wrong mechanism.

    Refusing without exiting 0 would block the code push -- the thing this design deliberately does
    not do. Exiting 0 without refusing is the defect the proof hook exists to close.
    """
    done = _run(repo, LAB_BUMP_PROOF_CMD='echo no-verdict-for-this-tree; exit 1', LAB_BUMP_PROOF_NAME='heavy')
    assert done.returncode == 0, f'a tag refusal must never fail the push: {done.stderr}'
    assert 'heavy' in done.stdout.lower(), f'the refusal must NAME why it refused: {done.stdout!r}'
    assert _git(repo, 'tag', '--list') == '', 'no tag may be minted without its proof'


def test_a_passing_proof_is_RECORDED_IN_the_tag(repo: Path) -> None:
    """The accepting side of the two-sided control, and the tag carries the line it rests on."""
    done = _run(repo, LAB_BUMP_PROOF_CMD='echo "[verdict tree=abc tier=heavy] PASS -- probe"')
    assert done.returncode == 0, done.stderr
    assert _git(repo, 'tag', '--list') == 'v0.0.1'
    assert 'tier=heavy' in _git(repo, 'tag', '-n99', '--list', 'v0.0.1')


def test_no_proof_command_means_tag_without_one(repo: Path) -> None:
    """A repo with no such tier gets a version, and the tag claims nothing it cannot support."""
    done = _run(repo)
    assert done.returncode == 0, done.stderr
    assert _git(repo, 'tag', '--list') == 'v0.0.1'
    assert 'Proved by' not in _git(repo, 'tag', '-n99', '--list', 'v0.0.1')


def test_an_unusable_remote_exits_0_and_NAMES_the_cause(repo: Path) -> None:
    """Best-effort means "does not block AND does not go quiet", and it was only ever the first.

    Run against a remote path that does not exist: the tag push must fail, the script must still
    exit 0 (a tagging problem may never fail a code push), and the message must carry git's own
    reason rather than a bare "could not publish".
    """
    done = _run(repo)
    assert done.returncode == 0
    out = done.stdout + done.stderr
    line = next((ln for ln in out.splitlines() if 'could not publish' in ln), None)
    assert line is not None, f'the hook went quiet about a failed tag push: {out!r}'
    _, sep, cause = line.partition(' -- ')
    why = f'the message names no cause, so every failure reads identically: {line!r}'
    assert sep, why
    assert cause.strip(), why
