"""A network verb in a repo that declares no ``[tool.dev_lab.doors]`` is sent to the family retry door.

MEASURED 2026-11-22: a session in one repo ran ``git fetch`` inside a sibling that declares no doors; the engine
withheld the session's wrapper (rightly: that file is the session repo's) and said only "declare one in its
pyproject.toml" -- no door an agent could take. The retry verb needs no file of the target: ``python -m
dev_lab.dev.netverb -- git <verb>`` runs from any directory.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from dev_lab.dev import agenthooks
from dev_lab.dev.hook_adoption import HookAdoption, render
from dev_lab.dev.hooks import Remedy

SESSION_WRAPPER = 'sh scripts/session_only/with-retry.sh'
FAMILY_DOOR = '-m dev_lab.dev.netverb -- git <verb>'
TARGET_DOOR = 'sh tools/target_only_retry.sh'
SESSION_KILLER = 'python scripts/session_only/stop.py --pid N'
SESSION_RUNNER = 'python scripts/session_only/runner.py measure'


@pytest.fixture
def repos(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A session repo whose rules name its own retry wrapper, a sibling declaring no door, and the rules file."""
    session, bare = tmp_path / 'session', tmp_path / 'bare'
    for repo in (session, bare):
        (repo / '.git').mkdir(parents=True)
    hooks = session / '.claude' / 'hooks'
    hooks.mkdir(parents=True)
    adoption = HookAdoption(
        app_name='session',
        remedies={
            'NETWORK-VERB': Remedy('retry-wrapper', SESSION_WRAPPER),
            'RAW-PROCESS-KILL': Remedy('process-tree-killer', SESSION_KILLER),
            'BARE-TEST-INVOCATION': Remedy('verdict-entry-point', SESSION_RUNNER),
            'PUSH-NO-VERIFY': Remedy('verdict-entry-point', SESSION_RUNNER),
        },
    )
    rules = hooks / 'deny-rules.json'
    rules.write_text(render(adoption), encoding='utf-8')
    return session, bare, rules


@pytest.mark.parametrize('command', ['git fetch origin', 'git pull --rebase', 'uv sync'])
def test_a_repo_declaring_no_door_is_sent_to_the_family_retry_door(
    repos: tuple[Path, Path, Path], command: str
) -> None:
    _session, bare, rules = repos
    said = agenthooks.decide(command, rules, cwd=bare, hint=True)
    assert said is not None
    assert said.startswith('NETWORK-VERB:'), said
    assert FAMILY_DOOR in said, said
    assert SESSION_WRAPPER not in said, 'the session repo`s wrapper is not a file of the target'
    assert '[tool.dev_lab.doors] NETWORK-VERB' not in said, 'a declaration to add is not a door to take'


def test_the_session_repo_keeps_its_own_wrapper(repos: tuple[Path, Path, Path]) -> None:
    """PLANTED CONTROL: no other repo targeted, so the session's own row speaks unchanged."""
    session, _bare, rules = repos
    said = agenthooks.decide('git fetch origin', rules, cwd=session, hint=True)
    assert said is not None
    assert SESSION_WRAPPER in said
    assert FAMILY_DOOR not in said


def test_a_repo_declaring_its_door_keeps_it(repos: tuple[Path, Path, Path], tmp_path: Path) -> None:
    """PLANTED CONTROL: the family door answers only an UNDECLARED target; a declared door wins."""
    _session, _bare, rules = repos
    declared = tmp_path / 'declared'
    (declared / '.git').mkdir(parents=True)
    (declared / 'pyproject.toml').write_text(
        f'[project]\nname = "d"\n\n[tool.dev_lab.doors]\nNETWORK-VERB = "{TARGET_DOOR}"\n', encoding='utf-8'
    )
    said = agenthooks.decide('git fetch origin', rules, cwd=declared, hint=True)
    assert said is not None
    assert TARGET_DOOR in said
    assert FAMILY_DOOR not in said


