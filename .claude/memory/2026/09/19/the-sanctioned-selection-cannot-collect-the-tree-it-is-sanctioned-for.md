---
name: the-sanctioned-selection-cannot-collect-the-tree-it-is-sanctioned-for
description: syncscope named its own blind spot - whether a test module imports a pruned distribution - and collectscope closes it by joining a repo's TEST TREE to its optional-dependency table. The findings - motronics' SANCTIONED "--extra pareto --extra dev", scored COMPLETE at the runner, strands SEVEN distributions at COLLECTION; wdg-lab's CI "extras dev" strands four; and "--extra all --extra dev --extra img-to-cad", recorded as the incantation that restored the box, STILL strands pillow, declared only in a tooldrivers extra nothing names. Two design moves were forced by measurement - installed metadata is the wrong instrument (22 import names known, None for every interesting case), and an import name maps to a SET of suppliers because motronics declares cadquery-ocp-novtk and opencv-python-headless. One brief claim was refuted - a skip mark is not a guard.
metadata:
  type: project
created: 2026-09-19
accessed: 2026-09-19
---

# The sanctioned selection cannot collect the tree it is sanctioned for

## The blind spot, in the previous lane's own words

`syncscope.py` closes with: *"WHETHER A TEST IMPORTS A PRUNED DISTRIBUTION. The verdict set is
derived from the MANIFEST ... A test module importing `cv2` from an extra outside `all` still errors
at collection, and no reading of a manifest can say so."* That is an honest absence and it is the
subject here. One text cannot answer it; two can — the manifest AND the test tree.

A collection error is not a test failure. pytest IMPORTS every module it collects, so an
`ImportError` at module scope aborts that file and exits non-zero having judged nothing. The
2026-09-18 failure mode — a tree reading as BROKEN rather than UNEQUIPPED — survives one layer in,
past a scope that scored COMPLETE.

## What it convicted

| repo | selection | scope says | reach says |
|---|---|---|---|
| lab-commons | `dev` | COMPLETE | collects |
| optimi-lab | `dev` | COMPLETE | collects |
| wdg-lab | `dev` | COMPLETE | strands diskcache, fastapi, httpx, pandas |
| motronics | `pareto,dev` | COMPLETE | strands 7 |
| motronics | `all,dev,img-to-cad` | — | strands `pillow` |

The seven are cadquery-ocp-novtk, ezdxf, meshio, motronics-native, opencv-python-headless, pillow
and wdg-lab. Both COMPLETE scores are RIGHT at their own question: the runner survives both.

**The sharpest one is the third row.** `_synccensus_rows.py` names
`--extra all --extra dev --extra img-to-cad` as "the incantation that actually restored the box".
It carries the runner, the plugins, the linter and every vendor extra — and it still strands
`pillow`, which motronics declares ONLY in a `tooldrivers` extra that no incantation, no document
and no running code in that repo names. **There is no recorded selection in motronics that collects
its own test tree.**

## Two design moves that MEASUREMENT forced, not taste

**Installed metadata is the wrong instrument, not merely an incomplete one.**
`importlib.metadata.packages_distributions()` in this venv knows 22 import names and answers `None`
for cv2, OCP, PIL, yaml, ezdxf, meshio, scipy and matplotlib — every interesting case. Deeper: the
question is what a prune WOULD do, and an environment that has already been pruned answers that a
distribution does not exist. Reading a box to predict a box's future is circular. So resolution is
TEXT: declared name, then a NAMED alias set, then a file in the checkout, then UNRESOLVED by name.

**An import name maps to a SET of suppliers.** A one-to-one `cv2 -> opencv-python` map read
motronics as stranding two distributions it never declares: that repo declares
`opencv-python-headless` and `cadquery-ocp-novtk`. A build variant is a different distribution
supplying the same import, and only candidates the MANIFEST declares are used — so an aliased
import nothing declares answers UNRESOLVED rather than being convicted on a guess.

## The brief was wrong about one guard

It listed "sitting behind a skip mark" beside `importorskip` and `try/except ImportError` as
degrading. It does not. `pytestmark = pytest.mark.skipif(...)` is CREATED BY THE MODULE BODY, so the
body must execute before pytest can read it, and a module-scope `import cv2` runs first. Treating a
mark as a guard would score the loudest real hazard in the family as safe. Planted as its own
control in `test_dev_collectscope.py`.

## The control the family supplied itself

`OCP` is behind `pytest.importorskip` in wdg-lab and a bare module-scope import in motronics. One
reader, one import name, opposite answers, and the only difference is the guard. A reader that
convicted every optional integration would strand it twice; one that trusted the scope would strand
it never. That pair is pinned as a test, alongside four planted guard spellings and their bare twin.

## What it refuses and what it cannot see

Refuses: a reach set that moved either way (equality on errors, degrades AND unresolved), an extras
name the manifest does not declare (inherited from `survivors`), a caption for a reason, a scan
below its per-repo file floor, an alias row no live tree reaches.

Cannot see: a `conftest.py` `collect_ignore` or `--ignore` keeping a module out of collection; an
import through `importlib` or a string; a distribution that installs but fails to LOAD; and whether
an UNRESOLVED name survives — measured residue is `pdfminer`, `pywintypes`, `tomlkit`, `win32com`,
`yaml` in motronics and `pydantic_core`, `scipy` in wdg-lab, all pinned by equality.
