"""ONE RESOLVER (dev-lab #641): the shipped JS rule, its rendered shell twin and the Python twin give one answer.

``.venv`` is the pointer (user ruling 2026-11-20): a link to ``.venvs/<name>``, or a plain environment never
published. PLANTED CONTROLS: the layouts include a missing ``.venv``, a dangling link and a plain directory, so a
resolver that always answered the link path -- or always a ``.venvs`` entry -- disagrees; a watch from a superseded
environment yields, one from the current one does not.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from _venv_fake import linked_env

from dev_lab.dev import agent_guard, venvpointer
from dev_lab.dev.jsrun import node_path
from dev_lab.dev.venvpath import VENV_LAYOUTS

RESOLVER = Path(venvpointer.__file__).with_name('venv_resolver.js')
SH = shutil.which('sh')
TAIL = VENV_LAYOUTS[os.name][1:]


def _missing(root: Path) -> None:
    root.mkdir(parents=True)


def _plain(root: Path) -> None:
    (root / venvpointer.POINTER).mkdir(parents=True)


def _linked(root: Path) -> None:
    (root / venvpointer.HOME / 'old').mkdir(parents=True)
    linked_env(root, 'new')


def _dangling(root: Path) -> None:
    env = linked_env(root, 'gone')
    env.rmdir()


#: Each way a checkout can hold its pointer, and the environment the rule answers.
LAYOUTS = {
    'missing': (_missing, lambda root: root / venvpointer.POINTER),
    'plain': (_plain, lambda root: root / venvpointer.POINTER),
    'linked': (_linked, lambda root: root / venvpointer.HOME / 'new'),
    'dangling': (_dangling, lambda root: root / venvpointer.POINTER),
}


def _run(argv: list[str]) -> str:
    done = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8', check=False, timeout=60)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def _same(answer: str, expected: Path) -> bool:
    return os.path.normcase(os.path.realpath(answer)) == os.path.normcase(os.path.realpath(expected))


def _native(answer: str) -> str:
    """A shell answer in this platform's spelling (git bash on Windows prints ``/c/...``)."""
    if os.name == 'nt' and SH and answer.startswith('/'):
        return _run([str(Path(SH).with_name('cygpath')), '-w', answer])
    return answer


def test_the_three_resolvers_agree_on_every_layout(tmp_path: Path) -> None:
    assert SH, 'the shell twin runs in a POSIX sh: every host the kit serves has one'
    for name, (plant, expected_of) in LAYOUTS.items():
        root = tmp_path / name
        plant(root)
        expected = expected_of(root)
        assert _same(str(venvpointer.current(root)), expected), (name, venvpointer.current(root))
        js = _run([str(node_path()), str(RESOLVER), '--current', str(root)])
        sh = _run([str(SH), '-c', f'{venvpointer.shell_function()}\n_current_env "$1"', 'sh', root.as_posix()])
        assert _same(js, expected), (name, js, expected)
        assert _same(_native(sh), expected), (name, sh, expected)
    linked = tmp_path / 'linked'
    assert venvpointer.named(linked) == (linked / venvpointer.HOME / 'new').resolve()
    assert venvpointer.named(tmp_path / 'plain') is None, 'PLANTED CONTROL: a plain .venv is no published env'


def test_the_shell_twin_in_with_venv_is_the_rendering_of_the_js_rule() -> None:
    rendered = _run([str(node_path()), str(RESOLVER), '--shell'])
    assert venvpointer.shell_function() == rendered, 're-render: node venv_resolver.js --shell into with-venv.sh'
    assert '%' not in rendered, 'a crontab line embeds it, and cron reads % as a newline'


def test_no_door_carries_its_own_pointer_reader() -> None:
    dev = RESOLVER.parent
    for door in (dev / 'agent_launcher.js', dev / 'agenthooks' / 'deny-commands.js'):
        text = door.read_text(encoding='utf-8')
        assert 'venv_resolver.js' in text, door
        assert 'realpath' not in text, f'{door} resolves the pointer itself'


def test_the_installer_puts_the_resolver_beside_the_launcher_and_the_engine(tmp_path: Path) -> None:
    agent_guard.install_guard(tmp_path)
    hooks = tmp_path / '.claude' / 'hooks'
    assert (hooks / 'venv_resolver.js').read_bytes() == RESOLVER.read_bytes()


def test_a_watch_yields_only_an_environment_a_newer_one_superseded(tmp_path: Path) -> None:
    root = tmp_path / 'root'
    _linked(root)
    assert venvpointer.superseded(root / venvpointer.HOME / 'old')
    assert not venvpointer.superseded(root / venvpointer.HOME / 'new'), 'PLANTED CONTROL: the current env stays'
    assert not venvpointer.superseded(root / venvpointer.POINTER), '.venv itself is the current env'
    assert not venvpointer.superseded(tmp_path / 'python-install'), 'not a checkout env: never yields'


def test_a_plain_venv_is_current_until_a_publish(tmp_path: Path) -> None:
    root = tmp_path / 'plain'
    _plain(root)
    assert not venvpointer.superseded(root / venvpointer.POINTER), 'PLANTED CONTROL: never published, it is current'


def _interpreter(env: Path) -> Path:
    python = env.joinpath(*TAIL)
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text('', encoding='utf-8')
    return python


def test_a_launch_from_an_older_environment_takes_the_current_one(tmp_path: Path) -> None:
    """The doors that start a child (a detached follow or reclaim, a bootstrap) re-resolve their own interpreter."""
    root = tmp_path / 'root'
    old = _interpreter(root / venvpointer.HOME / 'old')
    new = _interpreter(linked_env(root, 'x'))
    assert Path(venvpointer.current_interpreter(old)).resolve() == new.resolve()
    assert Path(venvpointer.current_interpreter(new)).resolve() == new.resolve()
    through = root / venvpointer.POINTER / Path(*TAIL)
    assert Path(venvpointer.current_interpreter(through)).resolve() == new.resolve(), 'through the link: current'
    bare = tmp_path / 'bare'
    held = _interpreter(bare / venvpointer.HOME / 'old')
    assert venvpointer.current_interpreter(held) == str(held), 'PLANTED CONTROL: no .venv: unchanged'
    outside = _interpreter(tmp_path / 'python-install')
    assert venvpointer.current_interpreter(outside) == str(outside), 'not a checkout env: unchanged'
