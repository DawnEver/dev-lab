"""THE REVIEW RUNTIME FOLLOWS THE LOCK (2026-11-05): a host's ai-lab is the one its dev-lab's ``uv.lock`` pins.

Host host-a review failed because its ai-lab was a hand-built venv the machine file named, drifted from the pin. The
runtime is now built under the forge home keyed by the pinned commit, by CI's own steps: a moved pin rebuilds, the
same pin reuses, and a machine file still naming one is refused.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from lab_commons.config import CONFIG_ENV

from dev_lab.dev import reviewruntime
from dev_lab.dev.forgereview_runtimes import host_runtimes

if TYPE_CHECKING:
    from collections.abc import Sequence

SHA_A, SHA_B = 'a' * 40, 'b' * 40
CI_BASE = Path(reviewruntime.__file__).with_name('ci_base.toml')

#: The real seams, read before conftest stubs them for every other review test.
ENSURE, KIT = reviewruntime.ensure, reviewruntime.kit


def _lock(sha: str = SHA_A, url: str = 'https://github.com/o/ai-lab.git') -> str:
    return f'[[package]]\nname = "ai-lab"\nsource = {{ git = "{url}#{sha}" }}\n'


class _Builds:
    def __init__(self) -> None:
        self.built: list[tuple[str, str]] = []

    def __call__(self, venv: Path, source: str, commit: str) -> None:
        self.built.append((source, commit))
        python = reviewruntime.interpreter(venv)
        python.parent.mkdir(parents=True)
        python.write_text('', encoding='utf-8')


def test_the_pin_is_the_ai_lab_commit_the_lock_names() -> None:
    assert reviewruntime.pinned(_lock()) == SHA_A
    with pytest.raises(ValueError, match='pins no ai-lab'):
        reviewruntime.pinned('[[package]]\nname = "dev-lab"\n')
    with pytest.raises(ValueError, match='not a git revision'):
        reviewruntime.pinned('[[package]]\nname = "ai-lab"\nsource = { registry = "https://pypi.org/simple" }\n')


def test_ai_lab_comes_from_the_owner_dev_lab_came_from() -> None:
    assert reviewruntime.sibling('https://forge.lan/o/dev-lab.git') == 'https://forge.lan/o/ai-lab.git'
    assert reviewruntime.sibling('git+https://github.com/o/dev-lab') == 'https://github.com/o/ai-lab.git'
    with pytest.raises(ValueError, match='no owner'):
        reviewruntime.sibling('dev-lab')


def test_the_same_pin_reuses_and_a_moved_pin_rebuilds_and_removes_the_old(tmp_path: Path) -> None:
    builds = _Builds()
    first = ENSURE(tmp_path, 'src', SHA_A, build=builds)
    assert first == reviewruntime.interpreter(tmp_path / 'runtimes' / f'ai-lab-{SHA_A[:12]}')
    assert ENSURE(tmp_path, 'src', SHA_A, build=builds) == first
    assert builds.built == [('src', SHA_A)], 'PLANTED CONTROL: the same pin is one build'
    moved = ENSURE(tmp_path, 'src', SHA_B, build=builds)
    assert builds.built == [('src', SHA_A), ('src', SHA_B)], 'a moved pin rebuilds'
    assert moved.is_file()
    assert not first.exists(), 'the old pin leaves nothing behind'


def test_a_build_that_never_stamped_is_rebuilt(tmp_path: Path) -> None:
    half = tmp_path / 'runtimes' / f'ai-lab-{SHA_A[:12]}'
    python = reviewruntime.interpreter(half)
    python.parent.mkdir(parents=True)
    python.write_text('', encoding='utf-8')  # an interpreter, but no READY: the build died midway
    builds = _Builds()
    ENSURE(tmp_path, 'src', SHA_A, build=builds)
    assert builds.built == [('src', SHA_A)]
    assert (half / reviewruntime.READY).read_text(encoding='utf-8').strip() == SHA_A


def test_the_build_is_ci_s_method_step(tmp_path: Path) -> None:
    """The host's build and CI's ``method`` step are the same recipe: the commit, ai-lab's lock frozen, no deps."""
    ran: list[list[str]] = []

    def run(argv: Sequence[str]) -> str:
        ran.append(list(argv))
        return 'pkg==1\n'

    venv = tmp_path / 'ai-lab-x'
    reviewruntime.build(venv, 'https://forge/o/ai-lab.git', SHA_A, run=run, net=run)
    joined = [' '.join(a) for a in ran]
    assert any(f'fetch -q --no-tags origin {SHA_A}' in a for a in joined)
    assert any(f'checkout -q --detach {SHA_A}' in a for a in joined)
    export = next(a for a in ran if 'export' in a)
    assert export[1 : 1 + len(reviewruntime.EXPORT)] == list(reviewruntime.EXPORT)
    installs = [a for a in ran if 'install' in a and '--no-deps' in a]
    assert len(installs) == 2, 'the exported lock, then ai-lab itself, each --no-deps'
    method = tomllib.loads(CI_BASE.read_text(encoding='utf-8'))['_steps']['method'][0]['run']
    assert all(f' {flag}' in method for flag in reviewruntime.EXPORT), 'CI exports with the very flags the host does'
    assert method.count('--no-deps') == 2


