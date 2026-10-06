"""THE ALLOW HALF, and every arm here is a control in one of the two directions.

A generator with no control that a MISSING row is caught is the vacuous-scan defect wearing a new
hat: it would render a block, compare it to itself, and report agreement. So the planted rows come
in pairs -- one the mechanism must find, one it must not -- and the rows that are REAL are the nine
measured live on 2026-09-18 across the three consuming repos, quoted here as the derivation's own
evidence rather than as fixtures invented to agree with it.
"""

from __future__ import annotations

from collections.abc import Sequence
from fnmatch import fnmatchcase
from typing import Final

import pytest

from lab_commons.dev.allow_adoption import (
    AllowAdoption,
    DeclaredAllow,
    UnarguedAllow,
    allow_entries,
    allow_gaps,
    assert_allow_is_adoptable,
    derived_entries,
    glob_for,
    live_bash_rows,
    permissions_block,
    provenance,
    self_refused,
    settings_problems,
)
from lab_commons.dev.autodoors import claude_rows
from lab_commons.dev.floors import FloorMisdeclared, FloorUnmet, SlackFloor
from lab_commons.dev.hook_adoption import HookAdoption
from lab_commons.dev.hooks import Remedy
from lab_commons.dev.venvpath import INTERPRETER_ALLOW_ENTRY, INTERPRETER_RULE, VENV_LAYOUTS, venv_interpreter

#: The verdict entry point BOTH labs hand-wrote, character for character, in their own settings
#: files AND in their own `scripts/deny_rules.py`. The agreement is the evidence for `glob_for`.
VERIFY = Remedy('verdict-entry-point', './.venv/Scripts/python.exe -m lab_commons.dev.verify')

#: consumer-b's network remedy. It SPELLS the shape its own rule matches, so it carries an opening --
#: the one case `self_refused` exists for.
NETVERB = Remedy(
    'retry-wrapper',
    './.venv/Scripts/python.exe -m lab_commons.dev.netverb -- <verb>',
    allow=r'lab_commons\.dev\.netverb\b',
)

#: consumer-a' process-tree killer, as its own `deny-rules.json` reason spells the command.
SWEEP = Remedy('process-tree-killer', '.venv/Scripts/python.exe scripts/gate/stop_sweep.py --pid <root-pid>')

CONSUMER_C = HookAdoption(
    app_name='consumer_c',
    remedies={'BARE-TEST-INVOCATION': VERIFY, 'PUSH-NO-VERIFY': VERIFY},
    declared_absent=frozenset({'GIT-NETWORK-VERB', 'RAW-PROCESS-KILL'}),
)
CONSUMER_B = HookAdoption(
    app_name='consumer_b',
    remedies={'BARE-TEST-INVOCATION': VERIFY, 'PUSH-NO-VERIFY': VERIFY, 'GIT-NETWORK-VERB': NETVERB},
    declared_absent=frozenset({'RAW-PROCESS-KILL'}),
)
CONSUMER_A = HookAdoption(
    app_name='consumer_a',
    remedies={'RAW-PROCESS-KILL': SWEEP},
    declared_absent=frozenset({'BARE-TEST-INVOCATION', 'PUSH-NO-VERIFY', 'GIT-NETWORK-VERB'}),
)


def test_the_permission_block_carries_the_owned_worktree_dependency_doors() -> None:
    adoption = AllowAdoption(app_name='consumer_a', adoption=CONSUMER_A, scripts=('scripts/gate/dep_sync.py',))
    globs = [row.removeprefix('Bash(').removesuffix(')') for row in allow_entries(adoption)]
    for interpreter in (
        '.claude/worktrees/lane/.venv/Scripts/python.exe',
        '.claude/worktrees/lane/.venv/bin/python',
    ):
        assert any(fnmatchcase(f'{interpreter} scripts/gate/dep_sync.py --sync', pattern) for pattern in globs)
        assert any(fnmatchcase(f'{interpreter} -m lab_commons.dev.dep --bootstrap lane', pattern) for pattern in globs)
        assert not any(fnmatchcase(f'{interpreter} -m pip install arbitrary', pattern) for pattern in globs)


