"""Every test reserves on a box of its own: the box ledger file is under the test's ``tmp_path``.

A test that falls through to the default root shares the HOST's live seats (a sibling's verdict, a
stranger's directory on a cluster node) and its result then depends on who else is on the box. A
test that means the default root says so with ``monkeypatch.delenv``. The machine config is the
test's own for the same reason: a finished run LEARNS beside it (:mod:`lab_commons.compute.learned`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
from lab_commons.box import BOX_ENV, CPU_ENV, INSIDE_ENV
from lab_commons.config import CONFIG_ENV

from dev_lab.dev import _dep_project, metrics
from dev_lab.dev.lockcheck import UV_VERSION


@pytest.fixture(autouse=True)
def _a_box_of_its_own(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BOX_ENV, str(tmp_path / 'lab-commons-box' / 'box.sqlite'))
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'lab-commons-machine' / 'config.toml'))
    monkeypatch.delenv(INSIDE_ENV, raising=False)  # the verify running these tests is boxed; a test is not
    monkeypatch.delenv(CPU_ENV, raising=False)


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


#: The checkout this repository's live metrics log lives in, resolved once per session.
_LIVE_CHECKOUT: list[Path] = []


@pytest.fixture(autouse=True)
def _a_metrics_log_of_its_own(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A test never appends to the LIVE metrics log: a root resolving to this repository's checkout is its own.

    The writers take their root explicitly and most tests hand them a tmp tree; this catches the rest (a
    ``Path.cwd()`` at a CLI entry, a hook run against this checkout). Planted control: test_dev_metrics.
    """
    resolve = metrics.checkout
    if not _LIVE_CHECKOUT:
        _LIVE_CHECKOUT.append(resolve(Path(__file__).resolve().parent))
    own = tmp_path / 'metrics-checkout'
    monkeypatch.setattr(metrics, 'checkout', lambda root: own if (at := resolve(root)) == _LIVE_CHECKOUT[0] else at)


@pytest.fixture(autouse=True)
def _the_declared_uv(monkeypatch: pytest.MonkeyPatch) -> None:
    """The host's uv is never what a test measures: every lock-writing door sees the declared one.

    A test that means another uv says so itself. Planted control: test_one_uv_writes_every_lock.
    """
    monkeypatch.setattr(_dep_project, 'installed_uv_version', lambda _uv: UV_VERSION)
