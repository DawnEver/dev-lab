---
name: the-family-grew-a-plotting-layer
description: lab_commons.viz lands as a tier-2 opt-in subpackage — a plotting VOCABULARY that imports no plotting library, one adapter per backend behind one extra each, and the display policy re-homed from a consumer. Both adapters are measured drawing the same description; four ratchets had to be re-measured rather than raised.
metadata:
  type: project
created: 2026-10-06
accessed: 2026-10-06
---

# The family grew a plotting layer

A user ruling asked for drawing to become a UNIVERSAL family capability, with bokeh a first-class
backend for every existing plotting module and for the winding library's renderers alike, and for
the shared layer to live in this repo. The evidence that it was not one: the SAME config helper
existed twice in one tree with two DISAGREEING bodies (`font.size` 10 in one, 18 in the other), and
a vendored winding library carried its own mpl/bokeh backend pair that nothing outside it could use.

## The shape, and why it is not a wrapper

`lab_commons.viz` is the VOCABULARY and imports **no plotting library at all** — not at module scope
and not lazily (`NO-LAZY-IMPORT`; the opt-in mechanism in this family is the IMPORT). A figure is
data: `Series`, `Bars`, `Patch`, `Circle`, `Segment`, `Label`, `Field`, and one `Style` that is now
the single source of figure size, typeface, type size and palette. A renderer draws it.

Three decisions the layer had to MAKE rather than wrap:

* **One picture per renderer.** A renderer IS the figure — the 18-verb `Renderer` Protocol is
  checked with `isinstance`, so "this is a renderer" is an answer rather than an assumption.
* **`NullRenderer` is the DEFAULT.** A sweep or an unattended batch should not have a plotting
  library present at all, and the alternative is `if plot:` branches through every producer.
* **`Bars.width` is the one field with a value instead of "let the renderer decide"** — matplotlib
  draws 0.8 and bokeh 1.0, so a `None` would mean a description that draws a DIFFERENT picture per
  backend, which is the one thing a shared vocabulary must never do.

Two GATES, one per backend, and they are equal peers: `viz-mpl` (`matplotlib>=3.5`) and `viz-bokeh`
(`bokeh>=3`). Neither extra pulls the other's library in, and `tests/test_viz_gate.py` pins it by
reading the import statements and by running a FRESH interpreter — `import lab_commons` must leave
`lab_commons.viz`, `matplotlib` and `bokeh` all out of `sys.modules`.

## The display policy moved, and nothing was left behind

`enable_interactive_backend` / `is_interactive_backend` / `show_or_save` lived in a consumer's
`core/utils/cli.py`. They are the ONE place that knows GUI toolkits exist, so they now live in
`lab_commons.viz.mpl` with their reasoning intact — the `MPLBACKEND` declaration that wins, the
save-BEFORE-show ordering (a blocking `show()` discards a figure written after it), and the dead
canvas that degrades instead of warning. Bokeh gets no counterpart: it has no dead canvas, and a
policy guarding a failure a library does not have is a mechanism nobody can check. **No shim, no
alias, no dual entry point** — the consumers move by their own owners.

## What the first honest run found

Install the extras through the repo's own door (`.venv/Scripts/python.exe -m lab_commons.dev.dep
--sync --extra dev --extra viz-mpl --extra viz-bokeh`; a bare `uv pip install` is denied), because
UNTIL AN ADAPTER HAS RUN IT IS A CLAIM. Two real defects fell out of the first execution and neither
was visible in a signature: bokeh validates `line_width`/`size` against `Real` and REFUSES `None`
(the vocabulary's spelling for "the library decides"), so `_given()` drops those properties — while
a COLOUR must NOT be dropped, because bokeh reads `None` as "no fill" and an omitted colour takes its
grey default. And `PALETTES` is an INTERSECTION read off both registries, not a guess: bokeh has no
`Coolwarm`/`Rainbow`, and `blues`/`greens`/`reds` are capitalised in matplotlib. An unknown colormap
RAISES with the list; a silent fallback would draw a different colour scale per backend.

`bokeh_save(..., resources=INLINE)` is load-bearing the same way: without it the page renders only
while the box can reach a CDN, which fails exactly when a report is read off the machine that wrote
it.

## Four ratchets re-measured, none raised

The gate went from 7 red to 2967 passed / 0 failed (`tree=sha256:4d76d849cfe33105`,
`env=dae943dbfe09267b`), and every red was a RATCHET doing its job rather than an accident:

* `test_arch_suppressions` — the ported `except Exception:` in the GUI probe is two suppressed rules
  (`BLE001`, `S112`), declared BY NAME with the reason: what a backend raises when it cannot be used
  is not one type and differs per platform.
* `test_famtests_countpins` (446 constants) and `test_famtests_echoedtoken` (4206 bodies) — both
  floors re-priced on the ratio their own comments use (357, 3785). Raising the HEADROOM is how the
  arm is kept while the guard is given up; that is not what happened.
* `test_the_test_trees_collect_after_a_sync` and `test_the_syncs_leave_a_verdict_runnable` — both
  census rows MOVED WITH THE SELECTION they record, because `.github/workflows/ci.yml` now syncs
  `dev viz-mpl viz-bokeh`. Without the viz extras the same tree DEGRADES on those two names and
  still collects: every adapter test holds a module-scope `pytest.importorskip`, which the kit's own
  collection census classifies as a degrade rather than a stranded file.
* `test_no_name_carries_a_unit` convicted `Label.va` — `va` is a unit (volt-ampere). The anchors are
  `halign`/`valign` now; matplotlib's two-letter abbreviations are not worth a unit-shaped name.

A lesson for the next tier: a FLOOR is not a formality when the population is the whole tree. Adding
a feature adds constants and function bodies everywhere, and the arms that refuse a vacuous scan are
the first thing it reds.
