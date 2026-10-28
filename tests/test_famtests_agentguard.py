"""``dev_lab.dev.famtests.agentguard`` -- driven against a REAL engine on a REAL repository.

NOTHING HERE IS MODELLED. Each case builds a temporary git repository, installs the shipped engine
into it with :func:`dev_lab.dev.agent_guard.install_guard`, writes a rules file RENDERED from a
real :class:`~dev_lab.dev.hook_adoption.HookAdoption` over real
:class:`~dev_lab.dev.hooks.DenyRule` rows, and then runs ``node`` over the pair. The decision
read back is the one an agent's tool would receive, which is the only reading that can tell a live
guard from a plausible one.

THE SHADOWING DEFECT IS PLANTED IN BOTH DIRECTIONS, and it is the reason this body exists rather than
a copied file. Two rules are declared whose patterns BOTH match ``git push --force``; the registry
order decides which answers.
:func:`test_a_shadowed_rule_passes_the_weak_arm_and_is_caught_by_the_named_one` shows the weak
question -- *"was something refused"* -- answering yes while the rule that was supposed to fire is
covered for, and :func:`assert_refused_by` refusing. Reversing the order turns it green. Without that
pair the module's central claim would be prose.

THE FLOOR. :func:`test_an_empty_rules_file_refuses_nothing_and_the_pin_is_what_says_so` renders an
adoption that ships NO rule and shows the sanctioned arms all passing over it -- which is exactly the
vacuous green the by-name pin is there to catch.
"""

from __future__ import annotations

import inspect
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from lab_commons.proc import kill_process_tree

from dev_lab.dev import liverun
from dev_lab.dev.agent_guard import ENGINE_REL, RULES_REL, install_guard
from dev_lab.dev.agenthooks import run_engine
from dev_lab.dev.famtests.agentguard import (
    GuardNotLive,
    assert_committed_rules_are_rendered,
    assert_doors_name_live_rules,
    assert_every_rule_is_accounted_for,
    assert_node_is_available,
    assert_refused_by,
    assert_sanctioned,
    assert_the_guard_is_live,
    assert_the_shipped_set_is_pinned,
    decision_for,
    reason_for,
    shipped_rules,
)
from dev_lab.dev.hook_adoption import HookAdoption, render
from dev_lab.dev.hooks import DENY_RULES, DenyRule

_GIT = shutil.which('git') or 'git'

#: Two rules whose patterns BOTH match `git push --force`, in the order that makes the first shadow
#: the second. This is the live shape measured in one lab, reduced to its two rows.
_NETWORK = DenyRule(
    id='NETWORK-VERB',
    pattern=r'\bgit\s+(?:push|fetch)\b',
    hazard='a bare network verb retries nothing',
    remedy='route it through the retrying wrapper',
)
_FORCE = DenyRule(
    id='PUSH-FORCE',
    pattern=r'\bgit\s+push\b.*--force',
    hazard='rewriting a shared branch destroys the only published copy',
    remedy='push without rewriting history',
)
_TEMPLATED = DenyRule(
    id='TEMPLATED-REMEDY',
    pattern=r'\bgit\s+gc\b',
    hazard='a templated remedy names the interpreter by slot',
    remedy='run {python} -m dev_lab.dev.reclaim instead',
)
_STASH = DenyRule(
    id='GIT-STASH',
    pattern=r'\bgit\s+stash(?:\s|$)',
    hazard='`refs/stash` is repo-wide, so another worktree pops it',
    remedy='commit it on your own lane branch',
)


def _repo(tmp_path: Path, *, rules: tuple[DenyRule, ...], name: str = 'repo') -> tuple[Path, HookAdoption]:
    """A REAL git repository with the REAL engine installed and a REAL rendered rules file."""
    root = tmp_path / name
    root.mkdir(parents=True)
    subprocess.run([_GIT, 'init', '-q'], cwd=root, check=True, capture_output=True, timeout=60)
    install_guard(root)
    adoption = HookAdoption(app_name='fixture')
    (root / RULES_REL).write_text(render(adoption, rules), encoding='utf-8')
    return root, adoption


def _track_everything(root: Path) -> None:
    """Stage the tree, so `tracked_files` answers about a real index rather than an empty one."""
    for name, value in (('user.email', 'a@b.invalid'), ('user.name', 'Test')):
        subprocess.run([_GIT, 'config', name, value], cwd=root, check=True, capture_output=True, timeout=60)
    subprocess.run([_GIT, 'add', '-A'], cwd=root, check=True, capture_output=True, timeout=60)
    subprocess.run([_GIT, 'commit', '-q', '-m', 'fixture'], cwd=root, check=True, capture_output=True, timeout=60)


