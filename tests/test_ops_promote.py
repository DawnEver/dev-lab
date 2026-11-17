"""The promote role judges origin's integration tip by ``integrate promote`` and pushes only what it admits."""

from __future__ import annotations

from pathlib import Path

from _ops_fixtures import config, git, origin

from dev_lab.ops import hostverbs
from dev_lab.ops.promote import Outcome, run


def _admit(argv: list[str], root: Path) -> tuple[int, tuple[str, ...]]:
    assert argv[:2] == ['promote', '--newest'], 'W5: the host promotes the newest first parent that passes'
    git(root, 'update-ref', 'refs/heads/main', argv[-1])
    return 0, ()


def _origin_main(tmp_path: Path) -> str:
    return git(tmp_path / 'forge' / 'owner' / 'alpha.git', 'rev-parse', 'main')


def test_an_admitted_tip_is_pushed_to_the_trunk(tmp_path: Path) -> None:
    url, tip = origin(tmp_path)
    [outcome] = run(config(tmp_path, [url]), promote=_admit)
    assert outcome.state == 'promoted'
    assert _origin_main(tmp_path) == tip


def test_a_refused_tip_pushes_nothing(tmp_path: Path) -> None:
    url, tip = origin(tmp_path)
    before = _origin_main(tmp_path)
    said = ('[integrate] ALARM: abc passed over: red',)
    [outcome] = run(config(tmp_path, [url]), promote=lambda _argv, _root: (2, said))
    assert outcome.state == 'refused'
    assert outcome.detail.endswith('[integrate] ALARM: abc passed over: red'), 'W5: a refusal names its reason'
    assert _origin_main(tmp_path) == before != tip


def test_a_failing_promote_is_a_failure_not_a_refusal(tmp_path: Path) -> None:
    url, _ = origin(tmp_path)
    [outcome] = run(config(tmp_path, [url]), promote=lambda _argv, _root: (1, ()))
    assert outcome.state == 'failed'


def test_a_promoted_tip_is_current_and_not_judged_again(tmp_path: Path) -> None:
    url, _ = origin(tmp_path)
    host = config(tmp_path, [url])
    run(host, promote=_admit)
    judged: list[str] = []

    def record(argv: list[str], _root: Path) -> tuple[int, tuple[str, ...]]:
        judged.append(argv[-1])
        return 0, ()

    [outcome] = run(host, promote=record)
    assert (outcome.state, judged) == ('current', [])


def test_one_failing_repo_does_not_stop_the_next(tmp_path: Path) -> None:
    url, _ = origin(tmp_path)
    missing = (tmp_path / 'forge' / 'owner' / 'gone.git').as_uri()
    outcomes = run(config(tmp_path, [missing, url]), promote=_admit)
    assert [outcome.state for outcome in outcomes] == ['failed', 'promoted']


def test_no_refusal_is_quiet(monkeypatch) -> None:
    """W5 (dev-lab#644): a refusal, and a promotion that passed over newer commits, is an alert naming why.

    PLANTED CONTROL: a clean promotion and a current trunk alert nothing.
    """
    alerted: list[tuple[str, str]] = []
    nights = [
        Outcome('a', 'refused', 'abc red'),
        Outcome('b', 'promoted', 'main -> def; ALARM', alarmed=True),
        Outcome('c', 'promoted', 'main -> 123'),
        Outcome('d', 'current', '456'),
    ]
    monkeypatch.setattr(hostverbs.promote, 'run', lambda _config: nights)
    monkeypatch.setattr(hostverbs, 'alert', lambda _config, title, detail: alerted.append((title, detail)))
    assert hostverbs.promote_verb(None) == 0
    assert alerted == [('promote REFUSED a', 'abc red'), ('promote PROMOTED b', 'main -> def; ALARM')]
