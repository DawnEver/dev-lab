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

from lab_commons.compute.model import Schedule
from lab_commons.dev.forgealarm import INTEGRATION
from lab_commons.dev.forgestatus import Status
from lab_commons.dev.integrator import (
    BLOCKED,
    MERGE,
    PARTS_NEEDED,
    PROMOTE,
    WAITING,
    LaneRef,
    lane_ready,
    main,
    observe,
    prompts,
    read_refs,
    ready_lanes,
)
from lab_commons.dev.lanepolicy import Policy, load_policy

_POLICY = Policy()
_SCHEDULE = Schedule()


def _ref(branch: str, tip: str, at: int = 0, *, absorbed: bool = False) -> LaneRef:
    return LaneRef(branch, tip, at, absorbed=absorbed)


def _part(state: str = 'success', *, platform: str = 'base', scope: str = 'full', hands: str = '-') -> Status:
    """A ``tests/<platform>`` part as the forge holds it -- the one name for a platform result."""
    return Status(f'tests/{platform}', state, f'scope={scope} ran=3 hands={hands}', '')


_GREEN = (_part(),)
_RED = (_part('failure'),)


def test_a_lane_is_ready_only_when_its_parts_stand_pass() -> None:
    assert lane_ready(_GREEN, head='a')
    assert lane_ready((_part(scope='incremental'),), head='a'), 'a lane takes a part of any scope'
    assert not lane_ready(_RED, head='a')
    assert not lane_ready((), head='a'), 'no part is no result'
    assert not lane_ready((_part('pending'),), head='a'), 'a claim is not a part'
    assert not lane_ready((_part(hands='windows:2'),), head='a'), 'a part handing to a missing platform'


def test_a_retired_lab_namespace_status_is_not_a_platform_result() -> None:
    """PLANTED: a green ``lab``-namespace status carries no part, so the lane still waits."""
    assert not lane_ready((Status('lab' + '/gate', 'success', 'PASS', ''),), head='a')


def test_a_lane_is_ready_only_on_a_green_gate_at_its_exact_tip() -> None:
    refs = (_ref('feat/a', 'a1', 3), _ref('feat/b', 'b1', 1), _ref('fix/2-c', 'c1', 2), _ref('feat/d', 'd1'))
    statuses = {'a1': _GREEN, 'b1': _GREEN, 'c1': _RED}
    queue = ready_lanes(refs, statuses, _POLICY)
    # Ordered by the tip's commit time, oldest first: the lane that finished first merges first.
    assert [lane.branch for lane in queue.merge] == ['feat/b', 'feat/a']
    assert {(lane.branch, lane.state) for lane in queue.held} == {('fix/2-c', BLOCKED), ('feat/d', WAITING)}


def test_a_status_on_an_older_tip_does_not_carry_to_a_moved_or_force_pushed_one() -> None:
    queue = ready_lanes((_ref('feat/a', 'new'),), {'old': _GREEN}, _POLICY)
    assert queue.merge == ()
    assert [(lane.branch, lane.state) for lane in queue.held] == [('feat/a', WAITING)]


def test_absorbed_lanes_and_the_integration_branches_are_never_queued() -> None:
    green = _GREEN
    refs = (
        _ref('feat/done', 'f', absorbed=True),
        _ref('integrate/main', 'i', absorbed=True),
        _ref('main', 'm'),
    )
    queue = ready_lanes(refs, dict.fromkeys('wfim', green), _POLICY)
    assert (queue.merge, queue.held, queue.promotion) == ((), (), None)


def test_ties_order_by_branch_name_so_two_modes_print_the_same_queue() -> None:
    green = _GREEN
    queue = ready_lanes((_ref('feat/z', 'z', 5), _ref('feat/a', 'a', 5)), {'z': green, 'a': green}, _POLICY)
    assert [lane.branch for lane in queue.merge] == ['feat/a', 'feat/z']


@pytest.mark.parametrize(
    ('parts', 'state'),
    [
        (_GREEN, PROMOTE),
        (_RED, BLOCKED),
        ((), PARTS_NEEDED),
        ((_part('pending'),), PARTS_NEEDED),
        ((_part(scope='incremental'),), PARTS_NEEDED),
    ],
)
def test_the_integration_tip_not_on_main_is_judged_by_its_full_parts(parts: tuple[Status, ...], state: str) -> None:
    """The same reading push admission makes for the trunk: every part a PASS of scope full."""
    statuses = {'i': parts}
    queue = ready_lanes((_ref('integrate/main', 'i'),), statuses, _POLICY)
    assert queue.promotion is not None
    assert (queue.promotion.branch, queue.promotion.state) == ('integrate/main', state)


