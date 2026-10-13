"""Every test reserves on a box of its own: the broker's record root is the test's ``tmp_path``.

A test that falls through to the default root shares the HOST's live seats (a sibling's verdict, a
stranger's directory on a cluster node) and its result then depends on who else is on the box. A
test that means the default root says so with ``monkeypatch.delenv``. The machine config is the
test's own for the same reason: a finished run LEARNS beside it (:mod:`lab_commons.compute.learned`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from lab_commons.config import CONFIG_ENV
from lab_commons.resources import RESOURCE_DIR_ENV


@pytest.fixture(autouse=True)
def _a_box_of_its_own(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(RESOURCE_DIR_ENV, str(tmp_path / 'lab-commons-resources'))
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'lab-commons-machine' / 'config.toml'))


#: Git and Git Credential Manager never ask a person: a fake forge host once popped a GCM dialog on a
#: workstation. ``credential.interactive=never`` rides as command-level config, so it survives a test's
#: own ``GIT_CONFIG_GLOBAL``. It rides in ``GIT_CONFIG_PARAMETERS`` (what ``git -c`` itself exports), never
#: the numbered ``GIT_CONFIG_COUNT`` set: a test that plants its own numbered set would otherwise have its
#: ``KEY_0`` completed by ours (``git-env-repair``'s poison arm went quietly harmless).
#: No askpass is set: git consults askpass BEFORE ``GIT_TERMINAL_PROMPT``,
#: and an ``echo`` askpass would ANSWER a prompt with a fake credential instead of refusing it.
NO_PROMPT: Final = {
    'GIT_TERMINAL_PROMPT': '0',
    'GCM_INTERACTIVE': 'never',
    'GIT_CONFIG_PARAMETERS': "'credential.interactive'='never'",
}
ASKPASS: Final = ('GIT_ASKPASS', 'SSH_ASKPASS')


@pytest.fixture(autouse=True)
def _git_never_prompts(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in NO_PROMPT.items():
        monkeypatch.setenv(name, value)
    for name in ASKPASS:
        monkeypatch.delenv(name, raising=False)
