"""A new repo is configured ONCE, and the pieces are one statement rather than five discoveries.

PLANTED on hand-written manifests: a bare repo names every missing piece at once, and the same repo with the
five declarations supplied passes. The forge half is planted on a client whose ``/pulls`` answers 404.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab_commons.dev.famtests.onboarding import (
    OnboardingViolation,
    assert_repo_is_onboarded,
    assert_the_forge_takes_pull_requests,
)

_COMPLETE = """[tool.lab_commons.branchset]
trunk = 'main'
sessions = ['integrate/main']
ephemeral = ['pr/*']

[tool.lab_commons.integrator]
integration = 'integrate/main'
pr_merges_since = 'abc123'

[tool.lab_commons.tests]
produce = ["-m", "lab_commons.dev.verify", "--part", "{part}"]

[tool.lab_commons.hooks]
"""


def _repo(root: Path, manifest: str, *, files: tuple[str, ...] = ('AGENTS.md', 'uv.lock')) -> Path:
    (root / 'pyproject.toml').write_text(manifest, encoding='utf-8')
    for name in files:
        (root / name).write_text('# x\n', encoding='utf-8')
    return root


def test_a_complete_repo_is_onboarded(tmp_path: Path) -> None:
    assert assert_repo_is_onboarded(root=_repo(tmp_path, _COMPLETE)) == ()


def test_a_bare_repo_names_every_missing_piece_at_once(tmp_path: Path) -> None:
    """PLANTED control: the same repo with the declarations supplied passes (the test above)."""
    bare = _repo(tmp_path, "[project]\nname = 'x'\n", files=())
    with pytest.raises(OnboardingViolation) as refused:
        assert_repo_is_onboarded(root=bare)
    text = str(refused.value)
    for piece in ('branchset', 'pr_merges_since', 'produce', 'hooks', 'AGENTS.md', 'uv.lock'):
        assert piece in text, f'{piece} is missing from:\n{text}'


def test_one_missing_line_is_named_among_the_rest(tmp_path: Path) -> None:
    partial = _repo(tmp_path, _COMPLETE.replace("ephemeral = ['pr/*']\n", ''))
    with pytest.raises(OnboardingViolation, match='ephemeral'):
        assert_repo_is_onboarded(root=partial)


class _Forge:
    """The two answers onboarding's forge half reads: the repo, and its pull requests."""

    repo = '/api/v1/repos/o/r'

    def __init__(self, *, pulls: bool) -> None:
        self.pulls = pulls
        self.asked: list[str] = []

    def call(self, method: str, path: str, body: dict[str, object] | None = None) -> list[object] | dict[str, object]:
        self.asked.append(path)
        assert method == 'GET'
        if path.endswith('/pulls?state=all&limit=1') and not self.pulls:
            msg = '404 not found'
            raise RuntimeError(msg)
        return {} if not path.endswith('limit=1') else []


def test_a_repo_with_pull_requests_off_is_refused_by_name() -> None:
    assert_the_forge_takes_pull_requests(_Forge(pulls=True))
    with pytest.raises(OnboardingViolation, match='Pull Requests unit is OFF'):
        assert_the_forge_takes_pull_requests(_Forge(pulls=False))
