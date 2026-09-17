"""``lab_commons.dev.famtests.allowguard`` -- driven through the REAL engine, on REAL fixture repos.

WHY THE REAL ENGINE. The subject is whether two hand-written files AGREE, and the only thing that can
answer that is the thing that arbitrates them at runtime. An allow GLOB compared against a deny REGEX
by eye is exactly the reasoning this shared body replaces with a measurement, so every case here
renders a real ``deny-rules.json`` from the real registry, installs the real engine with
:func:`lab_commons.dev.agent_guard.install_guard`, and lets ``node`` decide.

NODE IS ASSERTED AT MODULE SCOPE RATHER THAN SKIPPED, for the reason
:class:`lab_commons.dev.agenthooks.NoNode` gives: the hook entry starts with ``node``, so a box
without one runs NO guard in every repo on it. Reporting that as a skip is reporting silence.

BOTH DIRECTIONS ARE PLANTED EVERYWHERE, because every assertion here can be satisfied by an
instrument that stopped working: a contradiction that must be SEEN sits beside a harmless row that
must NOT be reported, an unwired repo sits beside a wired one, and the vacuous scan -- a settings
file with no Bash row at all -- is driven as its own case rather than assumed impossible.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lab_commons.dev import agenthooks
from lab_commons.dev.agent_guard import RULES_REL, SETTINGS_REL, install_guard
from lab_commons.dev.famtests.allowguard import (
    GLOB_CASES,
    Scan,
    UnreadableSettings,
    VacuousAllowScan,
    allow_entries,
    assert_no_allow_contradicts,
    assert_the_scan_can_still_see,
    contradictions,
    probe_command,
)
from lab_commons.dev.hook_adoption import HookAdoption, render
from lab_commons.dev.hooks import Remedy

# ASSERTED, NOT SKIPPED: see the module docstring.
NODE = agenthooks.node_executable()

#: An adoption remedying every rule that needs a repo artefact, so the rendered file carries the whole
#: registry and a probe drawn from it is judged against all of it rather than against a subset.
ADOPTION = HookAdoption(
    app_name='lab-commons (famtests suite)',
    remedies={
        'BARE-TEST-INVOCATION': Remedy('verdict-entry-point', '.venv/Scripts/python.exe -m lab_commons.dev.verify'),
        'PUSH-NO-VERIFY': Remedy('verdict-entry-point', '.venv/Scripts/python.exe -m lab_commons.dev.verify'),
        'GIT-NETWORK-VERB': Remedy('retry-wrapper', 'sh {root}/scripts/hooks/with-retry.sh push'),
        'RAW-PROCESS-KILL': Remedy('process-tree-killer', '.venv/Scripts/python.exe -m lab_commons.dev.stop --pid N'),
    },
)

#: The entry every case below leans on, and it is a repo fact WHEREVER THIS IS USED -- whether a bare
#: test line is refused depends on the rows that repo could honestly ship. Here it is the fixture's
#: own answer, which is why the fixture renders the whole registry above.
DENIED_ENTRY = 'Bash(pytest *)'

#: Its counterweight. Without a row that must NOT be reported, a matcher that refused everything would
#: pass every arm in this file.
HARMLESS_ENTRY = 'Bash(echo *)'

#: The sanctioned exit a red points at. One repo's answer; spelled here because this fixture is a repo.
SANCTIONED = './.venv/Scripts/python.exe -m lab_commons.dev.verify'


def _write_settings(repo: Path, allow: list[str]) -> Path:
    """Merge an ``allow`` block into the repo's REAL settings file, leaving the wiring alone."""
    path = repo / SETTINGS_REL
    doc = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    doc.setdefault('permissions', {})['allow'] = allow
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + '\n', encoding='utf-8')
    return path


def _guarded_repo(root: Path, allow: list[str]) -> Path:
    """A REAL repository with the real engine installed, real wiring, and real rendered rules."""
    root.mkdir(parents=True, exist_ok=True)
    install_guard(root)
    (root / RULES_REL).write_text(render(ADOPTION), encoding='utf-8')
    _write_settings(root, allow)
    return root


@pytest.fixture
def clean(tmp_path: Path) -> Path:
    """A guarded repo whose allow list promises nothing the engine refuses."""
    return _guarded_repo(tmp_path / 'clean', [HARMLESS_ENTRY, 'Read(**)'])