# --------------------------------------------------------------------------------------------
# the box, and the refusal that is not a skip


@pytest.mark.workstation
def test_node_is_available_here_and_the_refusal_is_not_a_skip() -> None:
    """The workstation's live hook runs the HOST node: absent, this REDS rather than going quiet."""
    assert_node_is_available()


def test_a_box_planted_without_node_is_refused_by_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED: the cluster compute node's PATH, which carries no ``node`` -- named, never quiet."""
    monkeypatch.setenv('PATH', str(tmp_path))
    with pytest.raises(GuardNotLive, match=r'no `node` on PATH.*unguarded'):
        assert_node_is_available()


# --------------------------------------------------------------------------------------------
# is it live


def test_a_freshly_installed_guard_is_live(tmp_path: Path) -> None:
    """The green arm, over a REAL install, so the refusals below are not all this can say."""
    root, _ = _repo(tmp_path, rules=(_NETWORK, _FORCE, _STASH))
    assert_the_guard_is_live(root=root)


def test_a_hand_copied_engine_in_the_same_slot_is_refused(tmp_path: Path) -> None:
    """PLANTED: the file is present and the guard is NOT the family's. Present is not installed."""
    root, _ = _repo(tmp_path, rules=(_STASH,))
    (root / ENGINE_REL).write_text('// a hand-written hook that allows everything\n', encoding='utf-8')
    with pytest.raises(GuardNotLive, match='engine'):
        assert_the_guard_is_live(root=root)


def test_a_repo_with_no_guard_at_all_is_refused(tmp_path: Path) -> None:
    """THE FLOOR on this arm: nothing declared must not read the same as everything installed."""
    bare = tmp_path / 'bare'
    bare.mkdir()
    with pytest.raises(GuardNotLive):
        assert_the_guard_is_live(root=bare)


# --------------------------------------------------------------------------------------------
# the declaration and the file


def test_the_committed_rules_match_the_rendered_ones_and_a_hand_edit_reds(tmp_path: Path) -> None:
    """BOTH DIRECTIONS. The declaration is the half a reader trusts; the JSON is what runs."""
    root, adoption = _repo(tmp_path, rules=(_NETWORK, _FORCE, _STASH))
    assert_committed_rules_are_rendered(root=root, adoption=adoption, rules=(_NETWORK, _FORCE, _STASH))

    rows = json.loads((root / RULES_REL).read_text(encoding='utf-8'))
    rows[0]['reason'] = 'edited by hand'
    (root / RULES_REL).write_text(json.dumps(rows, indent=2) + '\n', encoding='utf-8')
    with pytest.raises(GuardNotLive, match='drifted'):
        assert_committed_rules_are_rendered(root=root, adoption=adoption, rules=(_NETWORK, _FORCE, _STASH))


def test_every_rule_is_accounted_for_and_a_silent_gap_is_refused(tmp_path: Path) -> None:
    """A rule needing a repo artefact, neither remedied nor declared absent, is the silent case."""
    needs_an_exit = DenyRule(
        id='BARE-TEST-INVOCATION',
        pattern=r'\bpytest\b',
        hazard='a hand-written test line has no verdict',
        remedy='re-issue through {remedy}',
        needs='verdict-command',
    )
    root, adoption = _repo(tmp_path, rules=(needs_an_exit,))
    _track_everything(root)
    with pytest.raises(Exception, match='BARE-TEST-INVOCATION'):
        assert_every_rule_is_accounted_for(root=root, adoption=adoption, rules=(needs_an_exit,))

    declared = HookAdoption(app_name='fixture', declared_absent=frozenset({'BARE-TEST-INVOCATION'}))
    assert_every_rule_is_accounted_for(root=root, adoption=declared, rules=(needs_an_exit,))


# --------------------------------------------------------------------------------------------
# the floor: the shipped set, by name


def test_the_shipped_set_is_pinned_by_name_in_both_directions(tmp_path: Path) -> None:
    """A gain and a loss both red, and the message says WHICH -- which a count could not."""
    root, _ = _repo(tmp_path, rules=(_NETWORK, _STASH))
    assert shipped_rules(root=root) == frozenset({'NETWORK-VERB', 'GIT-STASH'})
    assert_the_shipped_set_is_pinned(root=root, declared=frozenset({'NETWORK-VERB', 'GIT-STASH'}))

    with pytest.raises(GuardNotLive, match='GIT-STASH'):
        assert_the_shipped_set_is_pinned(root=root, declared=frozenset({'NETWORK-VERB'}))
    with pytest.raises(GuardNotLive, match='PUSH-FORCE'):
        assert_the_shipped_set_is_pinned(root=root, declared=frozenset({'NETWORK-VERB', 'GIT-STASH', 'PUSH-FORCE'}))


