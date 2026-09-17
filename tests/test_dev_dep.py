"""THE DEPENDENCY DOOR, driven by planted controls in BOTH directions.

Every refusal here plants its cause and calls the REAL function: a held lock is a port that answers
with a holder, a moved `env_key` is a port whose key function answers differently after the change,
and the anchors retired are real files on disk that this test writes and then asserts are gone.

TWO-SIDED THROUGHOUT, because a door that refuses everything passes a one-sided test: each refusal
is paired with the permitted case that must still pass -- a free lock permits, an unmoved key
retires NOTHING, and a repo that declares no lock at all is permitted with the gap RENDERED rather
than skipped.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

import pytest

from lab_commons.dev.dep import (
    LOCK_UNDECLARED,
    NO_ANCHORS_DECLARED,
    HeldEnvironmentError,
    Mode,
    Port,
    Version,
    current_env_key,
    mutate,
    pip_argv,
    refuse_if_locked,
)

_REQS: Final = ('example-package==1.2.3',)


class _Run:
    """A stand-in for `subprocess.run` that records its argv and answers a chosen return code."""

    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: list[str], **kwargs: object) -> _Run:
        self.calls.append(tuple(argv))
        return self


def _keys(*values: str):
    """A key function that answers *values* in order -- the planted 'the environment moved' control."""
    seen = iter(values)
    last = [values[-1]]

    def key() -> str:
        last[0] = next(seen, last[0])
        return last[0]

    return key


def _anchors(tmp_path: Path, *names: str) -> tuple[Path, ...]:
    paths = tuple(tmp_path / name for name in names)
    for path in paths:
        path.write_text('[VERDICT tree=abc env=def] PASS\n', encoding='utf-8')
    return paths


def test_the_prefix_is_this_interpreters_and_never_a_parsed_path() -> None:
    """Step 1: the environment is MEASURED, so a sibling repo cannot be caught by a scope bug."""
    run = _Run()
    report = mutate(_REQS, port=Port(name='somewhere'), run=run)
    assert report.prefix == sys.prefix


def test_a_held_lock_refuses_and_names_the_holder_and_the_remedy() -> None:
    """PLANTED CONTROL, H1: a lock that answers with a holder must stop the mutation."""
    port = Port(name='repo-under-test', holders=lambda: ('gate:integrate/main since 12:01',))
    with pytest.raises(HeldEnvironmentError) as caught:
        refuse_if_locked(port)
    message = str(caught.value)
    assert 'gate:integrate/main since 12:01' in message
    assert 'Wait for that run to finish and re-issue' in message


def test_a_held_lock_refuses_the_whole_door_and_runs_nothing() -> None:
    run = _Run()
    port = Port(name='repo-under-test', holders=lambda: ('heavy:main',))
    with pytest.raises(HeldEnvironmentError):
        mutate(_REQS, port=port, run=run)
    assert run.calls == [], 'the refusal must precede the mutation, or it guarded nothing'


def test_a_free_lock_permits_and_the_command_runs() -> None:
    """THE OTHER SIDE. A door that refuses a free lock too would pass the test above."""
    run = _Run()
    port = Port(name='repo-under-test', holders=tuple)
    report = mutate(_REQS, port=port, run=run)
    assert len(run.calls) == 1
    assert report.returncode == 0
    assert LOCK_UNDECLARED not in report.render()


def test_a_repo_with_no_lock_is_permitted_and_the_gap_is_rendered() -> None:
    """Honest degradation: optimi-lab today. Steps 1 and 3 run; step 2 is VISIBLY absent."""
    run = _Run()
    report = mutate(_REQS, port=Port(name='no-lock-repo'), run=run)
    assert len(run.calls) == 1
    assert LOCK_UNDECLARED in report.render()
    assert 'no-lock-repo' in report.render()


def test_a_moved_env_key_retires_every_anchor_that_exists(tmp_path: Path) -> None:
    """PLANTED CONTROL, H2: the key differs across the change, so the verdicts about it are dead."""
    anchors = _anchors(tmp_path, 'gate.verdict', 'heavy.verdict')
    port = Port(
        name='repo-under-test',
        holders=tuple,
        anchor_paths=lambda: anchors,
        key=_keys('before-key', 'after-key'),
    )
    report = mutate(_REQS, port=port, run=_Run())
    assert report.moved is True
    assert set(report.retired) == {str(path) for path in anchors}
    assert [path.exists() for path in anchors] == [False, False]
    assert 'after-key' in report.render()


def test_an_unmoved_env_key_retires_nothing(tmp_path: Path) -> None:
    """THE OTHER SIDE, and the one that matters: a no-op install must not destroy a live verdict."""
    anchors = _anchors(tmp_path, 'gate.verdict')
    port = Port(name='repo-under-test', holders=tuple, anchor_paths=lambda: anchors, key=_keys('same', 'same'))
    report = mutate(_REQS, port=port, run=_Run())
    assert report.moved is False
    assert report.retired == ()
    assert anchors[0].exists()


def test_an_anchor_that_does_not_exist_is_not_reported_as_retired(tmp_path: Path) -> None:
    port = Port(
        name='repo-under-test',
        holders=tuple,
        anchor_paths=lambda: (tmp_path / 'never-written.verdict',),
        key=_keys('before', 'after'),
    )
    report = mutate(_REQS, port=port, run=_Run())
    assert report.moved is True
    assert report.retired == ()


def test_a_repo_with_no_anchors_declared_renders_the_gap() -> None:
    """A moved key with nowhere to remedy it must SAY so; a silent pass is the vacuous green."""
    port = Port(name='no-anchor-repo', holders=tuple, key=_keys('before', 'after'))
    report = mutate(_REQS, port=port, run=_Run())
    assert report.moved is True
    assert NO_ANCHORS_DECLARED in report.render()


def test_a_declared_but_empty_anchor_set_is_not_the_same_as_undeclared() -> None:
    port = Port(name='repo', holders=tuple, anchor_paths=tuple, key=_keys('before', 'after'))
    report = mutate(_REQS, port=port, run=_Run())
    assert NO_ANCHORS_DECLARED not in report.render()


def test_resolution_is_the_default_and_pinned_is_the_narrow_mode() -> None:
    resolving = pip_argv(_REQS, mode=Mode.RESOLVE, python='py')
    pinned = pip_argv(_REQS, mode=Mode.PINNED, python='py')
    assert '--no-index' not in resolving, 'a dependency change that cannot resolve is not a dependency change'
    assert '--no-deps' not in resolving
    assert '--no-index' in pinned
    assert '--no-deps' in pinned
    assert resolving[:4] == ('py', '-m', 'pip', 'install')


def test_a_repeating_version_forces_a_reinstall_and_an_identifying_one_never_does() -> None:
    """THE RATCHET, both sides. Measured against pip 26.2.1's resolver: a local wheel already
    installed at the same version is SKIPPED with exit code 0 unless `--force-reinstall` is given --
    so a self-build needs the flag. Every other install must NOT get it: forcing a published
    dependency reinstalls bytes that are already correct, on every call.
    """
    repeats = pip_argv(_REQS, mode=Mode.PINNED, version=Version.REPEATS, python='py')
    assert '--force-reinstall' in repeats
    for mode in Mode:
        identifies = pip_argv(_REQS, mode=mode, version=Version.IDENTIFIES, python='py')
        assert '--force-reinstall' not in identifies, f'{mode} forced a reinstall nobody asked for'
        assert pip_argv(_REQS, mode=mode, python='py') == identifies, 'IDENTIFIES must be the default'
    assert len(list(Mode)) == 2, 'the floor: this scan must cover every mode there is'


def test_the_argv_the_report_declares_is_the_argv_the_child_was_given() -> None:
    """THE DECLARATION. `Report.argv` is the only thing a reader sees, so it must BE the command.

    This is the defect that produced `Version`: a caller needing a flag the door would not emit
    composed it into the injected `run`, and the report then named a command pip never got. The
    door answers the fact instead, and the argv stays single-sourced.
    """
    run = _Run()
    port = Port(name='repo', holders=tuple, anchor_paths=tuple, key=_keys('same'))
    report = mutate(_REQS, port=port, mode=Mode.PINNED, version=Version.REPEATS, run=run)
    assert len(run.calls) == 1, 'the floor: a scan over no call is vacuous'
    assert run.calls[0] == report.argv
    assert '--force-reinstall' in report.render(), 'a flag absent from the rendered command is unread'


def test_a_dry_run_checks_everything_and_mutates_nothing(tmp_path: Path) -> None:
    anchors = _anchors(tmp_path, 'gate.verdict')
    run = _Run()
    port = Port(name='repo', holders=tuple, anchor_paths=lambda: anchors, key=_keys('before', 'after'))
    report = mutate(_REQS, port=port, run=run, dry_run=True)
    assert run.calls == []
    assert report.returncode is None
    assert anchors[0].exists(), 'a dry run that retired an anchor would have mutated the thing it reports on'
    assert 'would install' in report.render()


def test_a_dry_run_still_refuses_a_held_lock() -> None:
    port = Port(name='repo', holders=lambda: ('gate:lane',))
    with pytest.raises(HeldEnvironmentError):
        mutate(_REQS, port=port, run=_Run(), dry_run=True)


def test_a_failed_command_still_checks_whether_the_environment_moved(tmp_path: Path) -> None:
    """A non-zero pip is not a promise that nothing changed, and the door does not make one."""
    anchors = _anchors(tmp_path, 'gate.verdict')
    port = Port(name='repo', holders=tuple, anchor_paths=lambda: anchors, key=_keys('before', 'after'))
    report = mutate(_REQS, port=port, run=_Run(returncode=1), dry_run=False)
    assert report.returncode == 1
    assert report.moved is True
    assert not anchors[0].exists()


def test_an_empty_requirement_set_refuses_rather_than_running_a_bare_pip() -> None:
    with pytest.raises(ValueError, match='names nothing'):
        mutate((), port=Port(name='repo'), run=_Run())


def test_the_shared_key_is_available_to_every_repo_without_an_adapter() -> None:
    """The env_key half of the port has a default, which is why only lock and anchors are injected."""
    first, second = current_env_key(), current_env_key()
    assert first == second
    assert len(first) >= 8
