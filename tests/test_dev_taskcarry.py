"""A TASK LEDGER CROSSES HOSTS THROUGH THE FORGE (hosts-config #78 item 0), never through a code branch.

``.claude/tasks`` is untracked by design (D80): the ledger of task ``<slug>`` travels as its own ref
``refs/tasks/<slug>`` on origin, a commit of the task directory alone, so no branch ever carries it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev import taskcarry

_GIT = shutil.which('git') or 'git'


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        [_GIT, '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
        cwd=cwd, check=True, capture_output=True, text=True, encoding='utf-8',
    ).stdout.strip()  # fmt: skip


def _hosts(tmp_path: Path) -> tuple[Path, Path, Path]:
    forge = tmp_path / 'forge.git'
    _git(tmp_path, 'init', '-q', '--bare', str(forge))
    hosts = []
    for name in ('a', 'b'):
        _git(tmp_path, 'clone', '-q', str(forge), name)
        _git(tmp_path / name, 'commit', '-q', '--allow-empty', '-m', 'seed')
        hosts.append(tmp_path / name)
    return forge, hosts[0], hosts[1]


def _ledger(host: Path, slug: str = 'toolchain') -> Path:
    return host / '.claude' / 'tasks' / slug


def _write(host: Path, journal: str) -> None:
    task = _ledger(host)
    (task / 'journal').mkdir(parents=True, exist_ok=True)
    (task / 'TASK.md').write_text('---\nauthority: a1\nstatus: open\n---\n', encoding='utf-8')
    (task / 'journal' / '2026-11-20.md').write_text(journal, encoding='utf-8')


def test_a_carried_ledger_arrives_whole_on_another_host_and_no_branch_holds_it(tmp_path: Path) -> None:
    forge, a, b = _hosts(tmp_path)
    _write(a, 'first\n')
    taskcarry.carry(a, 'toolchain')
    taskcarry.receive(b, 'toolchain')
    assert (_ledger(b) / 'journal' / '2026-11-20.md').read_text(encoding='utf-8') == 'first\n'
    assert (_ledger(b) / 'TASK.md').is_file()
    assert _git(forge, 'for-each-ref', '--format=%(refname)') == 'refs/tasks/toolchain'
    assert _git(a, 'status', '--porcelain') == '?? .claude/', 'the code index is never touched'


def test_a_second_carry_moves_the_ref_forward_and_replace_takes_it(tmp_path: Path) -> None:
    forge, a, b = _hosts(tmp_path)
    _write(a, 'first\n')
    taskcarry.carry(a, 'toolchain')
    taskcarry.receive(b, 'toolchain')
    _write(a, 'second\n')
    (_ledger(b) / 'stale.md').write_text('x', encoding='utf-8')
    taskcarry.carry(a, 'toolchain')
    assert _git(forge, 'rev-list', '--count', 'refs/tasks/toolchain') == '2', 'history kept, parent chained'
    taskcarry.receive(b, 'toolchain', replace=True)
    assert (_ledger(b) / 'journal' / '2026-11-20.md').read_text(encoding='utf-8') == 'second\n'
    assert not (_ledger(b) / 'stale.md').exists(), 'replace is the ledger as carried, nothing local survives'


def test_receive_refuses_to_overwrite_a_local_ledger_and_names_its_door(tmp_path: Path) -> None:
    _, a, b = _hosts(tmp_path)
    _write(a, 'from a\n')
    taskcarry.carry(a, 'toolchain')
    _write(b, 'local work\n')
    with pytest.raises(taskcarry.CarryRefused, match=r'--replace'):
        taskcarry.receive(b, 'toolchain')
    assert (_ledger(b) / 'journal' / '2026-11-20.md').read_text(encoding='utf-8') == 'local work\n'


def test_the_refusals_name_their_cause_and_door(tmp_path: Path) -> None:
    _, a, b = _hosts(tmp_path)
    with pytest.raises(taskcarry.CarryRefused, match=r'no task toolchain in the ledger.*task-open'):
        taskcarry.carry(a, 'toolchain')
    with pytest.raises(taskcarry.CarryRefused, match=r'origin holds no refs/tasks/toolchain.*carry toolchain'):
        taskcarry.receive(b, 'toolchain')
    with pytest.raises(taskcarry.CarryRefused, match=r'not a task slug'):
        taskcarry.carry(a, '../x')