def test_an_empty_rules_file_refuses_nothing_and_the_pin_is_what_says_so(tmp_path: Path) -> None:
    """THE VACUOUS GREEN, PLANTED. Every sanctioned arm passes over a guard that refuses nothing."""
    root, adoption = _repo(tmp_path, rules=())
    assert shipped_rules(root=root) == frozenset()
    assert_committed_rules_are_rendered(root=root, adoption=adoption, rules=())
    assert_sanctioned(root=root, command='git stash')
    assert_sanctioned(root=root, command='git push --force')
    with pytest.raises(GuardNotLive, match='GIT-STASH'):
        assert_the_shipped_set_is_pinned(root=root, declared=frozenset({'GIT-STASH'}))


# --------------------------------------------------------------------------------------------
# does it actually refuse, and by which rule


def test_a_forbidden_shape_is_refused_by_the_rule_that_owns_it(tmp_path: Path) -> None:
    """Driven through the REAL engine on the REAL installed files, not a Python restatement."""
    root, _ = _repo(tmp_path, rules=(_STASH, _NETWORK))
    assert_refused_by(root=root, command='git stash', rule='GIT-STASH')
    assert_refused_by(root=root, command='git fetch origin', rule='NETWORK-VERB')


def test_a_templated_remedy_is_judged_as_the_engine_prints_it(tmp_path: Path) -> None:
    """A ``{python}`` remedy is compared as the engine PRINTS it, so its own rule is recognised.

    The rules file carries the template; the engine prints the absolute interpreter (it read "NOT by").
    """
    root, _ = _repo(tmp_path, rules=(_TEMPLATED, _STASH))
    assert_refused_by(root=root, command='git gc', rule='TEMPLATED-REMEDY')
    with pytest.raises(GuardNotLive, match='NOT by TEMPLATED-REMEDY'):
        assert_refused_by(root=root, command='git stash', rule='TEMPLATED-REMEDY')


def test_a_sanctioned_shape_is_allowed(tmp_path: Path) -> None:
    """The other side of the ratchet: a guard refusing everything would pass every arm above."""
    root, _ = _repo(tmp_path, rules=(_STASH, _NETWORK))
    assert_sanctioned(root=root, command='ls -la')
    assert_sanctioned(root=root, command='python -c "print(1)"')
    with pytest.raises(GuardNotLive, match='refused it'):
        assert_sanctioned(root=root, command='git stash')


def test_a_shadowed_rule_passes_the_weak_arm_and_is_caught_by_the_named_one(tmp_path: Path) -> None:
    """THE MEASURED DEFECT, PLANTED BOTH WAYS.

    ``NETWORK-VERB`` ahead of ``PUSH-FORCE`` answers for ``git push --force``. The weak question --
    "was something refused" -- says yes, so ``PUSH-FORCE`` could stop firing entirely with the suite
    green. Naming the rule is what sees it, and reversing the registry order turns it green for the
    right reason rather than by loosening the arm.
    """
    shadowed, _ = _repo(tmp_path, rules=(_NETWORK, _FORCE), name='shadowed')
    command = 'git push --force origin main'

    assert decision_for(root=shadowed, command=command) is not None, 'the weak arm: something refused it'
    assert decision_for(root=shadowed, command=command) == reason_for(root=shadowed, rule='NETWORK-VERB')
    with pytest.raises(GuardNotLive, match='NOT by PUSH-FORCE'):
        assert_refused_by(root=shadowed, command=command, rule='PUSH-FORCE')

    ordered, _ = _repo(tmp_path, rules=(_FORCE, _NETWORK), name='ordered')
    assert_refused_by(root=ordered, command=command, rule='PUSH-FORCE')


def test_a_rule_that_is_not_shipped_cannot_be_expected_to_fire(tmp_path: Path) -> None:
    """A stale arm naming a retired rule must red, not silently assert about nothing."""
    root, _ = _repo(tmp_path, rules=(_STASH,))
    with pytest.raises(GuardNotLive, match='PUSH-FORCE'):
        reason_for(root=root, rule='PUSH-FORCE')


