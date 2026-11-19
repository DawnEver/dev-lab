"""A HOOK THAT CANNOT START NEVER BLOCKS (dev-lab #639): the launcher turns a wiring fault into one line and exit 0.

A child's argparse usage exit or a missing module blocked every prompt (exit 2 on UserPromptSubmit) and looped every
Stop. PLANTED CONTROL: a deliberate refusal -- exit 2 naming its rule, no usage text -- still blocks.
"""

from __future__ import annotations

import os
import subprocess
import venv
from pathlib import Path

import pytest

from dev_lab.dev import dep
from dev_lab.dev.jsrun import node_path

LAUNCHER = Path(dep.__file__).with_name('agent_launcher.js')

#: Child scripts are one line of `print(..., file=sys.stderr)`: a backslash before a quote is lost in Windows argv.
_USAGE = (
    'import sys;'
    'print("usage: taskbinding [-h] {show}", file=sys.stderr);'
    "print(\"taskbinding: error: argument verb: invalid choice: 'bind' (choose from 'show')\", file=sys.stderr);"
    'sys.exit(2)'
)
_MISSING = 'import dev_lab_no_such_module'
_REFUSAL = (
    'import sys; print("TASK-BOUND: this session is unbound -- door: task: <slug>", file=sys.stderr); sys.exit(2)'
)


@pytest.fixture(scope='module')
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp('project')
    venv.EnvBuilder(with_pip=False).create(root / '.venv')
    return root


def _launch(root: Path, code: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, 'CLAUDE_PROJECT_DIR': str(root)}
    return subprocess.run(
        [str(node_path()), str(LAUNCHER), '-c', code],
        capture_output=True, text=True, encoding='utf-8', env=env, cwd=root, check=False,
    )  # fmt: skip


def test_a_usage_exit_lets_the_prompt_through_in_one_line_naming_the_door(project: Path) -> None:
    done = _launch(project, _USAGE)
    assert done.returncode == 0, done.stderr
    lines = done.stderr.strip().splitlines()
    assert len(lines) == 1, done.stderr
    assert 'bind' in lines[0]
    assert 'dev_lab.dev.dep --bootstrap' in lines[0]


def test_a_missing_module_lets_the_prompt_through_in_one_line(project: Path) -> None:
    done = _launch(project, _MISSING)
    assert done.returncode == 0, done.stderr
    assert done.stderr.strip().splitlines() == [line for line in done.stderr.strip().splitlines() if '[hook]' in line]
    assert 'dev_lab_no_such_module' in done.stderr


def test_a_deliberate_refusal_still_blocks_with_its_own_words(project: Path) -> None:
    """PLANTED CONTROL: exit 2 with a rule and no usage text is a decision, passed through untouched."""
    done = _launch(project, _REFUSAL)
    assert done.returncode == 2
    assert 'TASK-BOUND' in done.stderr
    assert '[hook]' not in done.stderr
