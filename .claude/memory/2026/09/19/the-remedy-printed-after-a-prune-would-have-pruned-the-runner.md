---
name: the-remedy-printed-after-a-prune-would-have-pruned-the-runner
description: The install-door census could see which BUILD a command delivers and not which EXTRAS survive it, and the gap is what took one box from 113 distributions to 30. syncscope + synccensus close it by joining a command's selection with the repo's own optional-dependencies table. The finding - motronics' dep_sync prints "re-run naming every extra you need (--extra all where the project declares it)" to an operator mid-incident, and --extra all there is motronics[euclid,maxwell,pareto,femm,gui,native] with no dev, so following the advice removes pytest, pytest-xdist, pytest-timeout and ruff. Also measured - optimi-lab's CI hangs three of its four verdict-critical distributions on one word.
metadata:
  type: project
created: 2026-09-19
accessed: 2026-09-19
---

# The remedy printed after a prune would have pruned the runner

## The gap that was named rather than covered

`_doorcensus_rows.py` says it in its own docstring: *"WHICH EXTRAS SURVIVE. The vocabulary is
delivery, not population: a sync naming `-P` and no `--extra` classifies RESOLVES -- right about the
kit BUILD, blind to the optional distributions it removes."* That is an honest absence, and it is
the whole subject here.

The two questions fail differently, and that is why they are two modules:

* A WRONG BUILD still runs. The tree reports a verdict; the verdict is computed against a stale
  dependency, and every existing mechanism points at that.
* A WRONG POPULATION reports NOTHING. A tree with no pytest cannot say PASS, FAIL or INCONCLUSIVE,
  so the failure reads as a broken TREE and the reader is sent to debug the wrong thing.

## An extras name is a fact about the MANIFEST

This is the whole design constraint. `--extra all` is not a property of the command: in motronics
`all` is `motronics[euclid,maxwell,pareto,femm,gui,native]`, in lab-commons and optimi-lab there is
no such extra at all, and in wdg-lab there is not either. So the reader REFUSES an extras name the
manifest does not declare rather than scoring it as an empty selection, and it EXPANDS a
self-reference, because read literally `all` contains one distribution -- the project.

`[project.optional-dependencies]` is DECLINED as a family base
(`_famconfig_pyproject_rows.PYPROJECT_DECLINED`: it is the dependency graph and per-repo). That
decline is the constraint this works inside and not an obstacle: nothing proposes a shared value,
each repo's own table is read and one portable question is asked of it.

## The findings, all from TEXT -- nothing was installed, synced or pruned

* **motronics `scripts/gate/dep_sync.py:458`**, running code that prints AFTER a prune has removed
  distributions: *"re-run naming every extra you need (`--extra all` where the project declares
  it)"*. That project declares it, and it carries no `dev`: following the advice strands `pytest`,
  `pytest-xdist`, `pytest-timeout` and `ruff`. The remedy for the 2026-09-18 incident is the
  2026-09-18 incident.
* **optimi-lab `.github/workflows/ci.yml:38`**, `extras: 'dev'`. Its `addopts` carries `--cov`, so
  `pytest-cov` is as load-bearing as pytest -- pytest exits 4, no verdict, on an unrecognised
  option -- and it declares `lab-commons` ONLY inside the `dev` extra. Three of its four critical
  distributions hang on that one word.
* **The family has exactly one pruning command in a declared door**, `python-verify.yml:83`, and its
  extras are a workflow input. Every other lock-consuming door takes `--no-sync`.

## A plugin named in a config file is a dependency

The half that is easy to miss: `addopts = "... -n auto ..."` and `timeout = 300` make xdist and
pytest-timeout verdict-critical, because pytest treats an unrecognised option as a USAGE ERROR. So
the verdict set is DERIVED from each repo's own pytest configuration rather than typed out, and it
differs per repo: lab-commons needs 2 distributions, optimi-lab and wdg-lab 4, motronics 5.

## What it cannot see, and the refusals

A test module importing `cv2` from an extra outside `all` still errors at collection and no reading
of a manifest can say so -- `img-to-cad`'s absence scores COMPLETE here, and that is why the answer
is named VERDICT RUNNABILITY rather than environment health. `[dependency-groups]` (which no repo in
the family declares) and a verdict distribution supplied only under an environment marker both
answer UNMEASURED rather than a confident wrong answer. `--no-dev` is about GROUPS and not about a
`dev` EXTRA, and the spelling invites exactly that misreading.