@pytest.fixture
def contradictory(tmp_path: Path) -> Path:
    """The same repo with ONE row that promises a road the engine refuses."""
    return _guarded_repo(tmp_path / 'lying', [HARMLESS_ENTRY, DENIED_ENTRY])


# --------------------------------------------------------------------------------------------
# the instantiation, which is the only step between the two files


@pytest.mark.parametrize(('entry', 'expected'), GLOB_CASES)
def test_a_glob_is_instantiated_at_a_command_position(entry: str, expected: str | None) -> None:
    """PINNED RATHER THAN TRUSTED: the whole comparison rests on what a glob is turned into."""
    assert probe_command(entry) == expected


def test_the_case_table_carries_both_a_bash_row_and_a_non_bash_one() -> None:
    """A table of only-Bash rows would let a probe that never returns ``None`` pass unnoticed."""
    answers = {probe_command(entry) for entry, _ in GLOB_CASES}
    assert None in answers, GLOB_CASES
    assert len(answers - {None}) >= 2, GLOB_CASES


def test_a_trailing_star_is_dropped_and_an_interior_one_becomes_one_word() -> None:
    """The two readings are different, and conflating them changes what the engine is asked."""
    assert probe_command('Bash(git push *)') == 'git push'
    assert probe_command('Bash(python *tool.py*)') == 'python ARG tool.py'
    assert probe_command('Read(**)') is None
    assert probe_command('   Bash(  pytest   -q  )  ') == 'pytest -q'


# --------------------------------------------------------------------------------------------
# reading the declaration


def test_the_allow_rows_are_read_off_the_real_file(clean: Path) -> None:
    """Read from the file on disk, never from the list the test also wrote into a variable."""
    assert allow_entries(clean / SETTINGS_REL) == ('Bash(echo *)', 'Read(**)')


def test_an_absent_or_unreadable_settings_file_refuses_rather_than_reading_empty(tmp_path: Path) -> None:
    """AN EMPTY ANSWER IS THE FAILURE MODE HERE: no rows means no contradictions means green."""
    with pytest.raises(UnreadableSettings, match='does not exist'):
        allow_entries(tmp_path / 'nothing.json')
    broken = tmp_path / 'broken.json'
    broken.write_text('{not json', encoding='utf-8')
    with pytest.raises(UnreadableSettings, match='unreadable'):
        allow_entries(broken)


def test_a_settings_file_with_no_permissions_block_reads_as_no_rows_and_not_as_an_error(tmp_path: Path) -> None:
    """A repo that declares no permissions is READABLE and has nothing to promise; that is data."""
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'hooks': {}}), encoding='utf-8')
    assert allow_entries(path) == ()


# --------------------------------------------------------------------------------------------
# the scan, and what it reports about itself


def test_the_scan_reports_what_it_probed_as_well_as_what_it_refused(contradictory: Path) -> None:
    """FINDING NOTHING AND SEARCHING FOR NOTHING MUST BE DISTINGUISHABLE, so the scan carries both."""
    scan = contradictions(contradictory / SETTINGS_REL, contradictory / RULES_REL, cwd=contradictory)
    assert isinstance(scan, Scan)
    assert set(scan.probed) == {HARMLESS_ENTRY, DENIED_ENTRY}, scan
    assert set(scan.refused) == {DENIED_ENTRY}, scan
    assert 'lab_commons.dev.verify' in scan.refused[DENIED_ENTRY], scan.refused


def test_a_clean_allow_list_refuses_nothing_and_still_reports_what_it_probed(clean: Path) -> None:
    """THE GREEN ARM. Without it every assertion here is satisfied by a scan that refuses nothing."""
    scan = contradictions(clean / SETTINGS_REL, clean / RULES_REL, cwd=clean)
    assert scan.refused == {}
    assert scan.probed == (HARMLESS_ENTRY,), scan


def test_a_scan_that_probed_nothing_is_vacuous_and_says_so(tmp_path: Path) -> None:
    """THE FLOOR. Zero Bash rows gives zero contradictions, which is not the same fact as agreement."""
    repo = _guarded_repo(tmp_path / 'silent', ['Read(**)', 'WebFetch(*)'])
    scan = contradictions(repo / SETTINGS_REL, repo / RULES_REL, cwd=repo)
    assert scan.probed == ()
    assert scan.vacuous
    with pytest.raises(VacuousAllowScan, match='no `Bash'):
        assert_no_allow_contradicts(root=repo, sanctioned=SANCTIONED)


