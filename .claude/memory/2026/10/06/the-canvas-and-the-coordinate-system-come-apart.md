---
name: the-canvas-and-the-coordinate-system-come-apart
description: The viz tier's Renderer — a canvas, a coordinate system and a backend in one object — is split into Figure (frame/save/show/close) and Frame (projection + axes + every draw verb), which makes polar, twinx and panel grids expressible; the placement rule lives once in the vocabulary, both adapters read it, bokeh refuses polar by name, and matplotlib's layout engine is turned off because the rect IS the layout.
metadata:
  type: project
created: 2026-10-06
accessed: 2026-10-06
---

# The canvas and the coordinate system come apart

The user directive for this slice was *"允许彻底重构！"* under 第一性原理 / 抛弃历史包袱 / 奥卡姆剃刀 /
唯一真相源 / 分层解耦 / 不要向后兼容, and the defect a sibling measured against the consumer that must
merge in was: **`Renderer` conflated the CANVAS, the COORDINATE SYSTEM and the BACKEND.** Because it
collapsed them it had to invent an answer to "which coordinate system?" — and it invented "the one
and only one, plain cartesian, built at construction". Three shapes were therefore INEXPRESSIBLE:
5 of `wdg_viz`'s 21 registry entries are polar, `twinx` has 2 measured sites, and `subplots` with
`sharex`/`sharey` has ~10 including the family's own multi-solver field-map comparison.

## The shape, and the ONE rule that is the vocabulary's

```
Figure   the CANVAS   frame(...) / frames / save / show / close
  └─ Frame   ONE COORDINATE SYSTEM   projection, axes, ticks, title, EVERY DRAW VERB
```

The draw verbs MOVED rather than changed: same spellings, same primitives, new owner. `collections
.abc`-style typing is kept — both protocols are `runtime_checkable` and `isinstance` is the check.

**The placement rule is the vocabulary's and is stated once** (`lab_commons.viz._place`), because a
rule implemented in each adapter holds only until one of them is edited:

* `rect=(left, bottom, width, height)` in canvas fractions; `None` means the CANVAS DECIDES;
* a frame that names NO rect and shares an X axis is drawn OVER the frame it shares with — that is
  how a twin axis is spelled, and it inherits that frame's rect and projection;
* an unknown projection, an axis shared across two coordinate systems, a `sharey` with no rect (a
  y-axis twin is not expressible: the inherited placement is an X relationship) and a rect that is
  not four numbers all RAISE by name, identically on the box that draws nothing.

## The three measured shapes, in BOTH adapters

* **PANEL GRID** (2x2, every panel sharing both axes): matplotlib — four axes, `set_limits` on the
  first is the limit of all four; bokeh — four figures in a `gridplot` at the cells their rects
  describe, sharing `x_range`/`y_range` OBJECTS. Both report the same rects, because neither
  decides them.
* **TWIN AXIS**: matplotlib — `Axes.twinx()` (its own y on the right, x axis invisible, transparent
  patch, and a joined pair a layout engine cannot drift apart); bokeh — a second `Range1d` in
  `extra_y_ranges` plus a right-hand `LinearAxis`, with every glyph of the twin bound to that range
  by NAME (a `None` passed as `y_range_name` is REFUSED by bokeh, hence `given()`).
* **POLAR**: matplotlib draws it (`projection='polar'`); **bokeh REFUSES by name** — it has no polar
  projection and draws every glyph in cartesian data units, so a silent cartesian frame is the
  failure the refusal exists to prevent. `Contours` is the other, older refusal.

ONE PLACEMENT BOKEH CANNOT DRAW, and it refuses: an ARROWED segment on a twin frame is an `Arrow`
ANNOTATION, which has no range binding, so its head would land on the base frame's scale.

## Two decisions that cost the most time, both measured

* **MATPLOTLIB'S LAYOUT ENGINE IS TURNED OFF FOR THE CANVAS** (`figure.set_layout_engine('none')`).
  A figure whose axes were all added by hand makes constrained layout warn on EVERY draw ("there are
  no gridspecs with layoutgrids") — and a warning per figure in every consumer's batch is noise
  nobody can act on. Measured alternatives: `set_in_layout(False)` does NOT silence it, and a
  per-frame `GridSpec(left=...)` is IGNORED by the engine (all four 1x1 cells came out full-canvas),
  so the only honest answer was to say that the rect IS the layout.
* **`rect is None` IS NOT `rect == (0,0,1,1)`.** The first spelling of the default was the whole
  canvas, and a full-bleed axes has its title and labels OUTSIDE the canvas — measured, clipped, on
  the interactive path (`bbox_inches='tight'` at save hides the defect in exactly the artifacts a
  test looks at). A frame that names no rect is now `add_subplot()` (matplotlib's own panel, margins
  and all) and one that names a rect is `add_axes(rect)` — the two statements drawn as the two
  different things they are.

## What it cost, and what it removed

Split by the band, not by preference: each adapter is now a canvas module and a frame module, and
bokeh needed a third (`_bokeh_glyphs.py` — the four verbs that BUILD DATA rather than calling a
glyph), because the twin plumbing and the composite glyphs put its frame 31 code lines past the
band. `__init__.py` is at 289/300: the NEXT vocabulary addition needs that split too.

REMOVED, for the consumers to repoint: the `Renderer` protocol; every draw/axis verb on
`MplRenderer` and `BokehRenderer` (same spellings, now on the frame); and `BokehRenderer.figure`
(the canvas has frames, each with its own bokeh figure — there is no single one to hand back).

Ratchet: `CONSTANT_FLOOR` re-measured 357 → 358 (448 constants read, the same ~80%; the headroom
stays 90). Everything else passed unchanged, including the module-size band and the verb-parity
guard, which now checks TWO protocols and reads them from the source so it holds with neither
plotting library installed.
