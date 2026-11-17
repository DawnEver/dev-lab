"""ONE RESOLVER (dev-lab #641): the shipped JS rule, its rendered shell twin and the Python twin give one answer.

PLANTED CONTROLS: the layouts include every way a pointer can fail to name an environment (absent, empty, a path,
a dot name, a name with no directory), so a resolver that always answered ``.venv`` -- or always the pointer --
disagrees; a watch from a superseded environment yields, one from the current one does not.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from dev_lab.dev import agent_guard, venvpointer
from dev_lab.dev.jsrun import node_path

RESOLVER = Path(venvpointer.__file__).with_name('venv_resolver.js')
SH = shutil.which('sh')

#: (pointer content or None for no pointer, environment directories under .venvs/, also a legacy .venv?)
LAYOUTS: tuple[tuple[str | None, tuple[str, ...], bool], ...] = (
    (None, (), False),
    (None, (), True),
    (None, ('a',), True),
    ('a', ('a',), False),
    ('a', ('a',), True),
    ('a\n', ('a', 'b'), True),
    ('b\r\n', ('a', 'b'), True),
    ('  b  \n', ('b',), False),
    ('b\nextra\n', ('b', 'extra'), True),
    ('', ('a',), True),
    ('   \n', ('a',), True),
    ('missing', ('a',), True),
    ('missing', (), False),
    ('.', ('a',), True),
    ('..', ('a',), True),
    ('a/b', ('a',), True),
    ('a\\b', ('a',), True),
    ('c:x', ('x',), True),
    ('env-2026.11.16_1', ('env-2026.11.16_1', 'old'), True),
    ('\nb', ('b',), True),
)


def _layout(root: Path, layout: tuple[str | None, tuple[str, ...], bool]) -> Path:
    pointer, envs, legacy = layout
    root.mkdir(parents=True)
    for name in envs:
        (root / venvpointer.HOME / name).mkdir(parents=True)
    if legacy:
        (root / venvpointer.ALIAS).mkdir()
    if pointer is not None:
        (root / venvpointer.POINTER).write_bytes(pointer.encode('utf-8'))
    return root


def _run(argv: list[str]) -> str:
    done = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8', check=False, timeout=60)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def _same(answer: str, expected: Path) -> bool:
    return Path(answer).resolve() == expected.resolve()


def test_there_are_twenty_distinct_layouts() -> None:
    assert len(set(LAYOUTS)) == 20


def test_the_three_resolvers_agree_on_every_layout(tmp_path: Path) -> None:
    assert SH, 'the shell twin runs in a POSIX sh: every host the kit serves has one'
    named = 0
    for index, layout in enumerate(LAYOUTS):
        root = _layout(tmp_path / f'r{index}', layout)
        expected = venvpointer.current(root)
        named += expected != root / venvpointer.ALIAS
        js = _run([str(node_path()), str(RESOLVER), '--current', str(root)])
        sh = _run([str(SH), '-c', f'{venvpointer.shell_function()}\n_current_env "$1"', 'sh', root.as_posix()])
        assert _same(js, expected), (layout, js, expected)
        assert _same(sh, expected), (layout, sh, expected)
    assert 0 < named < len(LAYOUTS), 'PLANTED CONTROL: the layouts exercise both answers'


def test_the_shell_twin_in_with_venv_is_the_rendering_of_the_js_rule() -> None:
    rendered = _run([str(node_path()), str(RESOLVER), '--shell'])
    assert venvpointer.shell_function() == rendered, 're-render: node venv_resolver.js --shell into with-venv.sh'
    assert '%' not in rendered, 'a crontab line embeds it, and cron reads % as a newline'


def test_every_case_arm_of_the_shell_twin_opens_its_paren() -> None:
    """Every arm is written ``(pattern)``: macOS bash 3.2 ends a ``$(...)`` at an arm's bare ``)``.

    :func:`venvpointer.shell_interpreter` puts the twin INSIDE a command substitution, so a bare arm broke it there.
    """
    body = venvpointer.shell_function()
    arms = body[body.index(' in ') + 4 : body.index('esac')].split(';;')
    assert [arm.strip()[0] for arm in arms if arm.strip()] == ['(', '('], body


def test_no_door_carries_its_own_pointer_reader() -> None:
    dev = RESOLVER.parent
    for door in (dev / 'agent_launcher.js', dev / 'agenthooks' / 'deny-commands.js'):
        text = door.read_text(encoding='utf-8')
        assert 'venv_resolver.js' in text, door
        assert venvpointer.POINTER not in text, f'{door} reads the pointer itself'


def test_the_installer_puts_the_resolver_beside_the_launcher_and_the_engine(tmp_path: Path) -> None:
    agent_guard.install_guard(tmp_path)
    hooks = tmp_path / '.claude' / 'hooks'
    assert (hooks / 'venv_resolver.js').read_bytes() == RESOLVER.read_bytes()


def test_a_watch_yields_only_an_environment_a_newer_one_superseded(tmp_path: Path) -> None:
    root = _layout(tmp_path / 'root', ('new\n', ('old', 'new'), True))
    assert venvpointer.superseded(root / venvpointer.HOME / 'old')
    assert not venvpointer.superseded(root / venvpointer.HOME / 'new'), 'PLANTED CONTROL: the current env stays'
    assert not venvpointer.superseded(root / venvpointer.ALIAS), 'a legacy .venv was never published: it stays'
    assert not venvpointer.superseded(tmp_path / 'python-install'), 'not a checkout env: never yields'