def test_no_row_the_block_can_carry_begins_with_a_wildcard() -> None:
    """THE CONSUMER'S OWN PROPERTY, over every row THIS KIT renders.

    ``Bash(*/.venv/Scripts/python.exe ...)`` was a leading wildcard BY CONSTRUCTION, not by accident:
    a worktree's interpreter genuinely may live in another checkout, and the first spelling bought
    that with a ``*`` that also permits any invocation PREFIX -- another interpreter, another
    checkout's copy, a wrapper nobody sanctioned. MEASURED 2026-10-06 in a consuming repo: 86 of its
    271 rendered rows led with ``*``, all of them worktree spellings of a door row, and its own
    architecture suite refuses that shape by name. The rows are still emitted; their directory is
    anchored on the worktrees directory (rule WORKTREES-STAY-INSIDE) instead of wildcarded.

    Driven through the REAL renderers -- the derived rows, the BARE-INTERPRETER constant and the
    door rows -- rather than against a list, and both directions are planted: the guard is shown
    firing on the spelling it exists for, and the block is shown carrying something to check. A
    DECLARED row is outside this property and stays so: it is the repo's own text, VERBATIM, which
    is what an escape hatch IS -- the kit judges what it derives, and the reader judges the row
    somebody argued for.
    """
    allow = AllowAdoption('consumer_a', CONSUMER_A, scripts=('scripts/gate/runner.py',))
    entries = allow_entries(allow)
    assert len(entries) > 6, 'a block this small would make the assertion below vacuous'
    led = _leading_wildcards(entries)
    assert not led, f'{led} lead with a wildcard, which permits any invocation prefix'
    assert _leading_wildcards([*entries, 'Bash(*/.venv/Scripts/python.exe scripts/gate/runner.py *)']) == (
        'Bash(*/.venv/Scripts/python.exe scripts/gate/runner.py *)',
    ), 'the control: a row that leads with `*` must be caught by this exact expression'


def _leading_wildcards(entries: Sequence[str]) -> tuple[str, ...]:
    """The consumer's own expression, so the property pinned here is the one enforced downstream."""
    return tuple(entry for entry in entries if entry[len('Bash(') : -1].startswith('*'))


#: A remedy whose interpreter is preceded by a metavariable: the prefix is exactly what a tracked
#: row cannot know, so no spelling of this road without a leading `*` exists. Reachable through the
#: real renderer, which is why the refusal is pinned rather than the row.
METAVARIABLE_PREFIXED: Final = (
    '<repo>/.venv/Scripts/python.exe scripts/gate/runner.py',
    '{root}/.venv/bin/python -m lab_commons.dev.verify',
)


@pytest.mark.parametrize('command', METAVARIABLE_PREFIXED)
def test_a_remedy_that_would_render_a_leading_wildcard_is_refused_and_the_input_is_named(command: str) -> None:
    """THE REFUSAL HALF: where no acceptable spelling exists, no row is derived and the remedy is named.

    ``portable`` rewrites the venv spelling but keeps whatever precedes it, and a metavariable there
    becomes ``*`` one step later -- so the derivation CAN produce the forbidden shape, and refusing
    is the only honest answer: the command names an unknown prefix, and a row for it permits every
    prefix. The repair is the caller's, and the message says which: spell the road from a path the
    repo tracks, or DECLARE the row and argue for it.
    """
    with pytest.raises(UnarguedAllow, match='LEADS with a wildcard') as refused:
        glob_for(command)
    assert command in str(refused.value), 'the refusal must name the remedy it refused'


def test_the_same_road_spelled_from_a_tracked_path_renders_with_no_leading_wildcard() -> None:
    """THE OTHER SIDE, so the refusal above is a narrowing rather than a wall."""
    rendered = glob_for('.venv/Scripts/python.exe scripts/gate/runner.py')
    assert rendered == 'Bash(.venv/*/python* scripts/gate/runner.py *)'
    assert not _leading_wildcards([rendered])


def test_the_glob_matches_the_row_two_repos_wrote_by_hand() -> None:
    """THE DERIVATION IS READ OFF THE DATA: the rendered row is the one both labs already hold.

    It is no longer CHARACTER-identical to what those two hands wrote, and that is the 2026-09-19
    correction rather than a drift. Both wrote `.venv/Scripts/python.exe`, a file macOS does not
    have, into a file that is TRACKED IN GIT -- so on half the fleet the row permitted nothing, and
    an allow row that matches no command is indistinguishable from one nobody needed. The
    interpreter is normalised; everything either hand actually decided is preserved.
    """
    assert glob_for(VERIFY.command) == 'Bash(./.venv/*/python* -m lab_commons.dev.verify *)'


