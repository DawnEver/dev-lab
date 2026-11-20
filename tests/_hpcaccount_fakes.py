"""Fakes shared by the hpcaccount drift and ci-pause tests: a fake ``crontab`` and ``id``, a home, a config source."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

from lab_commons.hpc.grants import Grant

from dev_lab.dev import devhost
from dev_lab.dev.hpcaccount.fleet import ConfigSource
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

#: The account file name of the fake account: ``<cluster>-<user>``.
HOST: Final = 'c1-alice'
FAMILY: Final = (
    '[[hpc.grant]]\nuser = "alice"\ncluster = "c1"\nslurm_account = "a"\nrole = "verification"\n'
    '[hpc.clusters.c1]\nhosts = ["login01"]\n[hpc.clusters.c1.slurm_accounts.a]\nbilled = false\n'
)
#: The account layer; {root} is the declared root, under the test's own tmp dir (never a real /).
LAYER: Final = (
    '[deploy]\nhost = "login01"\nroot = "{root}"\n'
    'repos = [{{ name = "dev-lab", url = "https://forge.example/dev-lab.git", ref = "trunk" }}]\n'
)


def tools_of(tmp_path: Path, state: str = 'crontab.txt') -> Tools:
    """Fake ``crontab`` (state in *tmp_path*/*state*) and ``id``."""
    script = tmp_path / 'crontab.py'
    script.write_text(FAKE_CRONTAB, encoding='utf-8')
    echo = (sys.executable, '-c', 'print("alice")')
    return Tools(crontab=(sys.executable, str(script), str(tmp_path / state)), id=echo)


def clone_of(tmp_path: Path, family: str = FAMILY) -> Path:
    """A config-source clone declaring the account :data:`HOST` (its grant's role in *family*)."""
    clone = tmp_path / 'config'
    (clone / 'hosts').mkdir(parents=True)
    (clone / 'family.toml').write_text(family, encoding='utf-8')
    root = (tmp_path / 'root').as_posix()
    (clone / devhost.host_file(HOST)).write_text(LAYER.format(root=root), encoding='utf-8')
    return clone


def home_of(tmp_path: Path, extra: str = '', family: str = FAMILY) -> tuple[Path, Path, Path]:
    """A home, the clone, and a machine file that IS the clone's render plus *extra* (the account's own drift)."""
    home = tmp_path / 'home'
    home.mkdir()
    clone = clone_of(tmp_path, family)
    machine = tmp_path / 'machine.toml'
    machine.write_text(devhost.render(clone, HOST, {}) + extra, encoding='utf-8')
    return home, clone, machine


#: A three-account fleet over two clusters; ``rita`` is a research account (no CI cron).
HOSTS = ('login01.example',)
FLEET = (
    Grant(user='alice', hosts=HOSTS, slurm_account='a', cluster_name='c1'),
    Grant(user='bob', hosts=HOSTS, slurm_account='a', cluster_name='c2'),
    Grant(user='rita', hosts=HOSTS, slurm_account='a', cluster_name='c1'),
)
ROLES = {'alice': 'verification', 'bob': 'verification', 'rita': 'research'}


def fleet_source(tmp_path: Path) -> ConfigSource:
    """A config-source clone declaring :data:`FLEET`, each account's layer with its :data:`ROLES` role."""
    clone = tmp_path / 'src'
    (clone / 'hosts').mkdir(parents=True)
    rows = (f'[[hpc.grant]]\nuser = "{g.user}"\ncluster = "{g.cluster_name}"\nslurm_account = "a"\n' for g in FLEET)
    (clone / 'family.toml').write_text(''.join(rows), encoding='utf-8')
    root = (tmp_path / 'root').as_posix()
    for g in FLEET:
        layer = f'[deploy]\nhost = "login01.example"\nroot = "{root}"\nrole = "{ROLES[g.user]}"\n'
        (clone / 'hosts' / f'{g.cluster_name}-{g.user}.toml').write_text(layer, encoding='utf-8')
    return ConfigSource(clone, 'https://forge.example/config.git')