def test_the_kit_lock_is_the_editable_checkout_s(tmp_path: Path) -> None:
    (tmp_path / 'uv.lock').write_text(_lock(), encoding='utf-8')
    url = tmp_path.as_uri()

    def run(argv: Sequence[str]) -> str:
        assert argv[-3:] == ['remote', 'get-url', 'origin']
        return 'https://forge/o/dev-lab.git\n'

    lock, came = KIT(tmp_path, origin={'url': url, 'dir_info': {'editable': True}}, run=run)
    assert (lock, came) == (_lock(), 'https://forge/o/dev-lab.git')


def test_a_git_installed_kit_fetches_its_lock_once(tmp_path: Path) -> None:
    fetched: list[list[str]] = []

    def net(argv: Sequence[str]) -> str:
        fetched.append(list(argv))
        return ''

    origin = {'url': 'https://forge/o/dev-lab.git', 'vcs_info': {'vcs': 'git', 'commit_id': SHA_B}}
    for _ in range(2):
        lock, came = KIT(tmp_path, origin=origin, run=lambda _a: _lock(), net=net)
        assert (lock, came) == (_lock(), 'https://forge/o/dev-lab.git')
    assert len(fetched) == 2, 'PLANTED CONTROL: one clone and one fetch, then the cached lock'
    with pytest.raises(ValueError, match='no lock names'):
        KIT(tmp_path, origin={'url': 'file:///wheel'}, net=net)


def _machine(text: str) -> None:
    path = Path(os.environ[CONFIG_ENV])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def test_the_review_runtimes_carry_the_locked_ai_lab(locked_ai_lab: Path) -> None:
    _machine('[runtimes.corpus]\npath = "~/c"\n')
    got = reviewruntime.review_runtimes()
    assert got == {'corpus': {'path': '~/c'}, 'ai_lab': {'python': str(locked_ai_lab)}}
    given = reviewruntime.review_runtimes(['ai_lab.python=/runner/bin/python'])
    assert given['ai_lab'] == {'python': '/runner/bin/python'}, 'a runner hands the interpreter its method step built'


def test_a_hand_set_ai_lab_path_is_refused() -> None:
    _machine('[runtimes.ai_lab]\npython = "C:/ai-lab/.claude/worktrees/runtime-3/.venv/Scripts/python.exe"\n')
    with pytest.raises(ValueError, match=r'\[runtimes.ai_lab\] is retired: built from the ai-lab commit'):
        host_runtimes()
    _machine('[runtimes.corpus]\npath = "~/c"\n')
    assert host_runtimes() == {'corpus': {'path': '~/c'}}, 'PLANTED CONTROL: a runtime a host does declare'
