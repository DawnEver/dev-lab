"""A repo declares its hook adoption as DATA: ``[tool.dev_lab.hook_adoption]`` in pyproject, no adoption module.

2026-11-26 (a consumer with no ``scripts/`` tree): the only way to adopt the deny registry was a ``.py`` module
named by ``[tool.dev_lab.render] adoption``, so a repo carrying no adoption code skipped hook_adoption and
agent_guard both. The table carries the same three facts as :class:`dev_lab.dev.hook_adoption.HookAdoption`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev import agent_wiring, hook_adoption
from dev_lab.dev.famfiles import RENDERERS, render_argv, render_repo
from dev_lab.dev.hook_adoption import HookAdoption, adoption_from_table, render
from dev_lab.dev.hooks import Remedy, UnremediedRule
from dev_lab.dev.venvpath import current_os_name, venv_interpreter

_TABLE = """\
[project]
name = "planted-consumer"

[tool.dev_lab.hook_adoption]
declared_absent = ["NETWORK-VERB", "RAW-PROCESS-KILL"]

[tool.dev_lab.hook_adoption.remedies.BARE-TEST-INVOCATION]
kind = "verdict-entry-point"
command = "{python} -m dev_lab.dev.verify"

[tool.dev_lab.hook_adoption.remedies.PUSH-NO-VERIFY]
kind = "verdict-entry-point"
command = "{python} -m dev_lab.dev.verify"
"""


def _expected() -> HookAdoption:
    verify = Remedy('verdict-entry-point', f'{venv_interpreter(os_name=current_os_name())} -m dev_lab.dev.verify')
    return HookAdoption(
        app_name='planted-consumer',
        remedies={'BARE-TEST-INVOCATION': verify, 'PUSH-NO-VERIFY': verify},
        declared_absent=frozenset({'NETWORK-VERB', 'RAW-PROCESS-KILL'}),
    )


def test_the_rules_file_renders_from_the_pyproject_table(tmp_path: Path) -> None:
    """No ``--adoption``: the renderer reads the table, ``{python}`` resolved to this box's venv interpreter.

    PLANTED CONTROL: before the render the file is absent, so a pass is the write and not a reader of nothing.
    """
    (tmp_path / 'pyproject.toml').write_text(_TABLE, encoding='utf-8')
    assert not (tmp_path / agent_wiring.RULES_REL).exists()
    assert hook_adoption.main(['--repo', str(tmp_path)]) == 0
    assert (tmp_path / agent_wiring.RULES_REL).read_text(encoding='utf-8') == render(_expected())


def test_a_repo_declaring_neither_door_is_refused_naming_both(tmp_path: Path) -> None:
    """PLANTED CONTROL for the above: the same repo minus the table renders nothing and names both doors."""
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "x"\n', encoding='utf-8')
    with pytest.raises(SystemExit, match=r'\[tool\.dev_lab\.hook_adoption\].*--adoption'):
        hook_adoption.main(['--repo', str(tmp_path)])
    assert not (tmp_path / agent_wiring.RULES_REL).exists()


@pytest.mark.parametrize(
    ('table', 'refusal'),
    [
        ({'declared_absent': ['X'], 'remedy': {}}, r"unknown keys \['remedy'\]"),
        ({'remedies': {'BARE-TEST-INVOCATION': {'kind': 'k', 'command': 'c', 'cmd': 'c'}}}, r"unknown keys \['cmd'\]"),
        ({'declared_absent': 'NETWORK-VERB'}, 'declared_absent is a list'),
        ({'remedies': {'BARE-TEST-INVOCATION': 'python -m x'}}, 'is a table'),
    ],
)
def test_a_misspelled_table_is_refused_by_key(table: dict[str, object], refusal: str) -> None:
    """A typo in data ships nothing and reports nothing -- the case the module path refuses at construction."""
    with pytest.raises(ValueError, match=refusal):
        adoption_from_table(table, app_name='planted')


def test_the_data_adoption_meets_the_same_registry_checks() -> None:
    """A rule ID the registry does not define is refused exactly as a module's would be."""
    adoption = adoption_from_table({'declared_absent': ['NO-SUCH-RULE']}, app_name='planted')
    with pytest.raises(UnremediedRule, match='NO-SUCH-RULE'):
        render(adoption)


def test_the_one_door_renders_hook_adoption_from_the_table_alone(tmp_path: Path) -> None:
    """famfiles: the table makes hook_adoption -- and the guard it gates -- due with no ``adoption`` input.

    PLANTED CONTROL: without the table both skip, naming the two ways to declare it.
    """
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.render]\ndeltas = "d.py"\n', encoding='utf-8')
    lines = render_repo(tmp_path, 'py', lambda _argv, _root: 0)
    why = 'hook_adoption: skipped -- [tool.dev_lab.render] adoption is not declared, nor [tool.dev_lab.hook_adoption]'
    assert why in lines
    (tmp_path / 'pyproject.toml').write_text(_TABLE, encoding='utf-8')
    ran: list[list[str]] = []
    lines = render_repo(tmp_path, 'py', lambda argv, _root: ran.append(argv) or 0)
    assert {'agent_guard: rendered', 'hook_adoption: rendered'} <= set(lines)
    named = {renderer.name: renderer for renderer in RENDERERS}
    assert render_argv(named['hook_adoption'], tmp_path, 'py') == [
        'py', '-m', 'dev_lab.dev.hook_adoption', '--repo', str(tmp_path),
    ]  # fmt: skip
    assert render_argv(named['hook_adoption'], tmp_path, 'py') in ran


def test_the_table_and_a_module_together_are_refused(tmp_path: Path) -> None:
    """Two declarations of one adoption is two sources of one fact: the render refuses rather than picks one.

    PLANTED CONTROL: the table alone renders (above).
    """
    (tmp_path / 'pyproject.toml').write_text(_TABLE, encoding='utf-8')
    with pytest.raises(SystemExit, match='both'):
        hook_adoption.main(['--repo', str(tmp_path), '--adoption', 'a.py'])
    assert not (tmp_path / agent_wiring.RULES_REL).exists()
