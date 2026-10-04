"""INTEGRATOR-QUEUE: one ready predicate, one derived queue, whichever mode woke the integrator.

The pure half is driven with PLANTED refs and statuses; the git half reads REAL remote-tracking refs
planted with ``git update-ref`` over real commits -- exactly what a fetch leaves behind -- so no
network is involved (the module is fetch-free by contract, like ``forgeissue``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _forge_fake import git_out, make_repo, run_git

from lab_commons.dev.forgestatus import GATE_CONTEXT, HEAVY_CONTEXT, Status
from lab_commons.dev.integrator import (
    BLOCKED,
    HEAVY_NEEDED,
    PROMOTE,
    WAITING,
    LaneRef,
    Policy,
    gate_ready,
    load_policy,
    main,
    read_refs,
    ready_lanes,
)

_POLICY = Policy(lane_prefixes=('feat/', 'fix/'))


def _ref(branch: str, tip: str, at: int = 0, *, absorbed: bool = False) -> LaneRef:
    return LaneRef(branch, tip, at, absorbed=absorbed)


def test_gate_ready_is_success_and_nothing_else() -> None:
    assert gate_ready('success')
    assert not any(gate_ready(state) for state in ('failure', 'pending', 'error', ''))


def test_a_lane_is_ready_only_on_a_green_gate_at_its_exact_tip() -> None:
    refs = (_ref('feat/a', 'a1', 3), _ref('feat/b', 'b1', 1), _ref('fix/2-c', 'c1', 2), _ref('feat/d', 'd1'))
    statuses = {'a1': {GATE_CONTEXT: 'success'}, 'b1': {GATE_CONTEXT: 'success'}, 'c1': {GATE_CONTEXT: 'failure'}}
    queue = ready_lanes(refs, statuses, _POLICY)
    # Ordered by the tip's commit time, oldest first: the lane that finished first merges first.
    assert [lane.branch for lane in queue.merge] == ['feat/b', 'feat/a']
    assert {(lane.branch, lane.state) for lane in queue.held} == {('fix/2-c', BLOCKED), ('feat/d', WAITING)}


def test_a_status_on_an_older_tip_does_not_carry_to_a_moved_or_force_pushed_one() -> None:
    queue = ready_lanes((_ref('feat/a', 'new'),), {'old': {GATE_CONTEXT: 'success'}}, _POLICY)
    assert queue.merge == ()
    assert [(lane.branch, lane.state) for lane in queue.held] == [('feat/a', WAITING)]


def test_undeclared_prefixes_absorbed_lanes_and_the_integration_branches_are_never_queued() -> None:
    green = {GATE_CONTEXT: 'success'}
    refs = (
        _ref('wip/x', 'w'),
        _ref('feat/done', 'f', absorbed=True),
        _ref('integrate/main', 'i', absorbed=True),
        _ref('main', 'm'),
    )
    queue = ready_lanes(refs, dict.fromkeys('wfim', green), _POLICY)
    assert (queue.merge, queue.held, queue.promotion) == ((), (), None)


def test_ties_order_by_branch_name_so_two_modes_print_the_same_queue() -> None:
    green = {GATE_CONTEXT: 'success'}
    queue = ready_lanes((_ref('feat/z', 'z', 5), _ref('feat/a', 'a', 5)), {'z': green, 'a': green}, _POLICY)
    assert [lane.branch for lane in queue.merge] == ['feat/a', 'feat/z']


@pytest.mark.parametrize(
    ('heavy', 'state'),
    [('success', PROMOTE), ('failure', BLOCKED), ('', HEAVY_NEEDED), ('pending', HEAVY_NEEDED)],
)
def test_the_integration_tip_not_on_main_is_judged_by_its_heavy_status(heavy: str, state: str) -> None:
    statuses = {'i': {HEAVY_CONTEXT: heavy}} if heavy else {}
    queue = ready_lanes((_ref('integrate/main', 'i'),), statuses, _POLICY)
    assert queue.promotion is not None
    assert (queue.promotion.branch, queue.promotion.state) == ('integrate/main', state)


def test_the_consumer_declares_prefixes_branches_and_contexts(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.lab_commons.integrator]\nlane_prefixes = ["lane/"]\nintegration = "stage"\ngate_context = "ci/gate"\n',
        encoding='utf-8',
    )
    policy = load_policy(tmp_path)
    assert policy == Policy(lane_prefixes=('lane/',), integration='stage', gate_context='ci/gate')
    assert load_policy(tmp_path / 'absent') == Policy()


def test_a_malformed_declaration_is_refused_by_name(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text('[tool.lab_commons.integrator]\nlane_prefix = "x/"\n', encoding='utf-8')
    with pytest.raises(ValueError, match='lane_prefix'):
        load_policy(tmp_path)


def _commit(repo: Path, message: str) -> str:
    run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', message)
    return git_out(repo, 'rev-parse', 'HEAD')


def _repo(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """origin/main = base; origin/integrate/main holds feat/in; feat/out is new work; wip/x undeclared."""
    repo = make_repo(tmp_path, 'https://forge.example.org/o/r.git', branch='main')
    tips = {'main': _commit(repo, 'feat: base')}
    run_git(repo, 'switch', '-q', '-c', 'feat/in')
    tips['feat/in'] = _commit(repo, 'feat: in')
    tips['integrate/main'] = tips['feat/in']
    run_git(repo, 'switch', '-q', '-c', 'feat/out', 'main')
    tips['feat/out'] = _commit(repo, 'feat: out')
    tips['wip/x'] = tips['feat/out']
    for name, sha in tips.items():
        run_git(repo, 'update-ref', f'refs/remotes/origin/{name}', sha)
    return repo, tips


def test_read_refs_marks_what_the_integration_branch_already_holds(tmp_path: Path) -> None:
    repo, tips = _repo(tmp_path)
    found = {ref.branch: ref for ref in read_refs(repo, _POLICY)}
    assert set(found) == {'feat/in', 'feat/out', 'integrate/main'}
    assert found['feat/in'].absorbed
    assert not found['feat/out'].absorbed
    assert found['feat/out'].tip == tips['feat/out']
    assert not found['integrate/main'].absorbed  # not yet on main
    assert found['feat/out'].committed_at > 0


def test_the_poll_entry_prints_the_ordered_queue(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, tips = _repo(tmp_path)
    green = {tips['feat/out']: (Status(GATE_CONTEXT, 'success', 'PASS', ''),)}

    def statuses(sha: str) -> tuple[Status, ...]:
        return green.get(sha, ())

    assert main(['queue', '--json'], cwd=repo, statuses=statuses) == 0
    printed = json.loads(capsys.readouterr().out)
    assert [lane['branch'] for lane in printed['merge']] == ['feat/out']
    assert printed['promotion']['state'] == HEAVY_NEEDED
    assert main(['queue'], cwd=repo, statuses=statuses) == 0
    assert f'merge  feat/out  {tips["feat/out"][:12]}' in capsys.readouterr().out