def test_both_platform_spellings_of_one_remedy_derive_the_same_row() -> None:
    """THE ROW IS PORTABLE OR IT IS FALSE SOMEWHERE. Two inputs, one row -- not two rows.

    Not two entries, because `derived_entries` renders one row per remedy command precisely so a
    diff can say which road a deletion removed, and a platform pair is that hazard with a label on
    it. Not rendered-at-adoption either: that makes a TRACKED file per-machine, so it reds in every
    checkout on the other platform and the only repair available to that reader reds the first one
    back. A glob is the one option that is TRUE on both platforms at once.
    """
    tail = ' -m lab_commons.dev.verify'
    rendered = {glob_for('./' + venv_interpreter(os_name=name) + tail) for name in VENV_LAYOUTS}
    assert rendered == {'Bash(./.venv/*/python* -m lab_commons.dev.verify *)'}


def test_a_metavariable_becomes_one_wildcard_and_no_trailing_star_is_doubled() -> None:
    """`<root-pid>` is the agent's own value; a command already ending in `*` gains no second one."""
    assert glob_for(SWEEP.command) == 'Bash(.venv/*/python* scripts/gate/stop_sweep.py --pid *)'
    assert glob_for(NETVERB.command) == 'Bash(./.venv/*/python* -m lab_commons.dev.netverb -- *)'


def test_a_root_token_never_ships_literally() -> None:
    """The agent client expands no `{root}`, so a literal one would promise a path no box has."""
    assert glob_for('sh {root}/scripts/hooks/with-retry.sh push') == 'Bash(sh */scripts/hooks/with-retry.sh push *)'


def test_a_remedy_that_is_all_metavariable_derives_nothing() -> None:
    """THE CONTROL AGAINST `Bash(*)`: a row promising every command answers no rule in particular."""
    with pytest.raises(UnarguedAllow, match='every command there is'):
        glob_for('<anything>')


def test_one_row_per_remedy_naming_every_rule_it_answers() -> None:
    """A repo with one verdict command gets ONE row, and it says both rules it is the exit from."""
    assert derived_entries(CONSUMER_C) == {
        'Bash(./.venv/*/python* -m lab_commons.dev.verify *)': ('BARE-TEST-INVOCATION', 'PUSH-NO-VERIFY'),
        INTERPRETER_ALLOW_ENTRY: (INTERPRETER_RULE,),
    }


def test_a_rule_declared_absent_derives_no_row() -> None:
    """THE `needs` RULE ON THIS SIDE: consumer-c has no process-tree killer, so it promises none."""
    assert not any('stop_sweep' in entry for entry in derived_entries(CONSUMER_C))
    assert 'Bash(.venv/*/python* scripts/gate/stop_sweep.py --pid *)' in derived_entries(CONSUMER_A)


def test_a_needs_none_rule_is_never_derived_from() -> None:
    """GIT-STASH, PUSH-FORCE and WORKTREE-BASE-IS-EXPLICIT have PROSE exits, so nothing is guessed."""
    assert set(derived_entries(CONSUMER_B)) == {
        'Bash(./.venv/*/python* -m lab_commons.dev.verify *)',
        'Bash(./.venv/*/python* -m lab_commons.dev.netverb -- *)',
        INTERPRETER_ALLOW_ENTRY,  # the ONE needs-none exit that is a row: the owner's interpreter spelling
    }


def test_a_declared_road_costs_an_argument() -> None:
    """An allow list is not a place to pre-pay for roads nobody has needed yet."""
    with pytest.raises(UnarguedAllow, match='pre-pay'):
        DeclaredAllow('Bash(*yarn preview*)', '')


def test_a_row_that_is_not_a_permission_row_is_refused() -> None:
    """A line the agent client ignores, that a reader takes for a permission, is the lie."""
    with pytest.raises(UnarguedAllow, match='not a permission row'):
        DeclaredAllow('yarn preview', 'the docs preview server')


def test_a_declared_row_may_not_restate_a_derived_one() -> None:
    """THE FORK, refused at construction: a hand copy is where the two halves start to differ."""
    with pytest.raises(UnarguedAllow, match='already derive'):
        AllowAdoption(
            app_name='consumer_b',
            adoption=CONSUMER_C,
            declared=(DeclaredAllow('Bash(./.venv/*/python* -m lab_commons.dev.verify *)', 'the verdict'),),
        )