def test_a_raw_kill_in_a_repo_declaring_no_door_is_sent_to_the_family_stop_door(
    repos: tuple[Path, Path, Path],
) -> None:
    """The same gap, measured the same day on this kit's own checkout: the stop door reads no file of the target."""
    _session, bare, rules = repos
    reason = agenthooks.decide('taskkill /PID 1234 /T /F', rules, cwd=bare)
    assert reason is not None
    assert '-m dev_lab.dev.stoprun --pid <pid>' in reason, reason
    assert SESSION_KILLER not in reason
    assert '[tool.dev_lab.doors] RAW-PROCESS-KILL' not in reason


def test_a_rule_whose_door_is_a_file_of_the_target_is_still_told_the_declaration_to_add(
    repos: tuple[Path, Path, Path],
) -> None:
    """PLANTED CONTROL: a verdict runs the TARGET's tests in the target's environment, so no family door stands in."""
    _session, bare, rules = repos
    reason = agenthooks.decide('pytest tests/', rules, cwd=bare)
    assert reason is not None
    assert '[tool.dev_lab.doors] BARE-TEST-INVOCATION = ' in reason, reason
    assert 'netverb' not in reason
    assert 'stoprun' not in reason


KIT_DOOR = '<venv python> -m dev_lab.dev.netverb -- git <verb>'
TAIL = ('Scripts', 'python.exe') if os.name == 'nt' else ('bin', 'python')


def _venv(checkout: Path, *, carries_dev_lab: bool) -> Path:
    """``checkout``'s ``.venv`` interpreter, with dev_lab installed in it or not; the interpreter path."""
    python = checkout.joinpath('.venv', *TAIL)
    python.parent.mkdir(parents=True)
    python.write_bytes(b'')
    site = checkout.joinpath('.venv', *(('Lib',) if os.name == 'nt' else ('lib', 'python3.12')), 'site-packages')
    site.mkdir(parents=True)
    if carries_dev_lab:
        (site / 'dev_lab-1.0.dist-info').mkdir()
    return python


def _declaring_kit_door(tmp_path: Path, *, carries_dev_lab: bool) -> Path:
    target = tmp_path / 'declared'
    (target / '.git').mkdir(parents=True)
    (target / 'pyproject.toml').write_text(
        f'[project]\nname = "d"\n\n[tool.dev_lab.doors]\nNETWORK-VERB = "{KIT_DOOR}"\n', encoding='utf-8'
    )
    _venv(target, carries_dev_lab=carries_dev_lab)
    return target


def test_a_declared_door_whose_venv_lacks_dev_lab_names_the_bootstrap(
    repos: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    """A declared door whose interpreter lacks dev_lab names the bootstrap, run from the target, first.

    MEASURED 2026-11-25: the refusal named ``<target>/.venv/.../python -m dev_lab.dev.netverb``, a venv without
    dev_lab, because the door only checked that the interpreter EXISTS -- a door that cannot run.
    """
    session, _bare, rules = repos
    session_python = _venv(session, carries_dev_lab=True)
    target = _declaring_kit_door(tmp_path, carries_dev_lab=False)
    said = agenthooks.decide('git fetch origin', rules, cwd=target, hint=True)
    assert said is not None
    assert said.startswith('NETWORK-VERB:'), said
    lowered = said.lower()
    assert 'does not carry dev_lab' in lowered, said
    bootstrap = (
        f'cd {target.as_posix()} && {session_python.as_posix()} -m dev_lab.dev.dep --bootstrap {target.as_posix()}'
    )
    assert bootstrap.lower() in lowered, said


def test_a_declared_door_whose_venv_carries_dev_lab_is_named_as_is(
    repos: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    """PLANTED CONTROL: the target's venv carries dev_lab, so its netverb door is the exit and no bootstrap is."""
    session, _bare, rules = repos
    _venv(session, carries_dev_lab=True)
    target = _declaring_kit_door(tmp_path, carries_dev_lab=True)
    said = agenthooks.decide('git fetch origin', rules, cwd=target, hint=True)
    assert said is not None
    door = f'{target.joinpath(".venv", *TAIL).as_posix()} -m dev_lab.dev.netverb -- git <verb>'
    assert door.lower() in said.lower(), said
    assert 'dev_lab.dev.dep --bootstrap' not in said, said
