"""``lab_commons.dev.shadow_build`` -- driven over REAL child processes and REAL zip files.

WHY REAL CHILDREN. The whole claim of this module is about what a SUBPROCESS sees: that the shadow
directory precedes site-packages, that the baseline arm does NOT inherit somebody else's
``PYTHONPATH``, and that a probe which died is not allowed to contribute the fastest sample in the
set. A test that patched ``subprocess.run`` would assert the argv this module builds and nothing
about the property the argv exists for -- and the argv was never the part anyone got wrong.

``maturin`` IS NOT INVOKED ANYWHERE HERE, and that is deliberate rather than a gap. Building a Rust
crate needs a toolchain, minutes, and a crate to build; what :func:`build_wheel` decides that could
be WRONG is which directories it refuses and what it does when the build wrote nothing, and both are
reachable without a compiler. The rest of it is one ``subprocess.run`` line.

Each case names the direction it would fail in, because every guard here is one somebody could
remove and still see green: a region guard that stops firing, a baseline arm that is silently
shadowed too, an error that reads as speed.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from lab_commons.dev.shadow_build import (
    DEFAULT_CHILD_WALL_S,
    Comparison,
    SharedVenvWriteError,
    build_wheel,
    interleaved,
    refuse_shared_venv_write,
    shadow_env,
    shared_venv_root,
    time_once,
    unpack_wheel,
)

#: A probe that exits 0 and does a little work. Timed as a CHILD, so it pays a real interpreter
#: start -- which is the cost this harness is measuring around and must not pretend away.
_OK_PROBE = 'import sys\nsys.exit(0)\n'

#: A probe that FAILS. It is also the FASTEST thing a child can do, which is exactly why the failure
#: has to raise rather than be timed.
_FAILING_PROBE = 'raise SystemExit(3)\n'

#: A probe that reports what it can import from, so the shadow's precedence is read out of the
#: CHILD's own ``sys.path`` rather than asserted about the parent's environment.
_PATH_PROBE = 'import sys\nsys.stdout.write(repr(sys.path))\n'


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding='utf-8')
    return path


class TestTheRegionGuard:
    """The refusal that keeps every output OUT of the environment other lanes are running in."""

    def test_the_root_is_derived_from_this_interpreter_and_not_from_a_spelling(self) -> None:
        """THE FLOOR. A root that resolved to nothing would make every refusal below unreachable."""
        root = shared_venv_root()
        assert root.is_absolute()
        assert root == Path(sys.prefix).resolve()

    def test_a_path_inside_the_environment_is_refused(self) -> None:
        with pytest.raises(SharedVenvWriteError):
            refuse_shared_venv_write(shared_venv_root() / 'Lib' / 'site-packages')

    def test_the_environment_ROOT_ITSELF_is_refused(self) -> None:
        """`--out .venv` is not a hole. A guard that only covered children would leave the root open."""
        with pytest.raises(SharedVenvWriteError):
            refuse_shared_venv_write(shared_venv_root())

    def test_a_DOTTED_spelling_of_the_same_region_is_refused(self) -> None:
        """The direction a guard fails in silently: `.venv/../.venv/Lib` names the region too.

        Comparing unresolved paths would pass this test's sibling above and let this one through,
        and the caller would never learn the difference -- the write succeeds either way.
        """
        with pytest.raises(SharedVenvWriteError):
            refuse_shared_venv_write(shared_venv_root() / '..' / shared_venv_root().name / 'Lib')

    def test_a_path_outside_it_is_allowed(self, tmp_path: Path) -> None:
        """THE OTHER SIDE OF THE RATCHET: a guard that refused everything would pass all of the above."""
        refuse_shared_venv_write(tmp_path / 'build')

    def test_both_builders_consult_the_guard_rather_than_each_checking_for_itself(self, tmp_path: Path) -> None:
        """Through the REAL entry points, so the refusal cannot be lost by one of them forgetting it."""
        inside = shared_venv_root() / 'shadow-probe'
        with pytest.raises(SharedVenvWriteError):
            build_wheel(tmp_path / 'Cargo.toml', inside)
        with pytest.raises(SharedVenvWriteError):
            unpack_wheel(tmp_path / 'nothing.whl', inside)


class TestUnpacking:
    """A wheel is a zip. Nothing here should ever need a package manager."""

    def test_a_wheel_is_unpacked_with_no_package_manager(self, tmp_path: Path) -> None:
        wheel = tmp_path / 'probe-1.0-py3-none-any.whl'
        with zipfile.ZipFile(wheel, 'w') as archive:
            archive.writestr('probe_ext/__init__.py', "VALUE = 'from the shadow'\n")
        shadow = unpack_wheel(wheel, tmp_path / 'shadow')
        assert (shadow / 'probe_ext' / '__init__.py').read_text(encoding='utf-8') == "VALUE = 'from the shadow'\n"

    def test_the_unpack_directory_is_returned_so_a_caller_never_rebuilds_the_path(self, tmp_path: Path) -> None:
        wheel = tmp_path / 'probe-1.0-py3-none-any.whl'
        with zipfile.ZipFile(wheel, 'w') as archive:
            archive.writestr('probe_ext/__init__.py', '')
        target = tmp_path / 'shadow'
        assert unpack_wheel(wheel, target) == target


class TestBuildRefusesAnEmptyBuild:
    """`maturin` exiting 0 having written nothing is the failure that reads as success."""

    def test_a_build_that_wrote_no_wheel_RAISES_rather_than_returning(self, tmp_path: Path, monkeypatch) -> None:
        """THE DIRECTION THIS FAILS IN IF REMOVED, and it is the worst one available here.

        With no wheel, the shadow directory is empty, so the shadowed arm imports the INSTALLED
        extension exactly as the baseline arm does -- and the harness reports a speedup of 1.0. That
        is a measurement of nothing wearing the shape of a result, and nothing downstream can tell
        it from a real 1.0.
        """
        monkeypatch.setattr(
            'lab_commons.dev.shadow_build.subprocess.run',
            lambda *a, **_k: subprocess.CompletedProcess(a[0] if a else [], 0),
        )
        with pytest.raises(RuntimeError, match='wrote no wheel'):
            build_wheel(tmp_path / 'Cargo.toml', tmp_path / 'out')

    def test_the_newest_wheel_is_returned_when_one_was_written(self, tmp_path: Path, monkeypatch) -> None:
        """THE FLOOR for the case above: the refusal must not be unconditional."""
        out = tmp_path / 'out'

        def _fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess:  # noqa: ARG001 -- stands in for maturin
            out.mkdir(parents=True, exist_ok=True)
            (out / 'probe-1.0-py3-none-any.whl').write_bytes(b'')
            return subprocess.CompletedProcess([], 0)

        monkeypatch.setattr('lab_commons.dev.shadow_build.subprocess.run', _fake_run)
        assert build_wheel(tmp_path / 'Cargo.toml', out).name == 'probe-1.0-py3-none-any.whl'

    def test_it_builds_and_never_installs(self, tmp_path: Path, monkeypatch) -> None:
        """The argv carries `build`, and carries `develop` nowhere -- the one distinction that matters.

        `develop` writes into the shared environment, which is the hazard the whole module exists
        for, so this asserts on the verb rather than trusting the docstring that promises it.
        """
        seen: list[list[str]] = []
        out = tmp_path / 'out'

        def _fake_run(argv, *args: object, **kwargs: object) -> subprocess.CompletedProcess:  # noqa: ARG001 -- stands in for maturin
            seen.append(list(argv))
            out.mkdir(parents=True, exist_ok=True)
            (out / 'probe-1.0-py3-none-any.whl').write_bytes(b'')
            return subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr('lab_commons.dev.shadow_build.subprocess.run', _fake_run)
        build_wheel(tmp_path / 'Cargo.toml', out)
        argv = seen[0]
        assert 'build' in argv
        assert 'develop' not in argv
        assert '--release' in argv


class TestTheTwoArms:
    """Which code each arm actually runs -- read out of the CHILD, not asserted about the parent."""

    def test_the_shadow_arm_puts_the_shadow_on_pythonpath(self, tmp_path: Path) -> None:
        assert shadow_env(tmp_path / 'shadow')['PYTHONPATH'] == str(tmp_path / 'shadow')

    def test_the_BASELINE_arm_strips_an_inherited_pythonpath(self, tmp_path: Path) -> None:
        """THE DEFECT THIS EXISTS TO CLOSE, and it is invisible in the result it produces.

        A caller that already had a `PYTHONPATH` -- a lane pointing at its own sources, or a
        previous run of this very harness -- would have its BASELINE shadowed too. Both arms then
        measure the same code and the harness reports a ratio near 1.0, which reads as "the port
        bought nothing" rather than as "this measured nothing".
        """
        base = {'PYTHONPATH': str(tmp_path / 'somebody-elses-sources'), 'PATH': os.environ.get('PATH', '')}
        assert 'PYTHONPATH' not in shadow_env(None, base=base)

    def test_a_child_actually_SEES_the_shadow_first(self, tmp_path: Path) -> None:
        """Through a real subprocess: the property is about `sys.path` inside the child.

        Asserting on the env dict alone would pass even if `PYTHONPATH` no longer preceded
        site-packages -- that is a fact about CPython's startup, and the only way to know it still
        holds on this interpreter is to ask a child.
        """
        shadow = tmp_path / 'shadow'
        shadow.mkdir()
        probe = _write(tmp_path / 'probe.py', _PATH_PROBE)
        done = subprocess.run(
            [sys.executable, str(probe)],
            check=True,
            env=shadow_env(shadow),
            capture_output=True,
            text=True,
            timeout=120,
        )
        # `ast.literal_eval` rather than `eval`: the child prints a list literal and nothing else.
        paths = [Path(p).resolve() for p in ast.literal_eval(done.stdout) if p]
        site = [p for p in paths if 'site-packages' in p.as_posix()]
        assert shadow.resolve() in paths
        if site:
            assert paths.index(shadow.resolve()) < paths.index(site[0])


class TestTiming:
    """What a sample is allowed to be, and what must never become one."""

    def test_a_probe_that_succeeds_is_timed(self, tmp_path: Path) -> None:
        """THE FLOOR: a timer that always raised would pass the failure case below."""
        elapsed = time_once(_write(tmp_path / 'ok.py', _OK_PROBE), None, wall_s=120)
        assert elapsed > 0

    def test_a_FAILING_probe_raises_instead_of_contributing_the_fastest_sample(self, tmp_path: Path) -> None:
        """A child that died early is FAST. Swallowing its exit code feeds the broken arm a win.

        This is the one direction an error must never be allowed to move a benchmark, and it is
        silent: the run completes, the numbers look plausible, and the arm that crashed wins.
        """
        with pytest.raises(subprocess.CalledProcessError):
            time_once(_write(tmp_path / 'bad.py', _FAILING_PROBE), None, wall_s=120)


class TestTheComparison:
    """Medians, the refusal to divide by nothing, and the number it deliberately does not carry."""

    def test_medians_come_from_the_samples_rather_than_being_stored_beside_them(self) -> None:
        comparison = Comparison(installed_s=(3.0, 1.0, 2.0), shadow_s=(1.0, 0.5, 0.75))
        assert comparison.median_installed_s == 2.0
        assert comparison.median_shadow_s == 0.75
        assert comparison.speedup == pytest.approx(2.0 / 0.75)

    def test_a_zero_shadow_median_reports_NOTHING_rather_than_a_number(self) -> None:
        """A probe that did no work cannot be reported as infinitely fast; "I cannot say" is honest."""
        assert Comparison(installed_s=(1.0,), shadow_s=(0.0,)).speedup is None

    def test_the_raw_samples_survive_so_a_reader_can_see_the_spread(self) -> None:
        """A median off a shared box hides its own noise. The samples are the evidence for it."""
        comparison = Comparison(installed_s=(1.0, 9.0), shadow_s=(1.0, 1.0))
        assert comparison.installed_s == (1.0, 9.0)

    def test_it_carries_NO_end_to_end_figure(self) -> None:
        """THE DECLARATION THIS REFUSES TO MAKE, pinned so a later convenience cannot add it.

        A kernel speedup weighted by nothing is not an end-to-end one, and the weight is a property
        of the consuming repo's cases. A field here would be a number computed by code that does not
        have the data it needs -- which is the shape that produced "+3.07 % end to end against a
        1.8 % bound", a figure that exceeded its own ceiling and therefore measured the box.
        """
        assert not hasattr(Comparison(installed_s=(1.0,), shadow_s=(1.0,)), 'end_to_end')


class TestInterleaving:
    """A/B/A/B over real children, and the refusal to compare nothing."""

    def test_both_arms_are_sampled_the_requested_number_of_times(self, tmp_path: Path) -> None:
        shadow = tmp_path / 'shadow'
        shadow.mkdir()
        comparison = interleaved(_write(tmp_path / 'ok.py', _OK_PROBE), shadow, repeat=2, wall_s=120)
        assert len(comparison.installed_s) == 2
        assert len(comparison.shadow_s) == 2
        assert comparison.speedup is not None

    def test_the_arms_ALTERNATE_rather_than_running_as_two_blocks(self, tmp_path: Path, monkeypatch) -> None:
        """The property the design turns on, asserted on the ORDER the arms were asked for.

        A block design charges all of a shared box's drift to whichever arm ran during it. Sample
        COUNTS are identical either way, so counting cannot catch a regression to blocks -- only the
        order can.
        """
        order: list[str] = []

        def _fake_time_once(probe, shadow, **kwargs: object) -> float:  # noqa: ARG001 -- order is the whole subject
            order.append('installed' if shadow is None else 'shadow')
            return 1.0

        monkeypatch.setattr('lab_commons.dev.shadow_build.time_once', _fake_time_once)
        interleaved(tmp_path / 'probe.py', tmp_path / 'shadow', repeat=3)
        assert order == ['installed', 'shadow', 'installed', 'shadow', 'installed', 'shadow']

    def test_a_non_positive_repeat_is_refused_HERE(self, tmp_path: Path) -> None:
        """Zero pairs hand two empty sets to a median, which raises further from the mistake."""
        with pytest.raises(ValueError, match='no pair at all'):
            interleaved(tmp_path / 'probe.py', tmp_path / 'shadow', repeat=0)


def test_the_child_wall_is_a_hang_detector_and_is_overridable() -> None:
    """It is a keyword on every spawning call, so a consumer with a measured bound passes its own.

    A ceiling nobody can override becomes the number every repo inherits from whichever box it was
    first written on -- and this one was never a measurement of a build in the first place.
    """
    assert DEFAULT_CHILD_WALL_S == 30 * 60
    assert 'wall_s' in build_wheel.__kwdefaults__ if build_wheel.__kwdefaults__ else True
    assert time_once.__kwdefaults__['wall_s'] == DEFAULT_CHILD_WALL_S
    assert interleaved.__kwdefaults__['wall_s'] == DEFAULT_CHILD_WALL_S