def test_provenance_says_which_population_each_row_came_from() -> None:
    """Derived and declared are different repairs, so they are never merged into one flat list."""
    allow = AllowAdoption('consumer_b', CONSUMER_B, (DeclaredAllow('Bash(*yarn preview*)', 'the docs preview server'),))
    seen = provenance(allow)
    assert seen['Bash(*yarn preview*)'] == 'declared: the docs preview server'
    assert seen['Bash(./.venv/*/python* -m lab_commons.dev.netverb -- *)'] == 'derived from GIT-NETWORK-VERB'


#: A remedy spelling the very shape its own rule matches, with NO opening. `RAW-PROCESS-KILL` is
#: `matches: argument`, so `fires` searches the whole segment and this IS reachable from here --
#: unlike `netverb`'s exit, which spells `git push` in its tail where only the real engine, which
#: splits nested command positions, can see it. The scope is the point rather than an inconvenience.
BLIND_KILL = Remedy('process-tree-killer', 'Stop-Process -Id <root-pid>')

#: The same command with the opening its shipped rule would carry. It does NOT open this row, and
#: that is the second direction: the opening has to match the command the remedy actually names.
MISDIRECTED_KILL = Remedy('process-tree-killer', 'Stop-Process -Id <root-pid>', allow=r'\bstop_sweep\.py\b')


def _killer(remedy: Remedy) -> HookAdoption:
    """ConsumerA' adoption with one substituted process-tree remedy, so the plant is the only change."""
    return HookAdoption(
        app_name='consumer_a',
        remedies={'RAW-PROCESS-KILL': remedy},
        declared_absent=frozenset({'BARE-TEST-INVOCATION', 'PUSH-NO-VERIFY', 'GIT-NETWORK-VERB'}),
    )


def test_a_remedy_spelling_its_own_rules_shape_is_caught_where_this_half_can_see_it() -> None:
    """BOTH DIRECTIONS: the real remedies are clean, the planted one reds, the wrong opening does not."""
    assert self_refused(AllowAdoption('consumer_b', CONSUMER_B)) == ()
    assert self_refused(AllowAdoption('consumer_a', CONSUMER_A)) == ()
    caught = self_refused(AllowAdoption('consumer_a', _killer(BLIND_KILL)))
    assert any('RAW-PROCESS-KILL refuses' in problem for problem in caught), caught
    assert self_refused(AllowAdoption('consumer_a', _killer(MISDIRECTED_KILL))) == caught


def test_a_missing_derived_row_is_the_finding_and_a_clean_block_is_not() -> None:
    """THE 2026-09-18 INCIDENT ITSELF, planted in both directions over the same adoption."""
    allow = AllowAdoption('consumer_a', CONSUMER_A)
    rendered = {'permissions': {'allow': list(allow_entries(allow))}}
    assert settings_problems(rendered, allow) == ()
    assert any('missing:' in problem for problem in settings_problems({'permissions': {'allow': []}}, allow))


def test_a_hand_written_row_nobody_argued_for_is_the_other_side() -> None:
    """A ratchet has two sides: an undeclared row on disk reds as loudly as a missing derived one."""
    allow = AllowAdoption('consumer_a', CONSUMER_A)
    disk = {'permissions': {'allow': [*allow_entries(allow), 'Bash(*scripts/gate/stop_sweep.py *)']}}
    assert any('undeclared:' in problem for problem in settings_problems(disk, allow))


def test_the_section_merge_keeps_every_block_it_is_not_about() -> None:
    """`hooks` belongs to agent_guard and `deny` to whoever wrote it; a JSON section is not a file."""
    before = {
        'permissions': {'allow': ['Bash(*scripts/gate/stop_sweep.py *)', 'Read(**)'], 'deny': ['Bash(rm -rf *)']},
        'hooks': {'PreToolUse': [{'matcher': 'Bash'}]},
        'enabledPlugins': ['rem'],
    }
    after = permissions_block(before, AllowAdoption('consumer_a', CONSUMER_A))
    assert after['hooks'] == before['hooks']
    assert after['enabledPlugins'] == ['rem']
    assert after['permissions']['deny'] == ['Bash(rm -rf *)']
    assert after['permissions']['allow'] == [
        'Read(**)',
        'Bash(.venv/*/python* scripts/gate/stop_sweep.py --pid *)',
        INTERPRETER_ALLOW_ENTRY,
        *claude_rows(),
    ]
    assert live_bash_rows(before) == ('Bash(*scripts/gate/stop_sweep.py *)',)


