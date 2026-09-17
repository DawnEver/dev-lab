"""``lab_commons.dev.selfbuild`` -- driven over REAL manifests, REAL wheel files and REAL anchors.

WHAT IS AND IS NOT FAKED, stated first because it is the only interesting choice here. The manifests
are real TOML files on disk, read by the real ``tomllib``; the wheels are real files with real wheel
filenames; the verdict anchors are real files that are really deleted. What is injected is the ``run``
callable -- and that is the seam :mod:`lab_commons.dev.dep` declares for exactly this, not a patch
over the module under test. It has to be: the only alternative is invoking pip, and pip is how this
box's SHARED environment moves. A test suite that mutated the interpreter another lane's verdict is
running in would be committing the offence this whole module exists to police.

EVERY CASE NAMES THE DIRECTION IT FAILS IN. The ownership check is the one guard that could be
deleted and leave every other test green, because ``Mode.PINNED`` still refuses an index without it
-- and refusing an index says nothing whatever about ``pip install ./somebody-elses.whl``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from lab_commons.dev.dep import HeldEnvironmentError, Port
from lab_commons.dev.selfbuild import (
    ForeignDistributionError,
    NothingBuiltError,
    declared_distributions,
    install_self_build,
    normalise_distribution,
    refuse_foreign_wheel,
    wheel_distribution,
)

#: A real wheel filename. The version carries a `-` in neither field on purpose: the grammar's one
#: unambiguous field is the first, and that is the claim being relied on.
_WHEEL = 'motronics_native-0.4.1-cp312-cp312-win_amd64.whl'

#: The SAME project with an ILLEGAL filename: PEP 427 escapes `-` to `_` in the distribution field,
#: so this is a hand-renamed file rather than a second spelling. It must refuse -- fail-closed on a
#: malformed name is the only outcome that cannot install the wrong thing.
_WHEEL_RENAMED = 'motronics-native-0.4.1-cp312-cp312-win_amd64.whl'


def _manifest(directory: Path, name: str) -> Path:
    """A real `pyproject.toml` declaring one project name."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'pyproject.toml'
    path.write_text(f'[project]\nname = "{name}"\nversion = "0.1.0"\n', encoding='utf-8')
    return path


def _workspace(root: Path) -> tuple[Path, ...]:
    """A PyO3-shaped workspace: two crates under `rust/pybind/`, plus one manifest with no name."""
    _manifest(root / 'rust' / 'pybind' / 'euclid', 'motronics-native')
    _manifest(root / 'rust' / 'pybind' / 'other', 'other_native')
    nameless = root / 'rust' / 'pybind' / 'nameless'
    nameless.mkdir(parents=True)
    (nameless / 'pyproject.toml').write_text('[build-system]\nrequires = []\n', encoding='utf-8')
    return tuple(sorted((root / 'rust' / 'pybind').glob('*/pyproject.toml')))


def _wheel(root: Path, filename: str = _WHEEL) -> Path:
    path = root / filename
    path.write_bytes(b'not a real zip, and pip is never invoked here')
    return path


