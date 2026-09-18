"""The ASSERTIONS the family's repos hold in common, as a body each consumer PARAMETRIZES.

WHY A SHARED BODY AND NOT A SHARED FILE. Measured 2026-09-17 across the four repos: the same
architecture test exists three or four times under the same filename, at 83% to 97% identical CODE
with docstrings and comments blanked, and the few lines that differ are each ONE repo's answer -- its
root, its trunk name, the accounts it whitelists, the pre-commit stages it declares. A "shared" test
each repo copies is the fork it claims to remove wearing a new name, and the drift is measurable
today: one repo's copy of the hook-installation guard asserts a SUPERSET where the other two pin the
exact set, which is the count-pin failure in set form, and it has been green in that weaker shape for
as long as it has existed.

A 98% TWIN WITH A REPO NOUN WELDED INTO ITS CODE IS A SEAM, NOT A MOVE. That judgement is not this
package's invention -- it is how the consumers' own rosters judged their copies -- and it decides the
shape here: every repo-shaped fact arrives as a KEYWORD ARGUMENT WITH NO DEFAULT. ``LAB_CZ_BASE_REF``
is the worked example the family already paid for: a guessed ``origin/main`` in a repo whose trunk is
named otherwise resolves to nothing, finds no commits, and REPORTS THE LANE CLEAN. A default is not a
convenience here; it is one repo's answer handed silently to another and then reported as measured.

THE SHAPE IS THE ONE THE KIT ALREADY USES, and it is deliberately not a pytest plugin. ``assert_*``
callables live here -- :func:`~lab_commons.dev.hook_adoption.assert_shippable`,
:func:`~lab_commons.dev.rules.assert_adopted`, :func:`~lab_commons.dev.cjk.assert_cjk_floor` are the
precedent -- beside PURE predicates a consumer can parametrize and assert on directly. The consumer's
file stays a real test module in its own tree, naming its own facts, which is what keeps the
declaration where the repo can see it. A plugin would move the decision out of sight and give a
repo no place to say what its answer is.

A SHARED FILENAME IS NOT SHARED CODE, and the counter-evidence is kept because it is what makes the
rest mean something. ``test_the_public_surface_is_declared.py`` exists under one name in two repos at
89% DIFFERENT, and it is NOT here. A census that only ever finds MOVES is measuring its own
expectation.

``test_memory_lives_under_a_date.py`` WAS THE OTHER HALF OF THAT COUNTER-EXAMPLE AND IS NOW A ROW,
and the correction is recorded rather than quietly removed. It measured 33% identical between the two
labs -- one walks five declared memory trees, the other walks one -- and was read as a repo fact. It
was not: the 67% is the TREE LIST, THE FLOOR AND THE TWO EXCLUSION SETS, four repo-shaped facts, and
the readers underneath them are the same four functions. Passed as arguments with no default they
leave a body that is identical, which is what :mod:`lab_commons.dev.famtests.datedmemory` publishes.
A PERCENTAGE IS A RULER AND NOT A VERDICT -- the same lesson ``supersede`` states about surface
overlap, arriving here through the opposite door: there it over-convicted, here it under-convicted.

WHAT IS HERE, one module per shared body:

* :mod:`lab_commons.dev.famtests.allowguard` -- an agent-hook allow entry may not name a shape the
  deny registry refuses.
* :mod:`lab_commons.dev.famtests.hookinstall` -- the hooks a repo DECLARES are the hooks git has.
* :mod:`lab_commons.dev.famtests.visibility` -- what exists only on this box exists for nobody.
* :mod:`lab_commons.dev.famtests.agentguard` -- the guard is live, and the rule that fires is the
  rule that was meant to.
* :mod:`lab_commons.dev.famtests.configrender` -- the rendered family artefacts equal base + delta.
* :mod:`lab_commons.dev.famtests.rulespages` -- the always-loaded pages, pinned per page AND
  in total, because a named set and a budget are each blind to what the other sees.
* :mod:`lab_commons.dev.famtests.rostercensus` -- a placement roster is re-read against the kit,
  so a row's side cannot go stale after its subject lands upstream.
* :mod:`lab_commons.dev.famtests.datedmemory` -- every memory entry sits under its own date, and
  the entry's own header agrees with it. READERS, not the constructor next door in
  :mod:`lab_commons.dev.datedlog`: a different layout, the opposite refusal, and a floor.

WHOSE COPY A BODY JUDGES IS SAID ONCE, HERE, because it was said twice and differently until
2026-09-17 and the two answers were opposites. A body here judges THE CONSUMER'S OWN FILES -- the
tree it is handed -- and the wheel's copy of anything is only ever the DECLARATION those files are
compared against, never the subject. Audited across all five modules that day: ``hookinstall``,
``visibility`` and ``configrender`` were already clean (each takes a ``root`` or an explicit path,
and ``configrender``'s family BASE is a declaration, which is the allowed direction); ``agentguard``
was right and ``allowguard`` was wrong, driving the engine inside the installed wheel. The subject is
named by a PATH wherever it can differ, and :func:`lab_commons.dev.agenthooks.run_engine` is the one
runner that takes one -- a shipped NAME (:func:`lab_commons.dev.agenthooks.decide`) now reads as the
family question it is. An absent consumer file REFUSES; it never falls back to the wheel's, because a
fall-back reports the family's answer as the repo's at exactly the moment the repo has none. What
made this a defect rather than a tidiness point is that the two copies DRIFT: measured that day, the
engines installed in three repos allowed a shape the shipped one had refused since 2026-08-22, and
they agreed again only because somebody re-installed them.

NOTHING HERE IS RE-EXPORTED FROM :mod:`lab_commons.dev`. Flattened, ``entries``, ``contradictions``
and ``assert_live`` stop saying what they are about, and the import in a consumer's test file is the
one place the subject should be spelled.
"""

from __future__ import annotations

__all__: list[str] = []
