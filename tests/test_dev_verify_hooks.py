"""``verify`` carries the hooks-installed check as a STEP, so a narrowed run cannot skip it.

User directive 2026-09-23: guarantee the pre-commit hooks by test or mechanism. The adoption test
(``test_the_declared_hooks_are_installed.py``) only runs when a suite selects it; a verify narrowed to
one path never does. As a verify step the check runs on EVERY verify in every family repo, and the
only path that skips it is one where verify is not run at all.
"""

from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

from lab_commons.dev.hook_install import generated_hook, hooks_dir
from lab_commons.dev.verify import HOOKS_STEP, read_hooks

_GIT = shutil.which('git') or 'git'
_CONFIG = 'repos:\n  - repo: https://example.invalid/a\n    rev: v1\n    hooks:\n      - id: ruff\n'


def _repo(at: Path, *, config: str | None = _CONFIG) -> Path:
    at.mkdir(parents=True)
    subprocess.run([_GIT, 'init', '-q', str(at)], check=True, capture_output=True, timeout=60)
    if config is not None:
        (at / '.pre-commit-config.yaml').write_text(config, encoding='utf-8')
    return at


def test_an_unprotected_checkout_is_a_named_failure_with_its_remedy(tmp_path: Path) -> None:
    repo = _repo(tmp_path / 'r')
    handle = io.StringIO()
    report = read_hooks(repo, handle=handle)
    assert report.failures == (HOOKS_STEP,)
    assert report.reported == (HOOKS_STEP,)
    assert 'pre_commit install' in handle.getvalue(), 'the refusal names its remedy'


def test_a_protected_checkout_reports_clean(tmp_path: Path) -> None:
    repo = _repo(tmp_path / 'r')
    directory = hooks_dir(repo)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'pre-commit').write_text(
        generated_hook(config_name='.pre-commit-config.yaml', hook_type='pre-commit'), encoding='utf-8'
    )
    report = read_hooks(repo, handle=io.StringIO())
    assert report.reported == (HOOKS_STEP,)
    assert report.failures == ()


def test_a_repo_declaring_nothing_has_nothing_to_guard(tmp_path: Path) -> None:
    report = read_hooks(_repo(tmp_path / 'r', config=None), handle=io.StringIO())
    assert report.reported == (HOOKS_STEP,)
    assert report.failures == ()
