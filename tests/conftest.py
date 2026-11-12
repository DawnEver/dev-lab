"""Every test reserves on a box of its own: the box ledger file is under the test's ``tmp_path``.

A test that falls through to the default root shares the HOST's live seats (a sibling's verdict, a
stranger's directory on a cluster node) and its result then depends on who else is on the box. A
test that means the default root says so with ``monkeypatch.delenv``. The machine config is the
test's own for the same reason, and so is the machine home: a finished run LEARNS into its ``state``
(:mod:`lab_commons.compute.learned`).
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import pytest
from lab_commons.box import BOX_ENV, CPU_ENV, INSIDE_ENV
from lab_commons.config import CONFIG_ENV
from lab_commons.home import HOME_ENV

from dev_lab.dev import _dep_project, forgeserve, metrics, reviewruntime, uvfollow
from dev_lab.dev.lockcheck import uv_version
from dev_lab.dev.netverb import Attempt, Diagnosis, Report
from dev_lab.dev.reviewgitauth import FORGE_TOKEN_ENVS


@pytest.fixture(autouse=True)
def _a_box_of_its_own(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BOX_ENV, str(tmp_path / 'lab-commons-box' / 'box.sqlite'))
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'lab-commons-machine' / 'config.toml'))
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'lab-commons-home'))
    monkeypatch.delenv(INSIDE_ENV, raising=False)  # the verify running these tests is boxed; a test is not
    monkeypatch.delenv(CPU_ENV, raising=False)
    monkeypatch.delenv('CLAUDE_CODE_SESSION_ID', raising=False)  # a test plants the session it means


#: What a CI job's environment carries that no test may inherit: the run id (every simulated review host would
#: share one run, and a claim naming the reader's own run reads as a killed re-run's), the forge tokens (the
#: review door refuses them in its environment) and the workflow's ``GIT_CONFIG_COUNT``/``KEY_n``/``VALUE_n``
#: auth header. A test that means one plants it with ``monkeypatch.setenv``.
_CI_JOB_ENV: Final = re.compile(r'GITHUB_RUN_ID|GIT_CONFIG_(COUNT|KEY_\d+|VALUE_\d+)|' + '|'.join(FORGE_TOKEN_ENVS))


@pytest.fixture(autouse=True)
def _not_inside_a_ci_job(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [k for k in os.environ if _CI_JOB_ENV.fullmatch(k)]:
        monkeypatch.delenv(name)


@pytest.fixture(autouse=True)
def _a_serve_tick_measures_no_real_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``forge serve`` test never reads THIS host's pressure: a workstation's reading averages psutil over seconds.

    The call from serve is pinned in test_dev_forgeserve (which re-stubs it with a recorder); the step itself, on
    fixtures, in test_dev_hostalarm.
    """
    monkeypatch.setattr(forgeserve, 'pressed', lambda *_a, **_k: None)


@pytest.fixture(autouse=True)
def locked_ai_lab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A review test never builds THIS host's locked ai-lab: :func:`reviewruntime.review_runtimes` gets a stub.

    The kit pins ai-lab ``ab12...`` from ``https://forge/o/dev-lab.git``; the runtime is a planted interpreter path.
    test_dev_reviewruntime drives the real :func:`~reviewruntime.kit` and :func:`~reviewruntime.ensure` by seam.
    """
    python = tmp_path / 'locked-ai-lab' / 'python'
    lock = '[[package]]\nname = "ai-lab"\nsource = { git = "https://forge/o/ai-lab.git#ab12cd34ef56ab12" }\n'
    monkeypatch.setattr(reviewruntime, 'kit', lambda _home: (lock, 'https://forge/o/dev-lab.git'))
    monkeypatch.setattr(reviewruntime, 'ensure', lambda *_a: python)
    return python


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


#: Every commit a test makes has an author: a CI runner has no global ``user.name``/``user.email``, and a
#: ``commit``/``commit-tree`` there exits 128. The environment outranks any config, so a test is never
#: carried by the host's own identity either. A test that means another identity sets its own.
IDENTITY: Final = {
    f'GIT_{role}_{what}': value
    for role in ('AUTHOR', 'COMMITTER')
    for what, value in (('NAME', 'test'), ('EMAIL', 'test@example.invalid'))
}


@pytest.fixture(autouse=True)
def _a_git_identity_of_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in IDENTITY.items():
        monkeypatch.setenv(name, value)


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
    monkeypatch.setattr(_dep_project, 'installed_uv_version', lambda _uv: uv_version())
    monkeypatch.setattr(uvfollow, 'run_network_verb', _no_installer)


def _no_installer(argv: Sequence[str], **_kwargs: object) -> Report:
    """No test reaches an installer or the network: the uv update fails, so a stale uv stays stale and is refused."""
    said = 'no installer runs in a test; inject `run` into dev_lab.dev.uvfollow.follow'
    return Report(argv=tuple(argv), attempts=(Attempt(1, 1, said, Diagnosis.UNCLASSIFIED),), allowed_attempts=1)