class _Recorder:
    """A stand-in for `subprocess.run`, called exactly as `dep.mutate` calls the real one."""

    def __init__(self, returncode: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.returncode = returncode

    def __call__(self, argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, self.returncode)


def test_the_names_are_read_from_the_tree_and_folded(tmp_path: Path) -> None:
    """Read from real manifests, so a renamed crate cannot leave a stale allowlist behind."""
    manifests = _workspace(tmp_path)
    assert len(manifests) == 3, "the plant is this case's floor: three manifests, one of them nameless"
    assert declared_distributions(manifests) == frozenset({'motronics_native', 'other_native'})
    assert declared_distributions(()) == frozenset()
    assert normalise_distribution(' Motronics-Native ') == 'motronics_native'
    assert wheel_distribution(Path(_WHEEL)) == 'motronics_native'
    assert wheel_distribution(Path(_WHEEL_RENAMED)) == 'motronics', 'the first field, read as written'


def test_a_manifest_that_is_not_there_is_skipped_rather_than_raising(tmp_path: Path) -> None:
    """A caller's glob is a snapshot; a path that vanished must not take the whole reading down."""
    manifests = (*_workspace(tmp_path), tmp_path / 'rust' / 'pybind' / 'gone' / 'pyproject.toml')
    assert declared_distributions(manifests) == frozenset({'motronics_native', 'other_native'})


def test_a_foreign_wheel_is_refused_and_our_own_is_not(tmp_path: Path) -> None:
    """THE GUARD. Delete it and `Mode.PINNED` still refuses an index -- and installs scipy happily.

    The third case is the malformed-name direction: an illegal wheel filename refuses rather than
    being repaired into the name it looks like, because a repair here guesses at what to install.
    """
    built = declared_distributions(_workspace(tmp_path))
    refuse_foreign_wheel(_wheel(tmp_path), built, workspace='plant')
    with pytest.raises(ForeignDistributionError, match='DEPENDENCY CHANGE'):
        refuse_foreign_wheel(_wheel(tmp_path, 'scipy-1.14.0-cp312-cp312-win_amd64.whl'), built, workspace='plant')
    with pytest.raises(ForeignDistributionError, match='DEPENDENCY CHANGE'):
        refuse_foreign_wheel(_wheel(tmp_path, _WHEEL_RENAMED), built, workspace='plant')


def test_an_empty_allowlist_refuses_everything(tmp_path: Path) -> None:
    """THE FLOOR. A glob that stopped matching must not read as 'nothing objected'."""
    with pytest.raises(NothingBuiltError, match='builds nothing'):
        refuse_foreign_wheel(_wheel(tmp_path), frozenset(), workspace='plant')
    assert issubclass(NothingBuiltError, ForeignDistributionError), 'one catch must still cover both'


def test_the_install_is_pinned_names_the_wheel_and_retires_the_moved_anchors(tmp_path: Path) -> None:
    """END TO END through the real door: real anchors on disk, really deleted, because the key MOVED."""
    manifests = _workspace(tmp_path)
    wheel = _wheel(tmp_path)
    anchor = tmp_path / 'gate.verdict'
    anchor.write_text('PASS', encoding='utf-8')
    keys = iter(['before-key', 'after-key'])
    port = Port(
        name='plant',
        holders=lambda: (),
        anchor_paths=lambda: (anchor,),
        key=lambda: next(keys),
    )
    run = _Recorder()
    report = install_self_build(wheel, manifests=manifests, port=port, run=run)

    assert len(run.calls) == 1
    argv = run.calls[0]
    assert '--no-index' in argv, f'a resolving install was issued: {argv}'
    assert '--no-deps' in argv, f'a resolving install was issued: {argv}'
    assert argv[-1] == str(wheel)
    assert report.returncode == 0
    assert report.moved
    assert report.retired == (str(anchor),)
    assert not anchor.exists(), 'the anchor was reported retired and is still on disk'


def test_a_held_lock_refuses_before_anything_is_installed(tmp_path: Path) -> None:
    """H1: a verdict is in flight, so nothing runs and the anchor it will cite survives."""
    anchor = tmp_path / 'gate.verdict'
    anchor.write_text('PASS', encoding='utf-8')
    port = Port(name='plant', holders=lambda: ('pid 1234 (heavy)',), anchor_paths=lambda: (anchor,))
    run = _Recorder()
    with pytest.raises(HeldEnvironmentError, match='pid 1234'):
        install_self_build(_wheel(tmp_path), manifests=_workspace(tmp_path), port=port, run=run)
    assert run.calls == []
    assert anchor.exists()


def test_ownership_is_decided_before_the_lock_is_even_consulted(tmp_path: Path) -> None:
    """ORDER. A foreign wheel is refused whether or not the box happens to be free."""
    consulted: list[str] = []

    def holders() -> tuple[str, ...]:
        consulted.append('lock')
        return ()

    port = Port(name='plant', holders=holders)
    with pytest.raises(ForeignDistributionError):
        install_self_build(
            _wheel(tmp_path, 'scipy-1.14.0-cp312-cp312-win_amd64.whl'),
            manifests=_workspace(tmp_path),
            port=port,
            run=_Recorder(),
        )
    assert consulted == [], 'the lock was asked about a wheel that was never eligible'


def test_a_missing_wheel_is_a_typo_and_says_so(tmp_path: Path) -> None:
    """Checked here rather than left to pip: a missing local file is not an environment decision."""
    port = Port(name='plant', holders=lambda: ())
    with pytest.raises(FileNotFoundError, match='no such wheel'):
        install_self_build(tmp_path / 'absent.whl', manifests=_workspace(tmp_path), port=port, run=_Recorder())


def test_a_dry_run_checks_everything_and_retires_nothing(tmp_path: Path) -> None:
    """A dry run that deleted an anchor would have mutated the very thing it reports on."""
    anchor = tmp_path / 'heavy.verdict'
    anchor.write_text('PASS', encoding='utf-8')
    port = Port(name='plant', holders=lambda: (), anchor_paths=lambda: (anchor,), key=lambda: 'steady')
    run = _Recorder()
    report = install_self_build(_wheel(tmp_path), manifests=_workspace(tmp_path), port=port, run=run, dry_run=True)
    assert run.calls == []
    assert report.returncode is None
    assert report.retired == ()
    assert anchor.exists()
    assert '--no-index' in report.argv


def test_the_workspace_label_defaults_to_the_port_name(tmp_path: Path) -> None:
    """A refusal a reader cannot place is a refusal they route around."""
    port = Port(name='motronics-studio', holders=lambda: ())
    with pytest.raises(ForeignDistributionError, match='motronics-studio'):
        install_self_build(
            _wheel(tmp_path, 'scipy-1.14.0-cp312-cp312-win_amd64.whl'),
            manifests=_workspace(tmp_path),
            port=port,
            run=_Recorder(),
        )


def test_two_builds_at_one_version_both_reach_pip_as_a_forced_reinstall(tmp_path: Path) -> None:
    """THE PLANT: the same wheel FILENAME, hence the same version, carrying different bytes.

    That is what a crate with `dynamic = ["version"]` produces when its source moves and its
    `Cargo.toml` number does not, and it is the situation pip 26.2.1 answers by logging "already
    installed with the same version as the provided wheel" and exiting ZERO. Without
    `--force-reinstall` the second install here is a no-op the caller is told succeeded, and
    `env_key` -- which is the only other instrument in this door -- truthfully agrees nothing moved.

    Driven through the REAL entry point with a recording `run`, asserted on the argv the child was
    actually handed, and then asserted EQUAL to `report.argv`: a report naming a command pip did not
    get is the declaration-that-lies half of the same defect.
    """
    manifests = _workspace(tmp_path)
    argvs = []
    for content in (b'BUILD A -- one sha', b'BUILD B -- a later sha, same Cargo.toml version'):
        wheel = tmp_path / _WHEEL
        wheel.write_bytes(content)
        run = _Recorder()
        port = Port(name='plant', holders=lambda: (), anchor_paths=lambda: (), key=lambda: 'unmoved')
        report = install_self_build(wheel, manifests=manifests, port=port, run=run)
        assert len(run.calls) == 1, 'the floor: no call means nothing was measured'
        assert run.calls[0] == list(report.argv), 'the report named a command the child never got'
        assert not report.moved, 'the plant is an UNCHANGED version -- env_key cannot see this hazard'
        argvs.append(tuple(run.calls[0]))
    assert len(argvs) == 2, 'the floor: two builds, or the hazard was never planted'
    assert len({argv[-1] for argv in argvs}) == 1, 'both builds must name ONE wheel path and version'
    for argv in argvs:
        assert '--force-reinstall' in argv, f'pip would skip this install and exit zero: {argv}'
        assert '--no-index' in argv, 'forcing must not have loosened the pin'
        assert '--no-deps' in argv, 'forcing must not have loosened the pin'
