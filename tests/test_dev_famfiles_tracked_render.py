"""The one render door moves a TRACKED file only under the checkout's own kit, in a linked worktree (toolchain O18).

THE GAP, 2026-11-17: ``famfiles.render_repo`` drives every family renderer and wrote tracked files with no check, so
a MAIN checkout rendered from a kit its lock does not pin was left dirty and its fast-forward refresh stopped. The
rule is :mod:`dev_lab.dev.trackedrender`'s, applied ONCE at the door, not per renderer. Each refusal is planted beside
the control it must not break: the relock lane that must still render, the unchanged render that is silent.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from dev_lab.dev import famfiles, trackedrender

_GIT = shutil.which('git') or 'git'
_TRACKED = 'rendered.txt'
_UNTRACKED = 'ignored.out'


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        [_GIT, *args], cwd=root, capture_output=True, text=True, encoding='utf-8', check=True, timeout=60
    ).stdout


def _pin(root: Path, commit: str) -> None:
    pin = f'source = {{ git = "https://example.invalid/dev-lab.git#{commit}" }}'
    (root / 'uv.lock').write_text(f'[[package]]\nname = "dev-lab"\nversion = "0"\n{pin}\n', encoding='utf-8')


def _main(tmp_path: Path, *, pin: str) -> Path:
    """A MAIN checkout with one tracked rendered file, a declared renderer, and its lock pinning *pin*."""
    root = tmp_path / 'consumer'
    root.mkdir()
    _git(root, 'init', '-q')
    for name, value in (('user.email', 'a@b.invalid'), ('user.name', 'Test')):
        _git(root, 'config', name, value)
    (root / 'pyproject.toml').write_text('[tool.dev_lab.render]\ndeltas = "x"\n', encoding='utf-8')
    (root / '.gitignore').write_text(f'{_UNTRACKED}\n', encoding='utf-8')
    (root / _TRACKED).write_text('old render\n', encoding='utf-8')
    _pin(root, pin)
    _git(root, 'add', '.')
    _git(root, 'commit', '-q', '-m', 'an older render')
    return root


def _writes(text: str) -> Callable[[list[str], Path], int]:
    def run(_argv: list[str], root: Path) -> int:
        (root / _TRACKED).write_text(text, encoding='utf-8')
        (root / _UNTRACKED).write_text('any\n', encoding='utf-8')
        return 0

    return run


def _kit(tmp_path: Path, commit: str) -> trackedrender.Kit:
    return trackedrender.Kit(package=tmp_path / 'site-packages' / 'dev_lab', commit=commit)


def test_a_main_checkout_under_a_foreign_kit_keeps_nothing_tracked_and_names_the_door(tmp_path: Path) -> None:
    """PLANTED, the incident: kit a..., lock pins b..., MAIN checkout -- the render is put back and refused."""
    main = _main(tmp_path, pin='b' * 40)
    with pytest.raises(trackedrender.RenderRefused) as refused:
        famfiles.render_repo(main, 'py', _writes('new render\n'), kit=_kit(tmp_path, 'a' * 40))
    assert _git(main, 'status', '--porcelain') == '', 'the refused render left tracked dirt'
    assert (main / _UNTRACKED).is_file(), 'an ignored output is not judged'
    message = str(refused.value)
    for part in (_TRACKED, 'dev-lab aaaaaaaaaaaa', 'pins bbbbbbbbbbbb', 'MAIN checkout', 'lane worktree'):
        assert part in message, message
    assert famfiles.RENDER_COMMAND in message, 'the door names the render to run in the lane'


def test_a_main_checkout_keeps_its_own_dirt_when_a_render_is_refused(tmp_path: Path) -> None:
    """A tracked file the user had already edited returns to THEIR bytes, not to the index."""
    main = _main(tmp_path, pin='b' * 40)
    (main / _TRACKED).write_text('hand edit\n', encoding='utf-8')
    with pytest.raises(trackedrender.RenderRefused):
        famfiles.render_repo(main, 'py', _writes('new render\n'), kit=_kit(tmp_path, 'a' * 40))
    assert (main / _TRACKED).read_text(encoding='utf-8') == 'hand edit\n'


def test_control_a_relocked_lane_under_the_pinned_kit_receives_the_render(tmp_path: Path) -> None:
    """PLANTED CONTROL, the relock flow: a linked worktree whose committed lock pins the rendering kit writes."""
    main = _main(tmp_path, pin='b' * 40)
    lane = tmp_path / 'lane'
    _git(main, 'worktree', 'add', '-q', '-b', 'relock', str(lane))
    _pin(lane, 'c' * 40)
    _git(lane, 'commit', '-q', '-am', 'relock dev-lab')
    lines = famfiles.render_repo(lane, 'py', _writes('new render\n'), kit=_kit(tmp_path, 'c' * 40))
    assert 'vscodesettings: rendered' in lines
    assert (lane / _TRACKED).read_text(encoding='utf-8') == 'new render\n'


def test_control_an_unchanged_render_is_silent_even_on_main_under_a_foreign_kit(tmp_path: Path) -> None:
    """PLANTED CONTROL: the render writes the committed bytes -- nothing tracked moves, nothing is refused."""
    main = _main(tmp_path, pin='b' * 40)
    lines = famfiles.render_repo(main, str(tmp_path / 'no-such-python'), _writes('old render\n'))
    assert 'vscodesettings: rendered' in lines
    assert _git(main, 'status', '--porcelain') == ''


def test_an_interpreter_that_cannot_name_its_kit_is_never_trusted(tmp_path: Path) -> None:
    """A *python* that cannot answer the probe is a kit from no commit, so the rule refuses rather than guesses."""
    kit = trackedrender.interpreter_kit(str(tmp_path / 'no-such-python'))
    assert kit.commit == ''