# --------------------------------------------------------------------------------------------
# the assertion a consumer calls


def test_the_assertion_passes_on_a_repo_whose_two_files_agree(clean: Path) -> None:
    """The property, driven on a real tree: green means the allow list promises nothing refused."""
    assert_no_allow_contradicts(root=clean, sanctioned=SANCTIONED)


def test_the_assertion_reds_on_a_planted_contradiction_and_names_the_remedy(contradictory: Path) -> None:
    """A red must carry the row, what it promised, and the sanctioned spelling to redirect it to."""
    with pytest.raises(AssertionError) as caught:
        assert_no_allow_contradicts(root=contradictory, sanctioned=SANCTIONED)
    message = str(caught.value)
    assert DENIED_ENTRY in message
    assert 'pytest' in message
    assert SANCTIONED in message, 'a red that does not name the exit leaves deletion as the easy repair'


def test_an_unwired_repository_refuses_instead_of_reporting_agreement(tmp_path: Path) -> None:
    """THE IMPROVEMENT OVER ALL THREE FORKED COPIES, and it is delegated rather than re-walked.

    Each repo's own version hand-walked ``hooks.PreToolUse`` looking for the rules filename, which
    answers ABSENT and STALE identically. :func:`lab_commons.dev.agent_guard.guard_installation`
    already tells those apart, so the floor asks IT -- a settings file whose wiring runs the engine
    with other arguments is a different finding from one that does not run it at all, and collapsing
    them sends a reader to the wrong repair.
    """
    repo = tmp_path / 'unwired'
    (repo / '.claude' / 'hooks').mkdir(parents=True)
    (repo / RULES_REL).write_text(render(ADOPTION), encoding='utf-8')
    (repo / SETTINGS_REL).write_text(json.dumps({'permissions': {'allow': [DENIED_ENTRY]}}), encoding='utf-8')
    with pytest.raises(AssertionError, match='wiring'):
        assert_no_allow_contradicts(root=repo, sanctioned=SANCTIONED)


def test_a_missing_rules_file_refuses_rather_than_finding_no_contradiction(tmp_path: Path) -> None:
    """With no registry to contradict, every allow row is trivially honest and nothing was measured."""
    repo = _guarded_repo(tmp_path / 'ruleless', [DENIED_ENTRY])
    (repo / RULES_REL).unlink()
    with pytest.raises(AssertionError, match='rules'):
        assert_no_allow_contradicts(root=repo, sanctioned=SANCTIONED)


def test_the_sanctioned_exit_is_required_and_has_no_default() -> None:
    """NO DEFAULT. The verdict command is one repo's answer, and a guessed one points at nothing."""
    with pytest.raises(TypeError, match='sanctioned'):
        assert_no_allow_contradicts(root=Path())


# --------------------------------------------------------------------------------------------
# the instrument's own floor


def test_the_instrument_check_sees_a_planted_row_and_spares_a_harmless_one(clean: Path, tmp_path: Path) -> None:
    """THE PLANT, as a callable the consumer runs: it proves the engine still refuses ANYTHING.

    Without it this whole body passes equally well against an engine that stopped matching, which is
    the state in which every real allow row reads as honest.
    """
    assert_the_scan_can_still_see(
        root=clean,
        denied_entry=DENIED_ENTRY,
        harmless_entry=HARMLESS_ENTRY,
        scratch=tmp_path / 'probe',
    )


def test_the_instrument_check_reds_when_the_denied_row_is_not_refused(clean: Path, tmp_path: Path) -> None:
    """The other direction, driven by handing it a row this fixture's registry does NOT refuse."""
    with pytest.raises(AssertionError, match='UNDETECTED'):
        assert_the_scan_can_still_see(
            root=clean,
            denied_entry=HARMLESS_ENTRY,
            harmless_entry='Bash(ls *)',
            scratch=tmp_path / 'probe2',
        )


def test_the_instrument_check_reds_when_a_harmless_row_is_reported(clean: Path, tmp_path: Path) -> None:
    """And here: a row that IS refused, handed in as the one that must not be, must be caught."""
    with pytest.raises(AssertionError, match='harmless'):
        assert_the_scan_can_still_see(
            root=clean,
            denied_entry=DENIED_ENTRY,
            harmless_entry=DENIED_ENTRY,
            scratch=tmp_path / 'probe3',
        )
