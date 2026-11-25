"""A TRACKED render is written only by the checkout's own kit, and never into a MAIN checkout (toolchain O14).

THE INCIDENT, 2026-11-17: a consumer's MAIN checkout held a ``deny-commands.js`` and a ``settings.json`` that
differed from HEAD, because ``agent_guard --install`` ran there from a dev-lab kit its lock does not pin. The
dirt made the fast-forward refresh refuse the checkout, which fell 180 commits behind.

THE TENSION, kept in both directions here: the same install is how a LANE re-renders those files after a
relock, and the lane commits the result. So each rule is planted beside the control it must not break --
the foreign kit beside the lane whose relocked lock pins the running kit, the main checkout beside the
linked worktree, a refusal beside the no-op that has nothing to refuse.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev import agent_guard, agent_wiring, trackedrender

_GIT = shutil.which('git') or 'git'
#: The tracked files an older kit rendered differently from the running one.
_RENDERED = frozenset({agent_wiring.ENGINE_REL, agent_wiring.SETTINGS_REL})


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(
        [_GIT, *args], cwd=root, capture_output=True, text=True, encoding='utf-8', check=True, timeout=60
    )
    return done.stdout


def _pin(root: Path, commit: str) -> None:
    """*root*'s ``uv.lock``, pinning dev-lab at *commit* the way uv writes a git source."""
    pin = f'source = {{ git = "https://example.invalid/dev-lab.git#{commit}" }}'
    (root / 'uv.lock').write_text(f'[[package]]\nname = "dev-lab"\nversion = "0"\n{pin}\n', encoding='utf-8')


def _commit(root: Path, message: str) -> None:
    _git(root, 'add', '--', '.claude', 'uv.lock')
    _git(root, 'commit', '-q', '-m', message)


def _committed_older_render(root: Path, *, pin: str) -> Path:
    """A MAIN checkout whose COMMITTED hook files are an older kit's render, its lock pinning *pin*."""
    root.mkdir(parents=True)
    _git(root, 'init', '-q')
    for name, value in (('user.email', 'a@b.invalid'), ('user.name', 'Test')):
        _git(root, 'config', name, value)
    agent_guard.install_guard(root)  # a fresh repo: every file it writes is untracked, so nothing is refused
    engine = root / agent_wiring.ENGINE_REL
    engine.write_text(engine.read_text(encoding='utf-8') + '// rendered by an older kit\n', encoding='utf-8')
    (root / agent_wiring.SETTINGS_REL).write_text('{"hooks": {}}\n', encoding='utf-8')
    _pin(root, pin)
    _commit(root, 'an older render')
    assert _git(root, 'status', '--porcelain') == ''
    return root


def _lane(main: Path, name: str, *, relock_to: str | None = None) -> Path:
    """A linked worktree of *main*; with *relock_to*, its lock moved there and COMMITTED, as a relock does."""
    lane = main.parent / name
    _git(main, 'worktree', 'add', '-q', '-b', name, str(lane))
    if relock_to is not None:
        _pin(lane, relock_to)
        _commit(lane, 'relock dev-lab')
    return lane


def _changed(root: Path) -> set[str]:
    return {line[3:] for line in _git(root, 'status', '--porcelain').splitlines()}


def _kit(tmp_path: Path, commit: str) -> trackedrender.Kit:
    """A kit installed from git at *commit*, its package outside every planted checkout."""
    return trackedrender.Kit(package=tmp_path / 'site-packages' / 'dev_lab', commit=commit)


