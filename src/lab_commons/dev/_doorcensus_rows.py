"""THE INSTALL-DOOR CENSUS, pure DATA -- one row per repo per door, plus what was DECLINED.

The machinery is `doorcensus.py` and the seam is the one `test_arch_registry_data_is_separate.py`
names for `_rule_rows.py`: a table edited through the module that checks it drifts away from what it
describes, because the same edit that adds a row can relax the check that would have refused it and
the diff looks like one change. Nothing here computes; the readers are all one module over.

MEASURED 2026-09-19 against four checkouts, at the commits named below, with the classifier in
`installdoor.py` -- whose own docstring holds the tool versions and the venv-level measurements the
classification table was built from. Every number here is re-derived by `assert_census`, so a row
that stops being true REDS rather than ageing quietly into prose. That is not decorative: two prose
counts in this family were wrong for two days at the moment this file was written, and both sat
above a floor that could not see them.

THE READ IS AT ``HEAD``. Working-tree numbers were identical in all four repos on the day, and the
committed read is still the one that ships -- a sibling lane's half-finished edit must not be able
to turn this repo red for a change that exists in no commit.

  repo              HEAD       floating requirements declared
  ----------------  ---------  ------------------------------------------
  lab-commons       73c13e0    () -- it IS the kit
  wdg-lab           2c0b5f2c   ('lab-commons',)
  optimi-lab        6753e31    ('lab-commons',)
  motronics-studio  899778231  ('lab-commons', 'optimi-lab', 'wdg-lab')
"""

from __future__ import annotations

from lab_commons.dev.doorcensus import Declined, DoorRow, SharedDoor

__all__ = [
    'DECLINED',
    'DOORS',
    'DOOR_FLOOR',
    'REPO_FLOOR',
    'SHARED',
]

