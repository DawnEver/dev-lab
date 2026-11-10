"""A new repo is configured ONCE, and the pieces are one statement rather than five discoveries.

PLANTED on hand-written manifests: a bare repo names every missing piece at once, and the same repo with the
five declarations supplied passes. The forge half is planted on a client whose ``/pulls`` answers 404.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev.famtests.onboarding import (
    OnboardingViolation,
    assert_repo_is_onboarded,
    assert_the_forge_takes_pull_requests,
    onboarding_gaps,
)

_COMPLETE = """[tool.dev_lab.branchset]
trunk = 'main'
sessions = ['integrate/main']

[tool.dev_lab.integrator]
integration = 'integrate/main'
pr_merges_since = 'abc123'

[tool.lab_commons.tests]
produce = ["-m", "dev_lab.dev.verify", "--part", "{part}"]

[tool.dev_lab.hooks]
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
    for piece in ('branchset', 'integrator] integration', 'pr_merges_since', 'produce', 'hooks', 'AGENTS.md'):
        assert piece in text, f'{piece} is missing from:\n{text}'
    assert 'uv.lock' in text


def test_a_declared_integrator_without_its_start_is_named(tmp_path: Path) -> None:
    """The integration half moves with its declaration: declared without ``pr_merges_since``, it is named."""
    declared = _repo(tmp_path, "[project]\nname = 'x'\n[tool.dev_lab.integrator]\nintegration = 'integrate/main'\n")
    with pytest.raises(OnboardingViolation, match='pr_merges_since'):
        assert_repo_is_onboarded(root=declared)


def test_one_missing_line_is_named_among_the_rest(tmp_path: Path) -> None:
    partial = _repo(
        tmp_path,
        _COMPLETE.replace("sessions = ['integrate/main']\n", "sessions = ['integrate/main']\nephemeral = []\n"),
    )
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


def test_the_built_in_ephemeral_default_needs_no_restating() -> None:
    """``branchset.FAMILY_EPHEMERAL`` already makes ``pr/*`` ephemeral; a manifest without the line is onboarded.

    PLANTED CONTROL: a value that drops ``pr/*`` is still named.
    """
    text = (
        "[tool.dev_lab.branchset]\ntrunk = 'main'\nsessions = ['integrate/main']\n"
        "[tool.dev_lab.integrator]\nintegration = 'integrate/main'\npr_merges_since = 'abc'\n"
        "[tool.dev_lab.hooks]\n[tool.lab_commons.tests]\nproduce = ['-m', 'dev_lab.dev.verify', '--part', '{part}']\n"
    )
    assert onboarding_gaps(text, {'AGENTS.md', 'uv.lock'}.__contains__, 'origin/x') == []
    off = text.replace("sessions = ['integrate/main']\n", "sessions = ['integrate/main']\nephemeral = ['wip/*']\n")
    assert onboarding_gaps(off, {'AGENTS.md', 'uv.lock'}.__contains__, 'origin/x') != []


def test_a_rendered_family_file_without_its_render_input_declared_is_a_gap() -> None:
    """A family file a renderer writes, held with that renderer's input undeclared, is an onboarding gap.

    MEASURED 2026-11-10: three members held family files and declared no ``[tool.dev_lab.render]``, so every relock
    left them stale and the forge went red on the symptoms. A renderer is DUE where a file it writes is present
    (:func:`dev_lab.dev.famfiles.due_renderers`); each due renderer's required input must be declared.

    PLANTED CONTROLS: the same manifest with the inputs declared has no gap; a tree holding no file the renderer
    writes owes none of its inputs.
    """
    present = {'AGENTS.md', 'uv.lock', '.gitignore', '.claude/hooks/deny-rules.json'}
    gaps = ' '.join(onboarding_gaps(_COMPLETE, present.__contains__, 'origin/x'))
    assert '[tool.dev_lab.render] deltas' in gaps
    assert '[tool.dev_lab.render] adoption' in gaps
    declared = _COMPLETE + '[tool.dev_lab.render]\ndeltas = "tests/_famconfig.py"\nadoption = "scripts/deny_rules.py"\n'
    assert onboarding_gaps(declared, present.__contains__, 'origin/x') == []
    only_gitignore = {'AGENTS.md', 'uv.lock', '.gitignore'}
    left = ' '.join(onboarding_gaps(_COMPLETE, only_gitignore.__contains__, 'origin/x'))
    assert 'deltas' in left
    assert 'adoption' not in left
