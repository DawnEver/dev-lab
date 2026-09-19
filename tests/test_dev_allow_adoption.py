"""THE ALLOW HALF, and every arm here is a control in one of the two directions.

A generator with no control that a MISSING row is caught is the vacuous-scan defect wearing a new
hat: it would render a block, compare it to itself, and report agreement. So the planted rows come
in pairs -- one the mechanism must find, one it must not -- and the rows that are REAL are the nine
measured live on 2026-09-18 across the three consuming repos, quoted here as the derivation's own
evidence rather than as fixtures invented to agree with it.
"""

from __future__ import annotations

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
from lab_commons.dev.floors import FloorMisdeclared, FloorUnmet, SlackFloor
from lab_commons.dev.hook_adoption import HookAdoption
from lab_commons.dev.hooks import Remedy
from lab_commons.dev.venvpath import VENV_LAYOUTS, venv_interpreter

#: The verdict entry point BOTH labs hand-wrote, character for character, in their own settings
#: files AND in their own `scripts/deny_rules.py`. The agreement is the evidence for `glob_for`.
VERIFY = Remedy('verdict-entry-point', './.venv/Scripts/python.exe -m lab_commons.dev.verify')

#: wdg-lab's network remedy. It SPELLS the shape its own rule matches, so it carries an opening --
#: the one case `self_refused` exists for.
NETVERB = Remedy(
    'retry-wrapper',
    './.venv/Scripts/python.exe -m lab_commons.dev.netverb -- <verb>',
    allow=r'lab_commons\.dev\.netverb\b',
)

#: motronics' process-tree killer, as its own `deny-rules.json` reason spells the command.
SWEEP = Remedy('process-tree-killer', '.venv/Scripts/python.exe scripts/gate/stop_sweep.py --pid <root-pid>')

OPTIMI = HookAdoption(
    app_name='optimi_lab',
    remedies={'BARE-TEST-INVOCATION': VERIFY, 'PUSH-NO-VERIFY': VERIFY},
    declared_absent=frozenset({'GIT-NETWORK-VERB', 'RAW-PROCESS-KILL'}),
)
WDG = HookAdoption(
    app_name='wdg_lab',
    remedies={'BARE-TEST-INVOCATION': VERIFY, 'PUSH-NO-VERIFY': VERIFY, 'GIT-NETWORK-VERB': NETVERB},
    declared_absent=frozenset({'RAW-PROCESS-KILL'}),
)
MOTRONICS = HookAdoption(
    app_name='motronics_studio',
    remedies={'RAW-PROCESS-KILL': SWEEP},
    declared_absent=frozenset({'BARE-TEST-INVOCATION', 'PUSH-NO-VERIFY', 'GIT-NETWORK-VERB'}),
)


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
    assert derived_entries(OPTIMI) == {
        'Bash(./.venv/*/python* -m lab_commons.dev.verify *)': ('BARE-TEST-INVOCATION', 'PUSH-NO-VERIFY'),
    }


def test_a_rule_declared_absent_derives_no_row() -> None:
    """THE `needs` RULE ON THIS SIDE: optimi-lab has no process-tree killer, so it promises none."""
    assert not any('stop_sweep' in entry for entry in derived_entries(OPTIMI))
    assert 'Bash(.venv/*/python* scripts/gate/stop_sweep.py --pid *)' in derived_entries(MOTRONICS)


def test_a_needs_none_rule_is_never_derived_from() -> None:
    """GIT-STASH, PUSH-FORCE and WORKTREE-BASE-IS-EXPLICIT have PROSE exits, so nothing is guessed."""
    assert set(derived_entries(WDG)) == {
        'Bash(./.venv/*/python* -m lab_commons.dev.verify *)',
        'Bash(./.venv/*/python* -m lab_commons.dev.netverb -- *)',
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
            app_name='wdg_lab',
            adoption=OPTIMI,
            declared=(DeclaredAllow('Bash(./.venv/*/python* -m lab_commons.dev.verify *)', 'the verdict'),),
        )


def test_provenance_says_which_population_each_row_came_from() -> None:
    """Derived and declared are different repairs, so they are never merged into one flat list."""
    allow = AllowAdoption('wdg_lab', WDG, (DeclaredAllow('Bash(*yarn preview*)', 'the docs preview server'),))
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
    """Motronics' adoption with one substituted process-tree remedy, so the plant is the only change."""
    return HookAdoption(
        app_name='motronics_studio',
        remedies={'RAW-PROCESS-KILL': remedy},
        declared_absent=frozenset({'BARE-TEST-INVOCATION', 'PUSH-NO-VERIFY', 'GIT-NETWORK-VERB'}),
    )


