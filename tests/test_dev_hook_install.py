"""``lab_commons.dev.hook_install`` -- driven on REAL git repositories, both ways.

WHY A REAL REPOSITORY AND NOT A STUB. The one thing this module is for is resolving the hooks
directory THROUGH git rather than string-building ``.git/hooks``, so a test that plants a directory
and skips ``git`` would prove exactly the property that does not need proving. Every case below
``git init``s a tree and asks the module about it.

BOTH DIRECTIONS FOR EVERY STATUS. The module has four per-stage verdicts and three top-level ones,
and each is a decision somebody could get wrong in the direction that reads as safe -- a foreign
hook counted as installed, an unread configuration counted as an empty one. So each is PLANTED and
driven through the real function rather than asserted about in prose.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from lab_commons.dev.hook_install import (
    ABSENT,
    FOREIGN,
    INSTALLED,
    NOTHING_DECLARED,
    PROTECTED,
    STALE,
    UNPROTECTED,
    declared_stages,
    generated_hook,
    hook_installation,
    hooks_dir,
    install_command,
    report_installation,
)

_GIT = shutil.which('git') or 'git'

#: A configuration in exactly the block-sequence shape pre-commit's own documentation uses, with a
#: hook at each of the three stages this family declares, one using pre-commit's DEPRECATED
#: spelling (``push``), and one naming no stage at all.
_CONFIG = """\
repos:
  - repo: https://example.invalid/a
    rev: v1
    hooks:
      - id: ruff
      - id: gate
        stages: [pre-push]
      - id: legacy-gate
        stages: [push]
      - id: commitizen
        stages: [commit-msg]