#: One row per repo per door file. ``commands`` and ``deliveries`` are compared by EQUALITY, never as
#: a floor: a floor is ``declared <= live`` and is satisfied by every shorter declaration, which is
#: exactly how ``lab-commons`` recorded 9 while delivering 16 and ``wdg-lab`` recorded 28 while
#: delivering 30, both green.
DOORS: tuple[DoorRow, ...] = (
    DoorRow(
        repo='lab-commons',
        path='Makefile',
        commands=13,
        deliveries=frozenset({'INERT'}),
        why=(
            'The kit declares no floating requirement -- it IS the kit -- so every command here is '
            'INERT by the SUBJECT being absent rather than by the commands being safe. This row is '
            'the one that acquires teeth on the day a bare `git+` requirement lands in this '
            'manifest, which is why the guard is pointed here rather than waived: a waiver would '
            'have had to be noticed and removed by hand.'
        ),
    ),
    DoorRow(
        repo='lab-commons',
        path='.github/workflows/ci.yml',
        commands=0,
        deliveries=frozenset(),
        why=(
            'ZERO IS THE MEASUREMENT, not a miss. This file is a thin caller: its only job is `uses: '
            './.github/workflows/python-verify.yml`, and every command of substance is in that '
            'reusable workflow. A repo-level floor cannot tell a file that legitimately holds no '
            'command from a file the scan stopped reading, and this row is where that distinction '
            'is recorded -- if a `run:` step is ever inlined here, the count moves and this reds.'
        ),
    ),
    DoorRow(
        repo='lab-commons',
        path='.github/workflows/python-verify.yml',
        commands=3,
        deliveries=frozenset({'INERT'}),
        why=(
            'THE ROW THAT LIES WHEN READ ALONE, and the SHARED entry below is its other half. All '
            'three commands here consume a lock, and they read INERT only because this repo declares '
            'no floating requirement. This workflow RUNS in every caller checkout, where the kit IS '
            'floating -- so the honest classification is the SharedDoor row, and this one exists to '
            'pin that the file still holds exactly those three commands.'
        ),
    ),
    DoorRow(
        repo='wdg-lab',
        path='Makefile',
        commands=16,
        deliveries=frozenset({'INERT', 'RESOLVES'}),
        why=(
            'The door everybody suspected of the three reverts on 2026-09-17 and the one that was '
            'never the defect: it installs through `uv pip install -e .[...]`, which re-resolves a '
            'bare git URL every time and therefore cannot serve a lock. Pinned RESOLVES rather than '
            'left alone, because the one-character change from `uv pip install` to `uv sync` is the '
            'edit a reader makes when a sync looks tidier, and it would revert the kit silently.'
        ),
    ),
    DoorRow(
        repo='wdg-lab',
        path='README.md',
        commands=8,
        deliveries=frozenset({'INERT', 'RESOLVES'}),
        why=(
            'A DOOR WITH A PERSON IN THE MIDDLE. What a README tells a human to type moves an '
            'environment exactly as a Makefile target does, and it is the door with no CI and no '
            'hook to catch it drifting away from the Makefile beside it. Eight commands, two of '
            'which install; a count alone could not say which of the eight changed, so the named '
            'delivery set is pinned with it.'
        ),
    ),
    DoorRow(
        repo='wdg-lab',
        path='.pre-commit-config.yaml',
        commands=3,
        deliveries=frozenset({'INERT'}),
        why=(
            'THE FILE THAT CARRIED THE ORIGINAL DEFECT, now clean. Its pre-push hook was `entry: uv '
            'run python -m lab_commons.dev.githooks bump-version`, whose implicit sync reverted the '
            'kit on every push -- a door nobody had listed as one, found only because the revert '
            'was measured three times in a day. It reads INERT today because the remedy `--no-sync` '
            'was applied; this row is what refuses the flag being dropped again.'
        ),
    ),
    DoorRow(
        repo='wdg-lab',
        path='scripts/githooks/generate-changelog.sh',
        commands=1,
        deliveries=frozenset({'INERT'}),
        why=(
            'The second measured reverting door, and the one that hid inside a shell function body '
            '-- `cmd() { uv run python -m commitizen changelog; }`, which the first cut of the '
            'scanner read as arguments to `cmd()` and found no door in at all. It ran on every '
            'commit. INERT today by the same `--no-sync` remedy, and pinned here so the repair '
            'cannot be undone by a reformat.'
        ),
    ),
    DoorRow(
        repo='wdg-lab',
        path='scripts/wdg-lab-update.sh',
        commands=2,
        deliveries=frozenset({'INERT', 'RESOLVES'}),
        why=(
            'The update script a developer runs by hand, which is precisely the situation where a '
            'reverted kit is blamed on the sibling repo rather than on the command just typed. It '
            'resolves, and it is the only door in this repo outside the Makefile and the README that '
            'does -- so the RESOLVES in this set disappearing means the update path stopped '
            'installing anything at all.'
        ),
    ),
    DoorRow(
        repo='optimi-lab',
        path='Makefile',
        commands=16,
        deliveries=frozenset({'INERT', 'RESOLVES'}),
        why=(
            'Measured correct on 2026-09-17 and changed as a result of nothing, which is a result '
            'rather than a skip: this repo carried the hazard fully loaded -- a floating kit '
            'requirement and an untracked lock sixteen commits behind -- and simply had no door that '
            'fired it. The row keeps that true; the sibling repo that DID revert did it through a '
            'file nobody had listed.'
        ),
    ),
    DoorRow(
        repo='optimi-lab',
        path='README.md',
        commands=6,
        deliveries=frozenset({'INERT', 'RESOLVES'}),
        why=(
            'The human-in-the-middle door again, and six commands here against eight in wdg-lab is '
            'the kind of difference a family-wide count would average away. Pinned per repo per file '
            'for that reason: the census axis is the repo because the repo is what a lane owns, and '
            'a drift has to name the tree it happened in before anyone can go and look.'
        ),
    ),
    DoorRow(
        repo='optimi-lab',
        path='.pre-commit-config.yaml',
        commands=0,
        deliveries=frozenset(),
        why=(
            'ZERO, AND THIS IS THE SIBLING OF THE FILE THAT CARRIED THE DEFECT. wdg-lab reverted the '
            'kit on every push through a hook entry in the file of this exact name; optimi-lab has '
            'no such entry, and that is a measurement worth a row rather than an omission worth '
            'nothing. The day a `uv run` hook is added here, this count moves off zero and the '
            'census says so before the first push does.'
        ),
    ),
    DoorRow(
        repo='optimi-lab',
        path='.github/workflows/ci.yml',
        commands=0,
        deliveries=frozenset(),
        why=(
            'Zero because it is a thin caller of lab-commons` reusable `python-verify.yml`, so this '
            "repo's CI install door physically lives in another repo's tree. That is the single "
            'clearest case for the SHARED table below: judged here the door is invisible, judged at '
            'home it is vacuous, and it is only judged honestly against the names THIS repo '
            'declares.'
        ),
    ),
    DoorRow(
        repo='optimi-lab',
        path='scripts/dep.py',
        commands=0,
        deliveries=frozenset(),
        why=(
            'Zero because this script composes its argv in Python through `lab_commons.dev.dep`, '
            'which spells `sys.executable -m pip install` -- correct by construction, and correct '
            'for a second reason, since pip re-clones a direct URL rather than treating it as '
            'satisfied. Declared as a door with a zero reading rather than left off the list: it '
            'IS a door, and the day it grows a literal `uv sync` the count moves.'
        ),
    ),
    DoorRow(
        repo='motronics-studio',
        path='Makefile',
        commands=15,
        deliveries=frozenset({'INERT'}),
        why=(
            'Fifteen commands and not one of them installs, because this Makefile delegates every '
            'install to `scripts/install/install.py` -- so the file that LOOKS like the install door '
            'holds none, and the real ones are argv builders declined below. A repo whose doors are '
            'all INERT is the reading a text census is most likely to be wrong about, which is why '
            'the declined rows have to name where the real check lives.'
        ),
    ),
    DoorRow(
        repo='motronics-studio',
        path='.pre-commit-config.yaml',
        commands=0,
        deliveries=frozenset(),
        why=(
            'Zero, and DELIBERATELY so: this config routes its hooks through `lab-with-venv` and '
            '`env` entries, and carries a comment saying "Never `uv run` here -- it resolves its own '
            'copy". That is a declaration, and this row is the code that must consult it. The '
            'sibling repo learned the same lesson by measuring three reverts instead of by reading a '
            'comment.'
        ),
    ),
    DoorRow(
        repo='motronics-studio',
        path='scripts/hooks/with-retry.sh',
        commands=2,
        deliveries=frozenset({'INERT'}),
        why=(
            'The network-verb wrapper every push goes through, included because a wrapper that runs '
            'on every remote operation is the highest-traffic path in the repo and the two commands '
            'in it are interpreter probes rather than installs. If this file ever grows an install '
            'retry -- the obvious next feature for a retrying wrapper -- it becomes a door that '
            'fires three times per failure, and the count moves here first.'
        ),
    ),
)