def test_a_missing_engine_is_a_refusal_and_never_a_quiet_allow(tmp_path: Path) -> None:
    """`None` means the engine ran and allowed. A file that is not there never ran at all."""
    root, _ = _repo(tmp_path, rules=(_STASH,))
    (root / ENGINE_REL).unlink()
    with pytest.raises(GuardNotLive, match='is not there'):
        decision_for(root=root, command='git stash')


# --------------------------------------------------------------------------------------------
# the family rule


def test_every_repo_shaped_argument_is_required() -> None:
    """A default hands one repo another's answer; only the family REGISTRY may carry one."""
    for func in (
        assert_the_guard_is_live,
        assert_the_shipped_set_is_pinned,
        assert_refused_by,
        assert_sanctioned,
        decision_for,
        reason_for,
        shipped_rules,
    ):
        defaults = {
            name: parameter.default
            for name, parameter in inspect.signature(func).parameters.items()
            if parameter.default is not inspect.Parameter.empty
        }
        assert defaults == {}, f'{func.__name__} carries defaults for repo-shaped facts: {defaults}'

    for func in (assert_committed_rules_are_rendered, assert_every_rule_is_accounted_for):
        parameters = inspect.signature(func).parameters
        assert parameters['root'].default is inspect.Parameter.empty
        assert parameters['adoption'].default is inspect.Parameter.empty
        assert parameters['rules'].default is not inspect.Parameter.empty, (
            "which rules EXIST is the family registry's answer, so that one may carry a default"
        )


def test_a_door_keyed_by_a_retired_rule_is_named_with_its_replacement(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.dev_lab.doors]\nGIT-NETWORK-VERB = "sh with-retry.sh push"\n', encoding='utf-8'
    )
    with pytest.raises(GuardNotLive, match='GIT-NETWORK-VERB is retired, rename it NETWORK-VERB'):
        assert_doors_name_live_rules(root=tmp_path)


def test_a_door_keyed_by_a_live_rule_passes(tmp_path: Path) -> None:
    """PLANTED CONTROL for the test above: the same door under its live ID."""
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.dev_lab.doors]\nNETWORK-VERB = "sh with-retry.sh push"\n', encoding='utf-8'
    )
    assert_doors_name_live_rules(root=tmp_path)


def test_this_repo_keys_its_doors_by_live_rules() -> None:
    assert_doors_name_live_rules(root=Path(__file__).resolve().parents[1])


# --------------------------------------------------------------------------------------------
# a probe judges the SHAPE, never the state of the box it runs on


@pytest.fixture
def live_repo(tmp_path: Path) -> Iterator[Path]:
    """A repo with the REAL guard and the FULL family registry, its venv this interpreter, and a run in it."""
    root = tmp_path / 'live'
    root.mkdir()
    subprocess.run([_GIT, 'init', '-q'], cwd=root, check=True, capture_output=True, timeout=60)
    install_guard(root)
    absent = frozenset(rule.id for rule in DENY_RULES if rule.needs is not None)
    (root / RULES_REL).write_text(render(HookAdoption(app_name='f', declared_absent=absent)), encoding='utf-8')
    if os.name == 'nt':
        shell = os.environ.get('COMSPEC', 'cmd.exe')
        subprocess.run([shell, '/c', 'mklink', '/J', str(root / '.venv'), sys.prefix], check=True, capture_output=True)
    else:
        (root / '.venv').symlink_to(sys.prefix, target_is_directory=True)
    sleeper = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'], cwd=root)
    try:
        deadline = time.monotonic() + 60
        while not liverun.live_runs(root) and time.monotonic() < deadline:
            time.sleep(0.5)
        assert liverun.live_runs(root), 'the planted run never became a live run'
        yield root
    finally:
        kill_process_tree(sleeper.pid)
        sleeper.wait(timeout=30)


def test_a_probe_names_the_shape_rule_while_a_run_is_live_in_the_tree(live_repo: Path) -> None:
    """INCIDENT (wdg-lab cutover): the probing suite IS a live run, so TREE-HAS-A-LIVE-RUN answered first."""
    assert_refused_by(root=live_repo, command='git stash', rule='GIT-STASH')


def test_the_installed_guard_still_refuses_a_live_tree_by_its_live_run(live_repo: Path) -> None:
    """PLANTED CONTROL: production judges the box; only the probe takes the live-run state as absent."""
    reason = run_engine(live_repo / ENGINE_REL, 'git stash', live_repo / RULES_REL, cwd=live_repo)
    assert reason is not None
    assert reason.startswith('TREE-HAS-A-LIVE-RUN:'), reason