def test_a_declared_road_may_not_name_a_file_the_tree_lacks() -> None:
    """The `needs` rule pointed the other way, planted on both sides of the tracked set."""
    allow = AllowAdoption(
        'consumer_b',
        CONSUMER_B,
        (DeclaredAllow('Bash(node **/scripts/post-review.js*)', 'the review poster', needs='scripts/post-review.js'),),
    )
    assert allow_gaps(allow, ['scripts/post-review.js']) == ()
    assert len(allow_gaps(allow, ['scripts/other.js'])) == 1


def test_the_block_is_bound_on_both_sides_and_neither_number_has_a_default() -> None:
    """A block that silently emptied reads as agreement; a floor it outgrew is a waiver nothing uses."""
    allow = AllowAdoption('consumer_b', CONSUMER_B, (DeclaredAllow('Bash(*yarn preview*)', 'the docs preview server'),))
    doors = len(claude_rows())
    assert len(allow_entries(allow)) == 4 + doors
    assert_allow_is_adoptable(allow, [], floor=2 + doors, headroom=2)
    with pytest.raises(FloorUnmet):
        assert_allow_is_adoptable(allow, [], floor=9 + doors, headroom=2)
    with pytest.raises(SlackFloor):
        assert_allow_is_adoptable(allow, [], floor=1 + doors, headroom=1)
    with pytest.raises(FloorMisdeclared):
        assert_allow_is_adoptable(allow, [], floor=2, headroom=0)


def test_an_adoption_with_no_app_name_cannot_report_which_repo_failed() -> None:
    """The repo-shaped fact arrives as an argument, and a blank one is refused at construction."""
    with pytest.raises(ValueError, match='app_name'):
        AllowAdoption('  ', CONSUMER_C)


def test_a_declared_row_may_not_spell_the_venv_interpreter_either() -> None:
    """THE DOOR `glob_for` CANNOT REACH, and it is live in a consuming repo today.

    A DERIVED row is normalised on the way out. A DECLARED row is the repo's own text, VERBATIM, so
    nothing normalises it -- and consumer-c's tracked settings file carries
    `Bash(./.venv/Scripts/python.exe scripts/dep.py *)`, which permits nothing at all on macOS. The
    refusal is at CONSTRUCTION rather than in a scan, because that is where the row is authored and
    where the repair costs one character.
    """
    with pytest.raises(UnarguedAllow, match='rather than globbing it'):
        DeclaredAllow('Bash(./.venv/Scripts/python.exe scripts/dep.py *)', 'the dependency door')


def test_the_refusal_names_the_row_the_author_should_have_written() -> None:
    """A refusal that names no remedy has named nothing -- the repair is quoted, not described."""
    with pytest.raises(UnarguedAllow, match=r'Write Bash\(\./\.venv/\*/python\* scripts/dep\.py \*\)'):
        DeclaredAllow('Bash(./.venv/Scripts/python.exe scripts/dep.py *)', 'the dependency door')


def test_a_portable_declared_row_and_an_unrelated_one_both_pass() -> None:
    """THE OTHER SIDE: a guard that refused every declared row would be switched off by lunchtime."""
    assert DeclaredAllow('Bash(./.venv/*/python* scripts/dep.py *)', 'the door').entry.endswith('*)')
    assert DeclaredAllow('Bash(*yarn preview*)', 'the docs preview server').entry == 'Bash(*yarn preview*)'


def test_the_family_doors_ride_every_block_and_a_declared_copy_is_refused() -> None:
    """AUTO-MODE-RUNS-THE-DOORS: each door row is in the block, script doors included, never restated."""
    allow = AllowAdoption('consumer_c', CONSUMER_C, scripts=('scripts/gate/runner.py',))
    entries = allow_entries(allow)
    assert set(claude_rows(('scripts/gate/runner.py',))) <= set(entries)
    assert 'Bash(.venv/Scripts/python.exe scripts/gate/runner.py *)' in entries
    assert provenance(allow)['Bash(.venv/*/python* -m lab_commons.dev.stoprun *)'].startswith('family door')
    door = DeclaredAllow('Bash(.venv/*/python* -m lab_commons.dev.stoprun *)', 'a restated door')
    with pytest.raises(UnarguedAllow):
        AllowAdoption('consumer_c', CONSUMER_C, (door,))