"""


def _repo(at: Path, *, config: str | None = _CONFIG) -> Path:
    at.mkdir(parents=True, exist_ok=True)
    subprocess.run([_GIT, 'init', '-q', str(at)], check=True, capture_output=True, timeout=60)
    if config is not None:
        (at / '.pre-commit-config.yaml').write_text(config, encoding='utf-8')
    return at


def test_the_declared_set_is_read_off_the_configuration(tmp_path: Path) -> None:
    """THE FLOOR ON THIS READER: a parser that found nothing would agree with every tree."""
    repo = _repo(tmp_path / 'r')
    stages = declared_stages(repo / '.pre-commit-config.yaml')
    assert set(stages) == {'pre-commit', 'pre-push', 'commit-msg'}, stages
    assert stages['pre-commit'] == ('ruff',), 'a hook naming no stage runs at pre-commit'
    assert stages['pre-push'] == ('gate', 'legacy-gate'), 'the deprecated `push` spelling is the same hook TYPE'


def test_an_unread_configuration_raises_rather_than_reporting_an_empty_one(tmp_path: Path) -> None:
    """Two facts, not one: "declares nothing" and "could not be read" must never collapse."""
    repo = _repo(tmp_path / 'r', config='hooks:\n  - id: ruff\n')
    with pytest.raises(ValueError, match='repos:'):
        declared_stages(repo / '.pre-commit-config.yaml')
    empty = _repo(tmp_path / 'e', config='repos: []\n')
    with pytest.raises(ValueError, match='parsed no hook ids'):
        declared_stages(empty / '.pre-commit-config.yaml')


def test_the_hooks_directory_is_the_one_git_names(tmp_path: Path) -> None:
    """Asked of git, never string-built -- the property a worktree and `core.hooksPath` both break."""
    repo = _repo(tmp_path / 'r')
    named = subprocess.run(
        [_GIT, '-C', str(repo), 'rev-parse', '--git-path', 'hooks'],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout.strip()
    assert hooks_dir(repo).resolve() == (repo / named).resolve()

    redirected = tmp_path / 'elsewhere'
    redirected.mkdir()
    subprocess.run(
        [_GIT, '-C', str(repo), 'config', 'core.hooksPath', str(redirected)],
        check=True,
        capture_output=True,
        timeout=60,
    )
    assert hooks_dir(repo).resolve() == redirected.resolve(), 'core.hooksPath redirects the directory git consults'


def test_this_guard_goes_both_ways(tmp_path: Path) -> None:
    """PLANTED CONTROL. The same tree, unprotected then protected, through the REAL reader."""
    repo = _repo(tmp_path / 'r')

    absent = hook_installation(repo)
    assert absent.verdict == UNPROTECTED
    assert {stage.status for stage in absent.stages} == {ABSENT}
    assert len(absent.failing) == len(absent.stages) == 3

    directory = hooks_dir(repo)
    directory.mkdir(parents=True, exist_ok=True)
    for stage in absent.stages:
        (directory / stage.stage).write_text(
            generated_hook(config_name='.pre-commit-config.yaml', hook_type=stage.stage), encoding='utf-8'
        )

    installed = hook_installation(repo)
    assert installed.verdict == PROTECTED
    assert {stage.status for stage in installed.stages} == {INSTALLED}
    assert installed.failing == ()


def test_a_stale_or_foreign_hook_is_not_an_installed_one(tmp_path: Path) -> None:
    """The two statuses that exist because "a file is there" is not the question being asked."""
    repo = _repo(tmp_path / 'r')
    directory = hooks_dir(repo)
    directory.mkdir(parents=True, exist_ok=True)

    (directory / 'pre-commit').write_text('#!/bin/sh\necho mine\n', encoding='utf-8')
    (directory / 'pre-push').write_text(
        generated_hook(config_name='.other-config.yaml', hook_type='pre-push'), encoding='utf-8'
    )
    (directory / 'commit-msg').write_text(
        generated_hook(config_name='.pre-commit-config.yaml', hook_type='pre-commit'), encoding='utf-8'
    )

    report = hook_installation(repo)
    assert {stage.stage: stage.status for stage in report.stages} == {
        'pre-commit': FOREIGN,
        'pre-push': STALE,
        'commit-msg': STALE,
    }
    assert report.verdict == UNPROTECTED


def test_a_repo_with_no_configuration_is_neither_pass_nor_fail(tmp_path: Path) -> None:
    """THREE ANSWERS. Folding this into `PROTECTED` is how a lost configuration reads as green."""
    repo = _repo(tmp_path / 'r', config=None)
    report = hook_installation(repo)
    assert report.verdict == NOTHING_DECLARED
    assert report.config is None
    assert report_installation(['--repo', str(repo)]) == 2


def test_the_remedy_is_derived_from_the_configuration(tmp_path: Path) -> None:
    """THE REFUSAL NAMES ITS REMEDY, and the remedy may not be a restatement of the stage list.

    A stage added to the configuration must appear in the install command WITHOUT anybody editing
    a second list -- the measured failure was a Makefile naming two of three stages, which left a
    whole stage declared and never installed while the hooks directory looked populated.
    """
    repo = _repo(tmp_path / 'r')
    assert install_command(repo) == [
        '-m',
        'pre_commit',
        'install',
        '--install-hooks',
        '-t',
        'commit-msg',
        '-t',
        'pre-commit',
        '-t',
        'pre-push',
    ]

    (repo / '.pre-commit-config.yaml').write_text(
        _CONFIG + '      - id: merge-guard\n        stages: [pre-merge-commit]\n', encoding='utf-8'
    )
    assert '-t pre-merge-commit' in ' '.join(install_command(repo)), 'the new stage arrived without a second edit'


def test_the_cli_exit_codes_separate_the_three_answers(tmp_path: Path) -> None:
    """0 / 1 / 2, driven for real: a reader that cannot tell them apart has one answer, not three."""
    repo = _repo(tmp_path / 'r')
    assert report_installation(['--repo', str(repo)]) == 1
    directory = hooks_dir(repo)
    directory.mkdir(parents=True, exist_ok=True)
    for stage in ('pre-commit', 'pre-push', 'commit-msg'):
        (directory / stage).write_text(
            generated_hook(config_name='.pre-commit-config.yaml', hook_type=stage), encoding='utf-8'
        )
    assert report_installation(['--repo', str(repo)]) == 0