def test_a_foreign_kit_leaves_the_main_checkout_clean_and_names_the_door(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """PLANTED, the incident itself: kit a..., lock pins b..., on a MAIN checkout -- refused, nothing written."""
    main = _committed_older_render(tmp_path / 'consumer', pin='b' * 40)
    monkeypatch.setattr(trackedrender, 'running_kit', lambda: _kit(tmp_path, 'a' * 40))
    assert agent_guard.report_guard(['--install', '--repo', str(main)]) == 1
    assert _git(main, 'status', '--porcelain') == '', 'the refused install dirtied the checkout'
    out = capsys.readouterr().out
    assert '[agent-guard] REFUSED' in out, out
    assert 'dev-lab aaaaaaaaaaaa' in out, 'the cause names the running kit'
    assert 'pins bbbbbbbbbbbb' in out, "the cause names the lock's pin"
    assert agent_wiring.ENGINE_REL in out, 'the refusal names the files it did not write'
    assert 'MAIN checkout' in out, out
    assert 'lane worktree' in out, 'the door: re-render in a lane and commit there'


def test_a_foreign_kit_writes_nothing_tracked_in_a_lane(tmp_path: Path) -> None:
    """PLANTED, the kit rule alone: a linked worktree, kit a..., lock pins b... -- refused naming the sync door."""
    lane = _lane(_committed_older_render(tmp_path / 'consumer', pin='b' * 40), 'stale-lane')
    with pytest.raises(trackedrender.RenderRefused) as refused:
        agent_guard.install_guard(lane, kit=_kit(tmp_path, 'a' * 40))
    assert _git(lane, 'status', '--porcelain') == ''
    message = str(refused.value)
    assert 'dev-lab aaaaaaaaaaaa' in message
    assert 'pins bbbbbbbbbbbb' in message
    assert '-m dev_lab.dev.dep --bootstrap' in message, 'the door: make the venv follow its lock'
    assert 'relock' in message, 'the other door: move the render with the lock'
    assert 'MAIN checkout' not in message, 'a linked worktree is not refused as a main checkout'


def test_control_a_lane_whose_relocked_lock_pins_the_running_kit_receives_the_render(tmp_path: Path) -> None:
    """PLANTED CONTROL: the relock flow -- a lane committed its lock at c..., the kit is c... -- still renders."""
    lane = _lane(_committed_older_render(tmp_path / 'consumer', pin='b' * 40), 'relock', relock_to='c' * 40)
    actions = agent_guard.install_guard(lane, kit=_kit(tmp_path, 'c' * 40))
    assert _changed(lane) == _RENDERED, actions
    assert agent_guard.guard_installation(lane).by_part['engine'].status == agent_guard.INSTALLED


def test_the_main_checkout_receives_no_tracked_render_even_from_its_own_kit(tmp_path: Path) -> None:
    """PLANTED, the main-checkout rule alone: the lock pins the running kit, and main still is not written."""
    main = _committed_older_render(tmp_path / 'consumer', pin='c' * 40)
    with pytest.raises(trackedrender.RenderRefused) as refused:
        agent_guard.install_guard(main, kit=_kit(tmp_path, 'c' * 40))
    assert _git(main, 'status', '--porcelain') == ''
    message = str(refused.value)
    assert 'MAIN checkout' in message
    assert 'lane worktree' in message
    assert 'not its own' not in message, 'the kit is the checkout own; only the main rule refused'


def test_control_an_install_with_nothing_to_change_is_never_refused(tmp_path: Path) -> None:
    """PLANTED CONTROL: a main checkout whose committed render IS the running kit's -- a no-op, exit clean."""
    main = _committed_older_render(tmp_path / 'consumer', pin='b' * 40)
    lane = _lane(main, 'render', relock_to='a' * 40)
    agent_guard.install_guard(lane, kit=_kit(tmp_path, 'a' * 40))
    _commit(lane, 'commit the render')
    _git(main, 'merge', '-q', '--ff-only', 'render')
    actions = agent_guard.install_guard(main, kit=_kit(tmp_path, 'b' * 40))
    assert _git(main, 'status', '--porcelain') == ''
    assert all('already' in action for action in actions), actions


def test_dev_lab_running_its_own_source_is_its_own_kit(tmp_path: Path) -> None:
    """dev-lab pins no dev-lab: a lane of it owns the kit whose package IS its ``src/dev_lab``; another does not."""
    main = _committed_older_render(tmp_path / 'dev-lab', pin='b' * 40)
    _git(main, 'rm', '-q', 'uv.lock')
    _git(main, 'commit', '-q', '-m', 'dev-lab locks no dev-lab')
    lane = _lane(main, 'own-source')
    elsewhere = trackedrender.Kit(package=tmp_path / 'elsewhere' / 'src' / 'dev_lab', commit='')
    with pytest.raises(trackedrender.RenderRefused, match='installed from no git commit'):
        agent_guard.install_guard(lane, kit=elsewhere)
    assert _git(lane, 'status', '--porcelain') == ''
    agent_guard.install_guard(lane, kit=trackedrender.Kit(package=lane / 'src' / 'dev_lab', commit=''))
    assert _changed(lane) == _RENDERED


def test_the_running_kit_is_this_package() -> None:
    """:func:`running_kit` names the package this module was imported from, so the source rule reads the truth."""
    kit = trackedrender.running_kit()
    assert kit.package == Path(trackedrender.__file__).resolve().parent.parent
    assert isinstance(kit.commit, str), 'the git commit it was installed at, or empty when none'


@pytest.mark.parametrize('ending', ['\n', '\r\n'])
def test_a_copied_hook_file_in_either_line_ending_is_already_present(tmp_path: Path, ending: str) -> None:
    """The resolver and the session catalog are TEXT: the ending git's checkout chose is no difference.

    THE INCIDENT, 2026-11-25 (PR #956, base@windows): a lane checked out under ``core.autocrlf`` held them
    with CRLF, the kit shipped LF, a byte compare rewrote both, and the lane went dirty with no change.
    PLANTED CONTROL: a file whose TEXT differs is still rewritten.
    """
    agent_guard.install_guard(tmp_path)
    copies = [tmp_path / '.claude' / 'hooks' / name for name in ('venv_resolver.js', 'native_session.json')]
    for copy in copies:
        text = copy.read_bytes().decode('utf-8').replace('\r\n', '\n')
        copy.write_bytes(text.replace('\n', ending).encode('utf-8'))
    actions = agent_guard.install_guard(tmp_path)
    assert not [line for line in actions if 'installed' in line and 'hooks' in line], actions
    copies[0].write_bytes(copies[0].read_bytes() + b'// drifted\n')
    assert any('environment resolver installed' in line for line in agent_guard.install_guard(tmp_path))
