"""``hpcaccount retention``: the caller's rules are streamed to the account before its kit's own retention runs.

A DEADLOCK, measured 2026-11-22: an account too full to update its kit ran the kit's OLD retention, which had no
rule for what filled it. PLANTED CONTROL: a kit that cannot run still got the caller's rules, and is named.
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess

from lab_commons.hpc.grants import Grant

from dev_lab.dev import oldcopies
from dev_lab.dev.hpcaccount import storage
from dev_lab.dev.hpcaccount.fleet import Target
from dev_lab.dev.hpcaccount.storage import retention_fleet
from dev_lab.dev.venvpointer import HOME, POINTER, RETIRED_POINTER

_ALICE = Grant(user='alice', hosts=('login01.example',), slurm_account='acct')
_TARGET = Target('login01.example', '/r/src')
_DEPLOY = '[deploy]\nhost = "login01.example"\nroot = "/r/src"\n'
_FREED = '[retention] deleted old-copy: 1 paths, 0.0 MB, 3 files'


def test_the_callers_rules_are_streamed_first_and_a_kit_that_cannot_run_is_named() -> None:
    sent: list[tuple[str, str | None]] = []

    def shell(cmd: str, stdin: str | None = None) -> str:
        sent.append((cmd, stdin))
        if 'sed -n' in cmd:
            return _DEPLOY
        if 'dev_lab.dev.retention' in cmd:
            msg = 'ModuleNotFoundError: the kit is half-built'
            raise RuntimeError(msg)
        return _FREED if stdin else '2'

    said: list[str] = []
    code = retention_fleet(
        [_ALICE], (), apply=True, say=said.append, connect=lambda _grant: shell, pin=lambda _grant, _host: shell
    )
    streamed = [(cmd, stdin) for cmd, stdin in sent if stdin]
    assert [stdin for _cmd, stdin in streamed] == [storage.SWEEP_SOURCE], 'the source travels on stdin, once'
    (line,) = [cmd for cmd, _stdin in streamed]
    assert line == storage.streamed_rules_command(_TARGET, apply=True)
    assert 'dev_lab' not in line, 'the line imports nothing of the kit'
    assert _FREED in said, "the caller's rules ran"
    assert code == 2
    assert (
        said[-1] == "alice: refused -- the kit's own retention did not run: ModuleNotFoundError: the kit is half-built"
    )


def test_the_streamed_line_falls_back_to_python3_and_carries_the_spec() -> None:
    line = storage.streamed_rules_command(_TARGET, apply=False)
    assert line.startswith('export LAB_ROOT=/r/src; cd /r/src/repos/dev-lab 2>/dev/null; py=')
    assert '|| py=python3;' in line
    assert 'retention: refused -- neither the kit environment nor python3 is a python >= 3.8' in line
    assert json.loads(shlex.split(line)[-1]) == storage.sweep_spec(_TARGET, apply=False)
    bash = shutil.which('bash')
    assert bash, 'the line runs in bash on the account'
    subprocess.run([bash, '-n', '-c', line], check=True)  # the composed line parses


def test_the_streamed_spec_holds_the_declared_names_from_their_one_source() -> None:
    spec = storage.sweep_spec(_TARGET, apply=False)
    assert spec['root'] == '/r/src'
    assert spec['strays_in_home'] == list(oldcopies.STRAYS_IN_HOME)
    assert spec['strays_in_root'] == list(oldcopies.STRAYS_IN_ROOT)
    assert (spec['pointer'], spec['envs'], spec['retired_pointer']) == (POINTER, HOME, RETIRED_POINTER)
    assert spec['apply'] is False
