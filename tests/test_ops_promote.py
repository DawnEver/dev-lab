"""The promote role judges origin's integration tip by ``integrate promote`` and pushes only what it admits."""

from __future__ import annotations

from pathlib import Path

from _ops_fixtures import config, git, origin

from dev_lab.ops.promote import run


def _admit(argv: list[str], root: Path) -> int:
    git(root, 'update-ref', 'refs/heads/main', argv[1])
    return 0


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
    [outcome] = run(config(tmp_path, [url]), promote=lambda _argv, _root: 2)
    assert outcome.state == 'refused'
    assert _origin_main(tmp_path) == before != tip


def test_a_failing_promote_is_a_failure_not_a_refusal(tmp_path: Path) -> None:
    url, _ = origin(tmp_path)
    [outcome] = run(config(tmp_path, [url]), promote=lambda _argv, _root: 1)
    assert outcome.state == 'failed'


def test_a_promoted_tip_is_current_and_not_judged_again(tmp_path: Path) -> None:
    url, _ = origin(tmp_path)
    host = config(tmp_path, [url])
    run(host, promote=_admit)
    judged: list[str] = []

    def record(argv: list[str], _root: Path) -> int:
        judged.append(argv[1])
        return 0

    [outcome] = run(host, promote=record)
    assert (outcome.state, judged) == ('current', [])


def test_one_failing_repo_does_not_stop_the_next(tmp_path: Path) -> None:
    url, _ = origin(tmp_path)
    missing = (tmp_path / 'forge' / 'owner' / 'gone.git').as_uri()
    outcomes = run(config(tmp_path, [missing, url]), promote=_admit)
    assert [outcome.state for outcome in outcomes] == ['failed', 'promoted']