def test_the_consumer_declares_its_branches_and_a_retired_host_is_refused_by_name(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text('[tool.lab_commons.integrator]\nintegration = "stage"\n', encoding='utf-8')
    assert load_policy(tmp_path) == Policy(integration='stage')
    (tmp_path / 'pyproject.toml').write_text('[tool.lab_commons.integrator]\nhost = "G"\n', encoding='utf-8')
    with pytest.raises(ValueError, match=r'host is retired: .*no host owns integration'):
        load_policy(tmp_path)
    assert load_policy(tmp_path / 'absent') == Policy()


def test_the_retired_prefix_list_is_refused_by_name_with_the_rule_that_replaced_it(tmp_path: Path) -> None:
    retired = 'lane' + '_prefixes'
    (tmp_path / 'pyproject.toml').write_text(f'[tool.lab_commons.integrator]\n{retired} = ["x/"]\n', 'utf-8')
    with pytest.raises(ValueError, match='classes_by_ref'):
        load_policy(tmp_path)


def test_a_malformed_declaration_is_refused_by_name(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text('[tool.lab_commons.integrator]\nlane_prefix = "x/"\n', encoding='utf-8')
    with pytest.raises(ValueError, match='lane_prefix'):
        load_policy(tmp_path)


def _commit(repo: Path, message: str) -> str:
    # A REAL change per commit: absorption is judged by patch-id (`git cherry`), and two EMPTY commits
    # carry no change to tell apart, so an empty `feat/out` reads as already held by `feat/in`.
    (repo / f'{message.replace(":", "").replace(" ", "_")}.txt').write_text(message, encoding='utf-8')
    run_git(repo, 'add', '-A')
    run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', message)
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
    found = {ref.branch: ref for ref in read_refs(repo, _POLICY, _SCHEDULE)}
    assert set(found) == {'feat/in', 'feat/out', 'integrate/main'}, 'wip/x: no class, so not a lane'
    assert found['feat/in'].absorbed
    assert not found['feat/out'].absorbed
    assert found['feat/out'].tip == tips['feat/out']
    assert not found['integrate/main'].absorbed  # not yet on main
    assert found['feat/out'].committed_at > 0


def test_the_poll_entry_prints_the_ordered_queue(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, tips = _repo(tmp_path)
    green = {tips['feat/out']: _GREEN}

    def statuses(sha: str) -> tuple[Status, ...]:
        return green.get(sha, ())

    assert main(['queue', '--json'], cwd=repo, statuses=statuses) == 0
    printed = json.loads(capsys.readouterr().out)
    assert [lane['branch'] for lane in printed['merge']] == ['feat/out']
    assert printed['promotion']['state'] == PARTS_NEEDED
    assert main(['queue'], cwd=repo, statuses=statuses) == 0
    assert f'merge  feat/out  {tips["feat/out"][:12]}' in capsys.readouterr().out


def test_the_classes_rule_names_the_lanes(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same refs, a rule that classes ``wip/*`` -- and only then is it a lane."""
    repo, _ = _repo(tmp_path)
    wip = Schedule(classes_by_ref={'wip/*': 'branch'})
    assert {ref.branch for ref in read_refs(repo, _POLICY, wip)} == {'wip/x', 'integrate/main'}


def test_each_ready_promotable_or_red_row_is_one_prompt_keyed_by_its_tip() -> None:
    refs = (_ref('feat/ok', 'o'), _ref('feat/red', 'r'), _ref('feat/wait', 'w'), _ref('integrate/main', 'i'))
    queue = ready_lanes(refs, {'o': _GREEN, 'r': _RED, 'i': _GREEN}, _POLICY)
    alarms = prompts(queue, 'o/r')
    assert {(a.kind, a.about) for a in alarms} == {
        (INTEGRATION, f'{MERGE} feat/ok@o'),
        (INTEGRATION, f'{BLOCKED} feat/red@r'),
        (INTEGRATION, f'{PROMOTE} integrate/main@i'),
    }, 'a waiting lane prompts nobody'
    moved = prompts(ready_lanes((_ref('feat/ok', 'o2'),), {'o2': _GREEN}, _POLICY), 'o/r')
    assert [a.about for a in moved] == [f'{MERGE} feat/ok@o2'], 'a moved tip is a NEW prompt, delivered at once'


def test_any_host_derives_the_prompts(tmp_path: Path) -> None:
    """No owner and no host argument: whoever serves derives the same rows (the forge keeps one issue each)."""
    repo, tips = _repo(tmp_path)
    green = {tips['feat/out']: _GREEN}
    found = observe(repo, 'o/r', statuses=lambda sha: green.get(sha, ()))
    assert [a.about for a in found] == [f'{MERGE} feat/out@{tips["feat/out"][:12]}']
