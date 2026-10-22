"""The ONE Windows Scheduled Task that serves every declared repo; never installed by a test."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from _arch_corpus import assert_floor, parse, rel, source_modules

from lab_commons import launch
from dev_lab.dev import servetask, workstation

#: The creation flags that give a child a console of its OWN instead of the inherited windowless one.
_DETACHING = frozenset({'DETACHED_PROCESS', 'CREATE_NEW_CONSOLE'})

#: The kit's source-module floor for the console scan; the bound the inline check held before.
SOURCE_FLOOR = 100


def test_the_task_runs_the_windowless_interpreter_from_its_checkout_every_five_minutes(tmp_path: Path) -> None:
    lab = tmp_path / 'lab-commons'
    want = servetask.definition_of(lab)
    assert want.command == str(lab / '.venv' / 'Scripts' / 'pythonw.exe'), 'pythonw: no console window'
    assert want.arguments == '-m dev_lab.dev.workstation serve'
    assert want.working_directory == str(lab), 'the checkout is the working directory, not a `cmd /c cd`'
    assert (want.logon_type, want.hidden, want.interval) == ('InteractiveToken', 'true', 'PT5M')


def test_the_definition_round_trips_through_the_task_xml(tmp_path: Path) -> None:
    want = servetask.definition_of(tmp_path / 'a&b')
    xml = servetask.task_xml(want, user='DOM\\ada')
    assert '<UserId>DOM\\ada</UserId>' in xml
    assert '<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>' in xml
    assert servetask.installed(xml) == want


def test_an_older_cmd_task_reads_back_as_a_different_definition(tmp_path: Path) -> None:
    old = (
        '<?xml version="1.0" encoding="UTF-16"?><Task><Actions><Exec><Command>cmd</Command>'
        '<Arguments>/c cd /d "C:\\x" &amp;&amp; "py" -m m serve</Arguments></Exec></Actions></Task>'
    )
    assert servetask.installed(old) != servetask.definition_of(tmp_path)
    assert servetask.installed('') is None
    assert servetask.query_argv() == ['schtasks', '/Query', '/TN', 'lab-forge-serve', '/XML']
    assert servetask.create_argv(tmp_path / 't.xml') == [
        'schtasks', '/Create', '/TN', 'lab-forge-serve', '/XML', str(tmp_path / 't.xml'), '/F',
    ]  # fmt: skip


def test_a_serve_spawn_starts_through_the_windowless_door() -> None:
    assert inspect.signature(workstation.serve).parameters['run'].default is launch.run


def test_the_serve_log_is_size_capped_by_one_rotation(tmp_path: Path) -> None:
    log = tmp_path / 'lab-forge' / 'serve.log'
    with servetask.open_log(log, cap=8) as out:
        out.write('0123456789')
    with servetask.open_log(log, cap=8) as out:
        out.write('new')
    assert log.read_text(encoding='utf-8') == 'new'
    assert log.with_name('serve.log.1').read_text(encoding='utf-8') == '0123456789'


def _detaches(path: Path) -> bool:
    return any(
        (isinstance(node, ast.Name) and node.id in _DETACHING)
        or (isinstance(node, ast.Attribute) and node.attr in _DETACHING)
        for node in ast.walk(parse(path))
    )


def test_nothing_in_the_kit_leaves_the_windowless_console_its_serve_child_inherits() -> None:
    """One flag at the root hides the whole tree ONLY while no descendant asks for a console of its own."""
    modules = source_modules()
    assert_floor(len(modules), SOURCE_FLOOR, 'kit source')
    assert [rel(path) for path in modules if _detaches(path)] == []


def test_a_planted_console_detaching_spawn_is_found(tmp_path: Path) -> None:
    """THE PLANTED CONTROL: the real `_detaches` finds each detaching flag and passes a clean module."""
    for flag in sorted(_DETACHING):
        planted = tmp_path / f'planted_{flag.lower()}.py'
        planted.write_text(
            f'import subprocess\nsubprocess.Popen([], creationflags=subprocess.{flag})\n', encoding='utf-8'
        )
        assert _detaches(planted)
    clean = tmp_path / 'clean.py'
    clean.write_text('import subprocess\nsubprocess.Popen([])\n', encoding='utf-8')
    assert not _detaches(clean)
