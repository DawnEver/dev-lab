"""A HOSTED PART'S SETUP: a failure posts the part under its own class, naming the setup's last line (dev-lab#998)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from _forge_state import StateForge

from dev_lab.dev import hostedsetup
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.harness import ActionsRun
from dev_lab.dev.producer import Owner, owner_of

SHA = 'c' * 40
RUN = ActionsRun(server_url='https://github.com', repository='o/r', run_id='7')

PYPROJECT = """
[tool.lab_commons.tests]
resources = ["corpus"]

[tool.dev_lab.parts]
hosted = { corpus = { setup = "fetch-corpus" } }
"""


def _setup_exits(monkeypatch, tmp_path: Path, code: int, output: str) -> tuple[StateForge, list[list[str]]]:
    (tmp_path / 'pyproject.toml').write_text(PYPROJECT, encoding='utf-8')
    ran: list[list[str]] = []

    def run(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        ran.append(list(argv))
        return SimpleNamespace(returncode=code, stdout=output)

    monkeypatch.setattr(hostedsetup._door, 'run', run)
    monkeypatch.setattr(hostedsetup, 'head_sha', lambda _root: SHA)
    return StateForge(), ran


@pytest.mark.parametrize(
    ('code', 'owner'), [(hostedsetup.EX_TEMPFAIL, Owner.NETWORK), (1, Owner.SETUP), (127, Owner.SETUP)]
)
def test_a_failed_setup_posts_its_part_under_its_own_class_naming_its_last_line(
    tmp_path: Path, monkeypatch, code: int, owner: Owner
) -> None:
    """EX_TEMPFAIL (a source did not answer) is ``network``; any other exit ``setup`` -- never a test's red."""
    forge, ran = _setup_exits(monkeypatch, tmp_path, code, 'fetching 11 files\narXiv: 503 Service Unavailable\n\n')
    assert hostedsetup.run_setup(tmp_path, 'corpus', forge, run=RUN) == code
    assert ran == [['bash', '-c', 'fetch-corpus']], 'the declared command, from its one declaration'
    (posted,) = status_list(forge, SHA)
    assert (posted.context, posted.state) == ('tests/corpus', 'error')
    assert owner_of(posted.state, posted.description) is owner
    assert owner_of(posted.state, posted.description) not in {Owner.CODE, Owner.ENVIRONMENT}
    assert f'setup exited {code}' in posted.description
    assert 'arXiv: 503 Service Unavailable' in posted.description, 'its last line names the cause'
    assert posted.url == 'https://github.com/o/r/actions/runs/7', 'the post links the run that failed'


def test_a_setup_that_passes_posts_nothing(tmp_path: Path, monkeypatch) -> None:
    """PLANTED CONTROL: the same setup exiting 0 leaves the part to its producer."""
    forge, _ran = _setup_exits(monkeypatch, tmp_path, 0, 'ok\n')
    assert hostedsetup.run_setup(tmp_path, 'corpus', forge, run=RUN) == 0
    assert not status_list(forge, SHA)


def test_a_part_declaring_no_setup_is_refused_by_name(tmp_path: Path, monkeypatch) -> None:
    forge, ran = _setup_exits(monkeypatch, tmp_path, 0, '')
    with pytest.raises(ValueError, match=r"'linux' declares no setup"):
        hostedsetup.run_setup(tmp_path, 'linux', forge, run=RUN)
    assert ran == []
