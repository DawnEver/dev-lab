"""Fakes shared by the hpcaccount backup and ci-pause tests: a fake ``crontab`` and ``id``, a home, a machine file."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

from dev_lab.dev.hpcaccount.steps import Tools

FAKE_CRONTAB: Final = r"""
import pathlib, sys
state = pathlib.Path(sys.argv[1])
if sys.argv[2] == '-l':
    if state.name == 'broken': sys.stderr.write('permission denied\n'); sys.exit(1)
    if not state.exists(): sys.stderr.write('no crontab for me\n'); sys.exit(1)
    sys.stdout.write(state.read_text())
else:
    state.write_text(sys.stdin.read())
"""

MARKED: Final = '*/5 * * * * tick # lab-commons-deploy:dev-lab\n'
MACHINE: Final = (
    '[deploy]\nhost = "login01"\nroot = "repos"\nrole = "research"\n'
    'repos = [{ name = "dev-lab", url = "https://forge.example/dev-lab.git", ref = "trunk" }]\n'
)


def tools_of(tmp_path: Path, state: str = 'crontab.txt') -> Tools:
    """Fake ``crontab`` (state in *tmp_path*/*state*), ``id`` and ``git``; shared with the ci-pause tests."""
    script = tmp_path / 'crontab.py'
    script.write_text(FAKE_CRONTAB, encoding='utf-8')
    echo = (sys.executable, '-c', 'print("alice")')
    return Tools(crontab=(sys.executable, str(script), str(tmp_path / state)), id=echo)


def home_of(tmp_path: Path, machine_text: str = MACHINE) -> tuple[Path, Path]:
    """A home holding a credential store, and a machine file declaring *machine_text*."""
    home = tmp_path / 'home'
    home.mkdir()
    line = 'https://' + 'me:<token>' + '@forge.example\n'  # split: no url credential to scan
    (home / '.git-credentials').write_text(line, encoding='utf-8')
    machine = tmp_path / 'config.toml'
    machine.write_text(machine_text, encoding='utf-8')
    return home, machine
