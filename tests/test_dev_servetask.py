"""The ONE Windows Scheduled Task that serves every declared repo; never installed by a test."""

from __future__ import annotations

from pathlib import Path

from lab_commons.dev import servetask
from lab_commons.dev.venvpath import venv_interpreter


def test_the_task_serves_every_repo_every_five_minutes_as_this_user_only_when_logged_on(tmp_path: Path) -> None:
    lab = tmp_path / 'lab-commons'
    argv = servetask.create_argv(lab, user='DOM\\ada', mode='integrate')
    assert argv[:4] == ['schtasks', '/Create', '/TN', 'lab-forge-serve']
    assert argv[argv.index('/SC') + 1 : argv.index('/SC') + 4] == ['MINUTE', '/MO', '5']
    assert argv[argv.index('/RU') + 1] == 'DOM\\ada'
    assert '/IT' in argv  # only when the user is logged on
    assert '/RP' not in argv  # no stored password
    action = argv[argv.index('/TR') + 1]
    assert action == servetask.action_of(lab)
    assert f'cd /d "{lab}"' in action
    python = venv_interpreter(os_name='nt')
    assert action.endswith(f'&& "{python}" -m lab_commons.dev.workstation serve --mode integrate')


def test_the_installed_action_is_read_back_from_the_query_xml() -> None:
    xml = (
        '<?xml version="1.0" encoding="UTF-16"?><Task><Actions><Exec><Command>cmd</Command>'
        '<Arguments>/c cd /d "C:\\x" &amp;&amp; "py" -m m serve</Arguments></Exec></Actions></Task>'
    )
    assert servetask.installed_action(xml) == 'cmd /c cd /d "C:\\x" && "py" -m m serve'
    assert servetask.installed_action('') == ''
    assert servetask.query_argv() == ['schtasks', '/Query', '/TN', 'lab-forge-serve', '/XML']
