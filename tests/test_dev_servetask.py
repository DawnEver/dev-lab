"""The ONE Windows Scheduled Task that serves every declared repo; never installed by a test."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest
from _arch_corpus import parse, rel, source_modules

from lab_commons.dev import servetask

#: The creation flags that give a child a console of its OWN instead of the inherited windowless one.
_DETACHING = frozenset({'DETACHED_PROCESS', 'CREATE_NEW_CONSOLE'})


def test_the_task_runs_the_windowless_interpreter_from_its_checkout_every_five_minutes(tmp_path: Path) -> None:
    lab = tmp_path / 'lab-commons'
    want = servetask.definition_of(lab, mode='integrate')
    assert want.command == str(lab / '.venv' / 'Scripts' / 'pythonw.exe'), 'pythonw: no console window'
    assert want.arguments == '-m lab_commons.dev.workstation serve --mode integrate'
    assert want.working_directory == str(lab), 'the checkout is the working directory, not a `cmd /c cd`'
    assert (want.logon_type, want.hidden, want.interval) == ('InteractiveToken', 'true', 'PT5M')


def test_the_definition_round_trips_through_the_task_xml(tmp_path: Path) -> None:
    want = servetask.definition_of(tmp_path / 'a&b', mode='develop')
    xml = servetask.task_xml(want, user='DOM\\ada')
    assert '<UserId>DOM\\ada</UserId>' in xml
    assert '<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>' in xml
    assert servetask.installed(xml) == want


def test_an_older_cmd_task_reads_back_as_a_different_definition(tmp_path: Path) -> None:
    old = (
        '<?xml version="1.0" encoding="UTF-16"?><Task><Actions><Exec><Command>cmd</Command>'
        '<Arguments>/c cd /d "C:\\x" &amp;&amp; "py" -m m serve</Arguments></Exec></Actions></Task>'
    )
    assert servetask.installed(old) != servetask.definition_of(tmp_path, mode='integrate')
    assert servetask.installed('') is None
    assert servetask.query_argv() == ['schtasks', '/Query', '/TN', 'lab-forge-serve', '/XML']
    assert servetask.create_argv(tmp_path / 't.xml') == [
        'schtasks', '/Create', '/TN', 'lab-forge-serve', '/XML', str(tmp_path / 't.xml'), '/F',
    ]  # fmt: skip


def test_a_serve_spawn_opens_no_console_window() -> None:
    flags = servetask.windowless()
    assert flags == ({'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {})


def test_the_serve_log_is_size_capped_by_one_rotation(tmp_path: Path) -> None:
    log = tmp_path / 'lab-forge' / 'serve.log'
    with servetask.open_log(log, cap=8) as out:
        out.write('0123456789')
    with servetask.open_log(log, cap=8) as out:
        out.write('new')
    assert log.read_text(encoding='utf-8') == 'new'
    assert log.with_name('serve.log.1').read_text(encoding='utf-8') == '0123456789'


@pytest.mark.parametrize('mode', ['integrate', 'develop'])
def test_the_mode_reaches_the_arguments(tmp_path: Path, mode: str) -> None:
    assert servetask.definition_of(tmp_path, mode=mode).arguments.endswith(f'--mode {mode}')


def _detaches(path: Path) -> bool:
    return any(
        (isinstance(node, ast.Name) and node.id in _DETACHING)
        or (isinstance(node, ast.Attribute) and node.attr in _DETACHING)
        for node in ast.walk(parse(path))
    )


def test_nothing_in_the_kit_leaves_the_windowless_console_its_serve_child_inherits() -> None:
    """One flag at the root hides the whole tree ONLY while no descendant asks for a console of its own."""
    modules = source_modules()
    assert len(modules) > 100, 'an empty scan is not a clean one'
    assert [rel(path) for path in modules if _detaches(path)] == []