def test_a_remedy_spelling_its_own_rules_shape_is_caught_where_this_half_can_see_it() -> None:
    """BOTH DIRECTIONS: the real remedies are clean, the planted one reds, the wrong opening does not."""
    assert self_refused(AllowAdoption('wdg_lab', WDG)) == ()
    assert self_refused(AllowAdoption('motronics_studio', MOTRONICS)) == ()
    caught = self_refused(AllowAdoption('motronics_studio', _killer(BLIND_KILL)))
    assert any('RAW-PROCESS-KILL refuses' in problem for problem in caught), caught
    assert self_refused(AllowAdoption('motronics_studio', _killer(MISDIRECTED_KILL))) == caught


def test_a_missing_derived_row_is_the_finding_and_a_clean_block_is_not() -> None:
    """THE 2026-09-18 INCIDENT ITSELF, planted in both directions over the same adoption."""
    allow = AllowAdoption('motronics_studio', MOTRONICS)
    rendered = {'permissions': {'allow': list(allow_entries(allow))}}
    assert settings_problems(rendered, allow) == ()
    assert any('missing:' in problem for problem in settings_problems({'permissions': {'allow': []}}, allow))


def test_a_hand_written_row_nobody_argued_for_is_the_other_side() -> None:
    """A ratchet has two sides: an undeclared row on disk reds as loudly as a missing derived one."""
    allow = AllowAdoption('motronics_studio', MOTRONICS)
    disk = {'permissions': {'allow': [*allow_entries(allow), 'Bash(*scripts/gate/stop_sweep.py *)']}}
    assert any('undeclared:' in problem for problem in settings_problems(disk, allow))


def test_the_section_merge_keeps_every_block_it_is_not_about() -> None:
    """`hooks` belongs to agent_guard and `deny` to whoever wrote it; a JSON section is not a file."""
    before = {
        'permissions': {'allow': ['Bash(*scripts/gate/stop_sweep.py *)', 'Read(**)'], 'deny': ['Bash(rm -rf *)']},
        'hooks': {'PreToolUse': [{'matcher': 'Bash'}]},
        'enabledPlugins': ['rem'],
    }
    after = permissions_block(before, AllowAdoption('motronics_studio', MOTRONICS))
    assert after['hooks'] == before['hooks']
    assert after['enabledPlugins'] == ['rem']
    assert after['permissions']['deny'] == ['Bash(rm -rf *)']
    assert after['permissions']['allow'] == [
        'Read(**)',
        'Bash(.venv/*/python* scripts/gate/stop_sweep.py --pid *)',
    ]
    assert live_bash_rows(before) == ('Bash(*scripts/gate/stop_sweep.py *)',)


def test_a_declared_road_may_not_name_a_file_the_tree_lacks() -> None:
    """The `needs` rule pointed the other way, planted on both sides of the tracked set."""
    allow = AllowAdoption(
        'wdg_lab',
        WDG,
        (DeclaredAllow('Bash(node **/scripts/post-review.js*)', 'the review poster', needs='scripts/post-review.js'),),
    )
    assert allow_gaps(allow, ['scripts/post-review.js']) == ()
    assert len(allow_gaps(allow, ['scripts/other.js'])) == 1


def test_the_block_is_bound_on_both_sides_and_neither_number_has_a_default() -> None:
    """A block that silently emptied reads as agreement; a floor it outgrew is a waiver nothing uses."""
    allow = AllowAdoption('wdg_lab', WDG, (DeclaredAllow('Bash(*yarn preview*)', 'the docs preview server'),))
    assert len(allow_entries(allow)) == 3
    assert_allow_is_adoptable(allow, [], floor=2, headroom=2)
    with pytest.raises(FloorUnmet):
        assert_allow_is_adoptable(allow, [], floor=9, headroom=2)
    with pytest.raises(SlackFloor):
        assert_allow_is_adoptable(allow, [], floor=1, headroom=1)
    with pytest.raises(FloorMisdeclared):
        assert_allow_is_adoptable(allow, [], floor=2, headroom=0)


def test_an_adoption_with_no_app_name_cannot_report_which_repo_failed() -> None:
    """The repo-shaped fact arrives as an argument, and a blank one is refused at construction."""
    with pytest.raises(ValueError, match='app_name'):
        AllowAdoption('  ', OPTIMI)


def test_a_declared_row_may_not_spell_the_venv_interpreter_either() -> None:
    """THE DOOR `glob_for` CANNOT REACH, and it is live in a consuming repo today.

    A DERIVED row is normalised on the way out. A DECLARED row is the repo's own text, VERBATIM, so
    nothing normalises it -- and optimi-lab's tracked settings file carries
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
