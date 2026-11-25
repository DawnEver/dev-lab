"""THE FAMILY RUST TOOLCHAIN is one fact rendered into every Rust repo (user ruling 2026-11-24).

Planted controls: a hand-edited channel reds, a delta key the renderer does not own is refused, and a delta
restating a base component is refused; the rendered channel satisfies the lock check's exact-version rule.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev.lockcheck import _EXACT, TOOLCHAIN
from dev_lab.dev.rusttoolchain import CHANNEL, COMPONENTS, drift, main, render, write


def _repo(tmp_path: Path, delta: str = '') -> Path:
    (tmp_path / 'pyproject.toml').write_text(f'[project]\nname = "x"\n{delta}', encoding='utf-8')
    return tmp_path


def test_the_family_channel_is_one_exact_version() -> None:
    """The fact the lock check demands of every Rust tree holds of the family's own value."""
    assert _EXACT.match(CHANNEL), CHANNEL
    assert set(COMPONENTS) == {'clippy', 'rustfmt'}


def test_the_delta_appends_components_and_targets(tmp_path: Path) -> None:
    text = render(_repo(tmp_path, '[tool.dev_lab.rust]\ncomponents = ["miri"]\ntargets = ["wasm32-unknown-unknown"]\n'))
    assert f'channel = "{CHANNEL}"' in text
    assert 'components = ["clippy", "rustfmt", "miri"]' in text
    assert 'targets = ["wasm32-unknown-unknown"]' in text


@pytest.mark.parametrize(
    ('delta', 'needle'),
    [('channel = "stable"', "'channel'"), ('components = ["clippy"]', 'restates the family base')],
)
def test_a_delta_that_forks_the_base_is_refused(tmp_path: Path, delta: str, needle: str) -> None:
    """PLANTED CONTROL: a repo choosing its own channel, or restating a base component, is refused by name."""
    with pytest.raises(ValueError, match=needle):
        render(_repo(tmp_path, f'[tool.dev_lab.rust]\n{delta}\n'))


def test_a_hand_edit_reds_and_one_render_settles_it(tmp_path: Path) -> None:
    """PLANTED CONTROL: absent reds, rendered is current, a hand-moved channel reds, the CLI check exits 1."""
    root = _repo(tmp_path)
    assert 'absent' in (drift(root) or '')
    assert write(root) == f'{TOOLCHAIN}: rendered'
    assert drift(root) is None
    (root / TOOLCHAIN).write_text(render(root).replace(CHANNEL, '1.0.0'), encoding='utf-8')
    assert 'differs' in (drift(root) or '')
    assert main(['check', '--repo', str(root)]) == 1
    assert main(['render', '--repo', str(root)]) == 0
    assert main(['check', '--repo', str(root)]) == 0
