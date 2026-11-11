"""A host runs a forge's Actions runner from its config: ``[ops.runner.<name>]`` renders it and its steps."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.ops import config, forgerunner, install, secretplace

BASE = """
[ops]
home = "/srv/forge"
python = "/opt/dev-lab/.venv/bin/python"
repos = []
"""

RUNNER = """
[ops.runner.light]
instance = "https://forge.example.org"
labels = ["light:host"]
capacity = 2
memory_max = "300M"
slice = "ci-runners.slice"
token_file = "/etc/dev-lab/runner-light/registration-token"
"""


def _host(tmp_path: Path, text: str = BASE + RUNNER) -> config.OpsConfig:
    path = tmp_path / 'supervise.toml'
    path.write_text(text, encoding='utf-8')
    return config.load(path, structure_only=True)


def test_a_declared_runner_renders_its_unit_and_its_config(tmp_path: Path) -> None:
    host = _host(tmp_path)
    (runner,) = host.runners
    assert (runner.name, runner.capacity, runner.labels) == ('light', 2, ('light:host',))
    rendered = forgerunner.files(host)
    unit = rendered['etc/systemd/system/dev-lab-runner-light.service']
    assert 'Slice=ci-runners.slice' in unit
    assert 'MemoryMax=300M' in unit
    assert 'User=runner-light' in unit
    assert 'daemon --config /etc/dev-lab/runner-light/config.yaml' in unit
    yaml = rendered['etc/dev-lab/runner-light/config.yaml']
    assert 'capacity: 2' in yaml
    assert '- light:host' in yaml
    assert 'file: /var/lib/runner-light/.runner' in yaml


def test_install_renders_the_runner_and_names_its_registration(tmp_path: Path) -> None:
    host = _host(tmp_path)
    assert 'etc/systemd/system/dev-lab-runner-light.service' in install.files(host)
    steps = forgerunner.steps(host)
    assert any(step.startswith('id runner-light ||') for step in steps)
    register = next(step for step in steps if ' register ' in step)
    assert '--instance https://forge.example.org' in register
    assert '/etc/dev-lab/runner-light/registration-token' in register  # read from the declared file, never typed
    assert steps[-1] == 'systemctl enable --now dev-lab-runner-light.service'


def test_the_registration_token_is_a_declared_secret_of_root(tmp_path: Path) -> None:
    owners = secretplace.declared(_host(tmp_path))
    assert owners['/etc/dev-lab/runner-light/registration-token'] == 'root'


def test_no_runner_renders_nothing(tmp_path: Path) -> None:
    """The planted control: a host that declares no runner gets no runner unit."""
    host = _host(tmp_path, BASE)
    assert host.runners == ()
    assert forgerunner.files(host) == {}
    assert forgerunner.steps(host) == []


@pytest.mark.parametrize(
    ('row', 'match'),
    [
        ('capacity = 0', 'capacity'),
        ('labels = []', 'labels'),
        ('colour = "red"', 'unknown keys'),
    ],
)
def test_a_bad_runner_is_refused_at_load(tmp_path: Path, row: str, match: str) -> None:
    text = BASE + RUNNER.replace('capacity = 2', row) if row.startswith('capacity') else BASE + RUNNER
    if row.startswith('labels'):
        text = BASE + RUNNER.replace('labels = ["light:host"]', row)
    elif not row.startswith('capacity'):
        text = BASE + RUNNER + row + '\n'
    with pytest.raises(ValueError, match=match):
        _host(tmp_path, text)