#: Doors DELIBERATELY not text-censused, each naming the mechanism that covers it instead. An omitted
#: door and a considered one look identical in a list of paths; they do not look identical here.
DECLINED: tuple[Declined, ...] = (
    Declined(
        repo='motronics-studio',
        path='scripts/gate/dep_sync.py',
        covered_by='motronics-studio tests/unit/scripts/test_the_install_doors_deliver_the_declared_kit.py',
        why=(
            'THIS REPO`S REAL DOORS ARE ARGV BUILDERS, and a text scan of this file reads four '
            'command-shaped literals while being unable to say which branch composes the argv that '
            'actually runs. The honest mechanism is to CALL `uv_command` and classify what it '
            'returns, which that test does -- including the pre-fix argv as a planted control, so '
            'the bare `uv sync` it replaced cannot come back unnoticed.'
        ),
    ),
    Declined(
        repo='motronics-studio',
        path='scripts/install/install.py',
        covered_by='motronics-studio tests/unit/scripts/test_the_install_doors_deliver_the_declared_kit.py',
        why=(
            'Declined for the same reason and worth naming separately because it is the door that '
            'was SUSPECTED and was never the defect: it spells `uv pip install -e ".[all,dev]"` as a '
            'Python list, so the text census reads zero commands in it while the repo`s own test '
            'pins the exact argv. A fix applied where there is no defect costs the next reader the '
            'reason, so nothing here was changed.'
        ),
    ),
    Declined(
        repo='wdg-lab',
        path='scripts/dep.py',
        covered_by='lab_commons.dev.dep, exercised by tests/test_dev_dep.py',
        why=(
            'Reads zero commands because it delegates to `lab_commons.dev.dep`, which builds '
            '`sys.executable -m pip install` and is tested in this repo. Recorded as declined rather '
            'than simply left out of the list, because optimi-lab DOES list its own `scripts/dep.py` '
            'with a zero reading -- two repos treating the same file differently is exactly the '
            'asymmetry a census exists to make visible instead of inferable.'
        ),
    ),
)

#: A door stored in one repo and RUN in others, classified against the names of the repos that run
#: it. There is one today, and finding it is what this table was added for.
SHARED: tuple[SharedDoor, ...] = (
    SharedDoor(
        repo='lab-commons',
        path='.github/workflows/python-verify.yml',
        ran_by=('optimi-lab', 'wdg-lab'),
        deliveries=frozenset({'INERT', 'REVERTS'}),
        why=(
            'THE FINDING. This reusable workflow holds `uv sync --python X $extra_flags` and two '
            '`uv run make ...` steps, and all three are lock-consuming. Scanned at home against '
            'lab-commons` empty floating set they classify INERT; scanned against a caller`s '
            '(`lab-commons`) they are REVERTS, and no caller could see the file because it is not in '
            'its tree. Two of the three were remedied with `--no-sync`, which is also the correct '
            'fix on its own terms: `uv run` with no `--extra` re-syncs WITHOUT the extras the '
            'preceding step just installed, and that is the prune shape measured taking one '
            'environment from 113 distributions to 30. The remaining `uv sync` is survivable only '
            'because no `uv.lock` is ever checked out, which `assert_no_tracked_lock` asserts rather '
            'than assumes.'
        ),
    ),
)

#: How few repos this census may reach and still be a verdict. lab-commons is always there; a run
#: that saw only it has measured one tree and proved nothing about the family.
REPO_FLOOR: int = 2

#: How few rows it may read. Under every single repo`s door count, so it catches a census that
#: reached the checkouts and stopped reading them -- not a box holding fewer siblings.
DOOR_FLOOR: int = 6
