"""WHAT EACH PUBLISHED `lab_commons.dev` MODULE REPLACED, or did not -- DATA, one row per module.

READ AS SOURCE by `lab_commons.dev._provenance.provenance_rows`, never imported, so every value here
is a literal. `undeclared_modules` is the mechanism that makes this file a ratchet rather than a
habit: a published module with no row reds, and a row naming no module reds too.

THREE KINDS, AND ONLY THE FIRST IS A PROVENANCE CLAIM.

* `supersedes` -- this module replaced those consumer files, whole or in part. This is the only kind
  the census's PROVENANCE detector reads.
* `adopted_by` -- the consumer file DELEGATES to this module and stays. Recorded because the
  distinction is exactly what a docstring cannot make: prose that names a file names it for both
  reasons at once, which is how `verify`'s mention of `scripts/gate/runner.py` (carved FROM, 0 of 51
  names shared) became the false positive that `named_only` exists to hold.
* `original` -- no consumer fork behind it. It is a DECLARATION, refusable by a reader: `forge` is
  the row to look at first, because motronics-studio's `scripts/repo/forge_protect.py` shares `Forge`
  and `token_for` with it, and three tranches still read that file BY HAND as still local. Overlap is
  not provenance here for the same reason it is not a detector next door.

A CONSUMER PATH IS SPELLED AS THE CONSUMER SPELLS IT, repo-relative. Matching is by suffix, so a
basename reaches the row without a repo name in front of it -- and a repo name in front of it would
be one repo's answer in a file three repos read.
"""

from __future__ import annotations

from typing import Final

__all__ = ['PROVENANCE']

PROVENANCE: Final[dict[str, tuple[str, ...]]] = {
    'ab_bench': ('original',),
    'agent_guard': ('original',),
    'bounded': (
        'supersedes',
        'scripts/gate/bounded.py',
        'scripts/gate/_box.py',
        'scripts/gate/wall_reason.py',
        'scripts/gate/width.py',
    ),
    'boxlock': ('original',),
    'boxwait': ('original',),
    'bypath': ('supersedes', 'scripts/gate/_by_path.py'),
    'checkout': (
        'supersedes',
        'scripts/lanes/prune_origin_branches.py',
        'scripts/lanes/session_branches.py',
        'scripts/repo/worktree_debris.py',
    ),
    'cjk': ('original',),
    'content': ('original',),
    'datedlog': ('supersedes', 'scripts/gate/_dated.py'),
    'dep': ('supersedes', 'scripts/gate/native_install.py'),
    'devdocs': ('original',),
    # THREE implementations existed -- motronics `scripts/repo/docs.py`, wdg-lab `scripts/docs.py`,
    # optimi-lab `scripts/pdoc`. The table stayed with each repo, so this is adoption, not a move.
    'docsite': ('adopted_by', 'scripts/repo/docs.py'),
    'docwidth': ('original',),
    'envkey': ('original',),
    'famconfig': ('original',),
    # See the module docstring above: declared original against a measured 2-name overlap.
    'forge': ('original',),
    'gatebase': ('supersedes', 'scripts/gate/base.py'),
    'hook_adoption': ('supersedes', 'scripts/repo/write_deny_rules.py'),
    'hook_install': ('supersedes', 'scripts/repo/_hooks.py'),
    # `scripts/hooks/with-retry.sh` is a REMEDY that resolves in one checkout on earth, which is why
    # `hooks` holds the statements and `hook_adoption` holds the pointer. Neither replaced it.
    'hooks': ('original',),
    'installdoor': ('original',),
    'logref': ('original',),
    # Both named by `netverb`'s docstring as the vacuum it closes, and both ADOPTED it on 2026-09-17
    # while staying: wdg-lab's roster carries one as SPLITS and the other as STAYS.
    'netverb': ('adopted_by', 'scripts/pull_all.py', 'scripts/wdg-lab-update.sh'),
    'profile': ('original',),
    'quantity_values': ('original',),
    'reports': ('original',),
    'rules': ('original',),
    'seams': ('supersedes', 'scripts/gate/seam_install.py'),
    'selfbuild': ('supersedes', 'scripts/gate/native_install.py'),
    'shadow_build': ('supersedes', 'scripts/gate/native_ab.py'),
    'shards': ('supersedes', 'scripts/gate/_shards.py'),
    'supersede': ('original',),
    'symcov': ('supersedes', 'scripts/repo/_symbol_coverage.py'),
    'testfacts': ('original',),
    'treedirt': ('supersedes', 'scripts/gate/tree_state.py'),
    'units': ('original',),
    'verdict': ('original',),
    # `scripts/gate/runner.py` is the tree this was CARVED FROM and it stayed: it shares 0 of its 51
    # names with this module. Naming it `supersedes` is the mistake this kind exists to refuse.
    'verify': ('adopted_by', 'scripts/gate/runner.py'),
    # -- `lab_commons.dev.famtests`, the shared assertion bodies. Each replaces a consumer's whole
    #    test file, which is the class of row that has no import to be found by: a test file that
    #    has not adopted the body yet imports nothing from the kit at all.
    'agentguard': ('supersedes', 'tests/architecture/test_the_agent_guard_is_live.py'),
    'allowguard': ('supersedes', 'tests/architecture/test_no_allow_entry_names_a_denied_shape.py'),
    'configrender': ('supersedes', 'tests/architecture/test_the_family_config_is_rendered.py'),
    'hookinstall': ('supersedes', 'tests/architecture/test_the_declared_hooks_are_installed.py'),
    'rostercensus': ('supersedes', 'tests/architecture/test_the_roster_is_re_read_against_the_kit.py'),
    'rulespages': (
        'supersedes',
        'tests/architecture/test_the_rules_pages_are_a_ratchet.py',
        'tests/architecture/ratchets/test_rules_line_ratchet.py',
    ),
    'visibility': ('supersedes', 'tests/architecture/test_this_checkout_is_visible_on_origin.py'),
    # -- `lab_commons.dev.githooks`.
    'bootstrap': ('supersedes', 'scripts/hooks/with-venv.sh'),
}
