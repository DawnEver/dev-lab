"""``Rounds.card`` -- the host card's ``running`` list names only the runs the run store still holds.

MEASURED 2026-11-22: the queue showed ``running <sha> base`` for four runs while the same tick had alarmed each
as settled ("no job of this part was ever submitted; superseded by ..."). The card listed the runs the tick
STARTED with; a run settled while the tick advanced it had its file dropped and was published as running anyway.
PLANTED CONTROL: beside the settled run, one still in flight stays listed.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from lab_commons.config import CONFIG_ENV

from dev_lab.dev import forgerounds, forgerunstate

REPO = 'https://f/o/r.git'
SETTLED, FLYING = 'a' * 40, 'b' * 40


def _run(sha: str) -> forgerunstate.Run:
    run = forgerunstate.Run(REPO, sha, 'pr/example', 'tests', 'out', 'owner', phase=forgerunstate.SUBMITTED)
    forgerunstate.save(run)
    return run


def _rounds(tmp_path: Path, runs: list[forgerunstate.Run]) -> forgerounds.Rounds:
    built = forgerounds.Rounds(
        tmp_path, REPO, lambda _alarm: None, runs, slurm=None, say=lambda _line: None,
        sized=lambda _needs: pytest.fail('no round runs here'), supplied=lambda _held: pytest.fail('no round'),
        holding=lambda: (), ticking={}, carding={}, produce=lambda *_a, **_k: pytest.fail('nothing is produced'),
    )  # fmt: skip
    built.latest.update(ticked=SimpleNamespace(queue=(), artefacts=''), supply=None, held=(), box=None)
    return built


def test_a_run_settled_as_superseded_leaves_the_published_running_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))
    published: list[dict[str, Any]] = []
    monkeypatch.setattr(forgerounds, 'publish_card', lambda *_a, **kwargs: published.append(kwargs))
    settled, flying = _run(SETTLED), _run(FLYING)
    rounds = _rounds(tmp_path, [settled, flying])
    rounds.card(())
    assert published[-1]['running'] == (f'{SETTLED[:12]} base', f'{FLYING[:12]} base'), 'both are in flight'
    forgerunstate.drop(settled)  # what settling does: released with its reason on record, its file dropped
    assert not forgerunstate.held(settled)
    assert forgerunstate.held(flying)
    rounds.card(())
    assert published[-1]['running'] == (f'{FLYING[:12]} base',), 'a settled run is not running'
