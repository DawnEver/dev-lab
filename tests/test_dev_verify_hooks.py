"""``verify`` carries the hooks-installed check as a STEP, so a narrowed run cannot skip it.

User directive 2026-09-23: guarantee the git hooks by test or mechanism. The adoption test
(``test_the_declared_hooks_are_installed.py``) only runs when a suite selects it; a verify narrowed to
one path never does. As a verify step the check runs on EVERY verify in every family repo.
"""

from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

from lab_commons.dev.hook_install import INSTALL_COMMAND, install
from lab_commons.dev.verify import HOOKS_STEP, read_hooks

_GIT = shutil.which('git') or 'git'


def _repo(at: Path) -> Path:
    at.mkdir(parents=True)
    subprocess.run([_GIT, 'init', '-q', str(at)], check=True, capture_output=True, timeout=60)
    (at / 'pyproject.toml').write_text('[tool.lab_commons.hooks]\n', encoding='utf-8')
    return at


def test_an_unprotected_checkout_is_a_named_failure_with_its_remedy(tmp_path: Path) -> None:
    handle = io.StringIO()
    report = read_hooks(_repo(tmp_path / 'r'), handle=handle)
    assert report.failures == (HOOKS_STEP,)
    assert report.reported == (HOOKS_STEP,)
    assert INSTALL_COMMAND in handle.getvalue(), 'the refusal names its remedy'


def test_a_protected_checkout_reports_clean(tmp_path: Path) -> None:
    repo = _repo(tmp_path / 'r')
    install(repo)
    report = read_hooks(repo, handle=io.StringIO())
    assert report.reported == (HOOKS_STEP,)
    assert report.failures == ()


def test_a_checkout_that_does_not_opt_in_has_nothing_to_guard(tmp_path: Path) -> None:
    at = tmp_path / 'r'
    at.mkdir()
    subprocess.run([_GIT, 'init', '-q', str(at)], check=True, capture_output=True, timeout=60)
    report = read_hooks(at, handle=io.StringIO())
    assert report.failures == ()
