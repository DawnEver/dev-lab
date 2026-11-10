"""The serve's data-PR step: an open PR on a repo this checkout consumes runs this checkout's tests at its head.

WHAT IS SCANNED IS DERIVED. The data repos are the urls of this served checkout's own
``[tool.dev_lab.data.*]`` rows (:func:`dev_lab.dev.datadeps.declared`) -- no second ``[serve] repos`` entry
names them, and a checkout with no data row scans nothing.

THE PLAN IS :func:`dev_lab.dev.dataconsumers.runs`; this step only carries it out, in the consumer's own
checkout with the consumer's own interpreter (:func:`dev_lab.dev.venvpath.checkout_interpreter`, never a bare
``python``): sync the data copy to the PR head under the run's override, run the planned verify, then sync the
copy back to the pin with no override. The tracked tree and the pin are never touched -- the head reaches the
run only through :data:`dev_lab.dev.datadeps.OVERRIDE`.

THE RESULT GOES THROUGH THE OUTBOX (:mod:`dev_lab.dev.forgeoutbox`), like every test part, as a
``tests/consumer:<member>`` status addressed to the DATA repo (:attr:`~dev_lab.dev.forgeoutbox.Post.repo`);
the serve's own flush delivers it. A head whose context the data repo already holds is not run again.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons import launch
from lab_commons.home import repos

from dev_lab.dev import dataconsumers, datadeps
from dev_lab.dev.forge import origin_url
from dev_lab.dev.forgealarm import INTEGRATION, Alarm
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgeoutbox import Post, enqueue, unprompted_client
from dev_lab.dev.forgepulls import ListingIncomplete, pr_list
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.venvpath import checkout_interpreter, current_os_name

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping, Sequence

    from dev_lab.dev._forge_records import PullRequest

__all__ = ['RUN_TIMEOUT_S', 'serve_step', 'step']

_SYNC: Final = ('-m', 'dev_lab.dev.datadeps', 'sync')


def step(
    root: Path,
    member: str,
    *,
    pulls: Callable[[str], Sequence[PullRequest]],
    decided: Callable[[str, str], Collection[str]],
    execute: Callable[[list[str], Path, Mapping[str, str]], int],
    interpreter: Callable[[Path], Path],
    say: Callable[[str], None],
) -> None:
    """Run and queue every consumer run *root* (the family member *member*) owes an open data PR.

    *pulls* lists a data repo's open PRs, *decided* the contexts a commit already holds there, *execute* runs an
    argv in a directory with an environment and returns its exit code -- each a seam a test fakes.
    """
    urls = sorted({dep.url for dep in datadeps.declared(root, overridden=False)})
    for url in urls:
        for pull in pulls(url):
            if not pull.head_sha or pull.draft:
                continue
            held = decided(url, pull.head_sha)
            for run in dataconsumers.runs(url, pull.head_sha, {member: root}):
                if run.context in held:
                    continue
                python = str(interpreter(run.root))
                env = {**os.environ, **run.env}
                execute([python, *_SYNC], run.root, env)
                code = execute([python, *run.argv[1:]], run.root, env)
                restored = {key: value for key, value in os.environ.items() if key != datadeps.OVERRIDE}
                execute([python, *_SYNC], run.root, restored)  # the copy goes back to the pin
                state = 'success' if code == 0 else 'failure'
                enqueue(
                    root, Post(pull.head_sha, run.context, state, f'{member} at #{pull.number}: exit {code}', repo=url)
                )
                say(f'[serve] {run.context} on {url} #{pull.number} {pull.head_sha[:12]}: {state}')


#: The longest one consumer run may take inside a serve tick.
RUN_TIMEOUT_S: Final = 3600


def _member(root: Path) -> str:
    """*root*'s family member name in this machine's ``[repos]``; its directory name when it is not listed."""
    mine = root.resolve()
    return next((name for name, path in repos().items() if Path(path).resolve() == mine), root.name)


def _execute(argv: list[str], cwd: Path, env: Mapping[str, str]) -> int:
    return launch.run(argv, cwd=cwd, env=dict(env), check=False, timeout=RUN_TIMEOUT_S).returncode


def serve_step(root: Path, *, say: Callable[[str], None], alarm: Callable[[Alarm], object]) -> None:
    """:func:`step` with the real forge, the outbox and this checkout's own interpreter; failure-contained."""
    os_name = current_os_name()

    def pulls(url: str) -> Sequence[PullRequest]:
        return pr_list(unprompted_client(root, url=url))

    def decided(url: str, sha: str) -> Collection[str]:
        return {one.context for one in status_list(unprompted_client(root, url=url), sha)}

    try:
        step(
            root, _member(root), pulls=pulls, decided=decided, execute=_execute,
            interpreter=lambda here: checkout_interpreter(here, os_name=os_name), say=say,
        )  # fmt: skip
    except (datadeps.DataRefused, ForgeCallFailed, ListingIncomplete, OSError) as failed:
        alarm(Alarm(INTEGRATION, origin_url(root), 'a data PR could not run its consumer tests', str(failed)))
