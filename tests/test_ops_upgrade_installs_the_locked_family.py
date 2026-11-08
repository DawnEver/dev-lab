"""``ops upgrade`` installs dev-lab WITH the family revisions its own ``uv.lock`` pins at the installed commit.

THE INCIDENT, 2026-11-08: every forge host carried a hand-written ``/opt/dev-lab/overrides.txt`` pinning lab-commons
at 01c8fb8 -- a second source of truth beside dev-lab's lock. The upgraded dev-lab imported ``lab_commons.home``,
which that old lab-commons lacks, so AMD-1's judge died on an ImportError; the same hosts also ran an ai-lab other
than the one the lock pins. The lock is the one source: the upgrade derives the overrides from it, and the
``overrides`` knob is retired (upgraded away on read).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from pathlib import Path

import pytest

from dev_lab.ops import upgrade
from dev_lab.ops.config import OpsConfig, load

LOCK = """\
version = 1

[[package]]
name = "ai-lab"
version = "0.0.1"
source = { git = "https://github.com/DawnEver/ai-lab.git#869350998c64984e356a83acdea5f1f1ff8d6b47" }

[[package]]
name = "dev-lab"
version = "0.0.1"
source = { editable = "." }

[[package]]
name = "lab-commons"
version = "0.3.1"
source = { git = "https://github.com/DawnEver/lab-commons.git?rev=main#bfe89356f44449b3acd5cbcf18accfcdc1cb80cc" }

[[package]]
name = "numpy"
version = "2.3.0"
source = { registry = "https://pypi.org/simple" }
"""

TIP = '49bf43b17c5208cac3adeea9533a80b3058dcf19'
OLD = '6b470cd9206b0a0ef901cf2a2732b4d6ebf7242f'


def _config(tmp: Path, extra: str = '') -> OpsConfig:
    path = tmp / 'supervise.toml'
    path.write_text(
        f'[ops]\nhome = "{(tmp / "home").as_posix()}"\npython = "/opt/dev-lab/.venv/bin/python"\n'
        f'[ops.upgrade]\nsource = "https://github.com/DawnEver/dev-lab.git"\nextras = ["ops"]\n{extra}',
        encoding='utf-8',
    )
    return load(path, environ={})


def test_the_lock_names_every_git_family_package_but_dev_lab_itself() -> None:
    assert upgrade.locked_family(LOCK) == [
        'ai-lab @ git+https://github.com/DawnEver/ai-lab.git@869350998c64984e356a83acdea5f1f1ff8d6b47',
        'lab-commons @ git+https://github.com/DawnEver/lab-commons.git@bfe89356f44449b3acd5cbcf18accfcdc1cb80cc',
    ]


def test_the_upgrade_installs_the_tip_commit_with_its_own_locked_family(tmp_path: Path) -> None:
    host = _config(tmp_path)
    installs: list[list[str]] = []
    overrides: list[str] = []

    def install(argv: Sequence[str]) -> tuple[int, str]:
        line = list(argv)
        installs.append(line)
        overrides.append(Path(line[line.index('--override') + 1]).read_text(encoding='utf-8'))
        return 0, ''

    commits = iter([OLD, TIP])
    code, said = upgrade.run(
        host,
        install=install,
        probe=lambda argv: (0, next(commits)) if '-c' in argv and 'direct_url' in argv[-1] else (0, ''),
        fetch=lambda _source, _ref: (TIP, LOCK),
    )
    assert code == 0, said
    assert installs[0][-1] == f'dev-lab[ops] @ git+https://github.com/DawnEver/dev-lab.git@{TIP}'
    assert 'lab-commons @ git+https://github.com/DawnEver/lab-commons.git@bfe89356' in overrides[0]
    assert 'ai-lab @ git+https://github.com/DawnEver/ai-lab.git@86935099' in overrides[0]


def test_a_rollback_reinstalls_the_old_commit_with_the_old_commits_lock(tmp_path: Path) -> None:
    host = _config(tmp_path)
    installs: list[list[str]] = []
    fetched: list[str] = []

    def fetch(_source: str, ref: str) -> tuple[str, str]:
        fetched.append(ref)
        return (TIP, LOCK) if ref != OLD else (OLD, LOCK.replace('bfe89356', '01c8fb89'))

    commits = iter([OLD, TIP])

    def probe(argv: Sequence[str]) -> tuple[int, str]:
        if '-c' in argv and 'direct_url' in argv[-1]:
            return 0, next(commits, OLD)
        return (1, '') if len(installs) == 1 else (0, '')  # the tip fails its self-check, the rollback passes

    code, said = upgrade.run(
        host, install=lambda argv: (installs.append(list(argv)), (0, ''))[1], probe=probe, fetch=fetch
    )
    assert code == 1
    assert 'restored' in said
    assert fetched == ['integrate/main', OLD]
    assert installs[1][-1].endswith(f'@{OLD}')


def test_a_hand_written_overrides_file_is_retired_on_read(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    host = _config(tmp_path, 'overrides = "/opt/dev-lab/overrides.txt"\n')
    assert host.upgrade is not None
    assert 'overrides' not in {field.name for field in dataclasses.fields(host.upgrade)}
    assert 'overrides' in capsys.readouterr().err


def test_a_judge_host_installs_its_reviewer_at_the_locked_revision(tmp_path: Path) -> None:
    """A judge host installs ai-lab even when its ``[ops.upgrade]`` names no ``packages``.

    AMD-1, 2026-11-08: no package named ai-lab, so the lock's ai-lab override pinned nothing and the judge kept a
    stale reviewer. The judge role implies its reviewer.
    """
    judge = (
        f'[ops.judge]\nuser = "judge"\nschedule = "*:0/5"\nrepos = ["https://github.com/o/r"]\n'
        f'[ops.judge.tokens]\n"github.com" = "{(tmp_path / "tok").as_posix()}"\n'
    )
    line = upgrade.command(_config(tmp_path, judge), TIP, tmp_path / 'family.txt')
    assert 'ai-lab' in line, line


def test_a_host_without_a_judge_installs_no_reviewer(tmp_path: Path) -> None:
    line = upgrade.command(_config(tmp_path), TIP, tmp_path / 'family.txt')
    assert not any(part.startswith('ai-lab') for part in line), line
