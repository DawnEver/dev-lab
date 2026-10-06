---
name: a-scalar-over-a-plane-has-three-shapes
description: The viz tier's `Field` was two drawings in one shape (the adapter picked the glyph, the producer could not), so it splits into `Field` (a continuum, to contour) and `Samples` (points that carry values, to scatter), `Grid` is added for a masked rectilinear array four consumer sites lacked, `panel_rects` owns the panel arithmetic, and bokeh refuses `Field` by name because it has no filled-contour glyph over a point set.
metadata:
  type: project
created: 2026-10-06
accessed: 2026-10-06
---

# A scalar over a plane has three shapes

The user directive for this slice was *"允许彻底重构！"* under 第一性原理 / 抛弃历史包袱 / 奥卡姆剃刀 /
唯一真相源 / 分层解耦 / 不要向后兼容, and the slice is step 3 of the plan: TWO MISSING DATA SHAPES AND
THE GRID HELPER, measured against the consumer that must merge in (its `wdg_viz/` renderers).

## `Field` splits, and the split is decided by a CONSUMER's own vocabulary

`Field` conflated two drawings the consumer names separately (`PlotMapType` distinguishes `Coutourf`
from `Scatter`), and each ADAPTER chose one: matplotlib drew a filled contour, bokeh a colour-mapped
scatter. A producer could not ask for the other — the conflation was not cosmetic, it was a decision
taken out of the producer's hands by the backend.

```
Field    a CONTINUUM, to contour   (x, y, values, scale)          -- surface through the samples
Samples  points that CARRY VALUES  (x, y, values, scale, marker,  -- marks, one per observation
                                    size, alpha)
Grid     a RECTILINEAR masked array (values, extent, scale)       -- a raster, voids transparent
```

* `Samples.values` IS REQUIRED and there is no `color`: a one-colour cloud is `draw_markers(Series)`,
  which already existed. `size` is a LENGTH and may be ONE number or ONE PER SAMPLE (a bubble map,
  measured at `duty_cycle_charts.py:118`); matplotlib takes an area, so that adapter squares it.
* `Grid` covers four measured `imshow`/`pcolormesh` sites (`field_maps.py:147`,
  `core/plotting/_plot_heatmap.py:87`, `slot_pole_combinations.py:157`, `motor_charts.py:768`). ROW 0
  IS THE SMALLEST Y — stated in the shape so neither adapter inherits the opposite from its library —
  and `extent=None` means THE INDICES ARE THE COORDINATES (the table case). `cells()` and `span()`
  are the two places the array is read, so a masked cell and a NaN are the same void in both
  adapters.
* NO BACK-COMPAT: nothing was aliased. Measured: the consumer has ZERO live call sites into this tier.

## The consequence nobody asked for, and it is the honest one: bokeh REFUSES `Field`

A continuum's drawing is a surface, and bokeh has no filled-contour glyph over a point set
(`contourpy` is declared by neither the `viz-bokeh` extra nor the package). Keeping the old
colour-mapped scatter would have made `Field` and `Samples` INDISTINGUISHABLE on that adapter —
exactly the conflation the split removed — and a producer asking for a contour map would get a cloud
that reads as one at a glance. So `BokehFrame.draw_field` raises, naming BOTH remedies: send
`Samples` if a cloud is what the data is, or use the matplotlib adapter. Same shape as the existing
`Contours` refusal, and the measured cost is that the shared description's field map is now driven
through matplotlib only (it moved out of `draw_everything` into `draw_continuum`).

## The grid helper: `panel_rects(nrows, ncols, *, left, bottom, right, top, hgap, vgap)`

The arithmetic ~10 consumer `subplots` sites would otherwise hand-compute, PROVIDED ONCE. A rect is
the axes' BOX and ticks/labels/titles are drawn OUTSIDE it, which is why a grid whose panels touch
draws the upper row's x labels through the lower row's title. `vgap > hgap` by default because a row
gap carries the upper panel's x labels AND its title; the bottoms are distinct and decreasing, which
is what bokeh's layout reads for its grid. `PANEL_RECTS` in `tests/_viz_figure.py` is now
`panel_rects(2, 2)` — so the panel arithmetic is RENDERED through both adapters, not asserted twice.

## The split, and one fix found on the way

`__init__.py` was 289/300 and the DEBT ceiling was at its exact sum, so the placement rules (the
rect convention, `PROJECTIONS`, `_place`, `_covers`, `_as_rect`, `_Placement` AND the new
`panel_rects`) moved to `_placement.py`: vocabulary-vs-helpers, the tier's own seam, and both
adapters and `NullRenderer` already read those rules. `PROJECTIONS` is re-exported (the precedent is
`bokeh.py` re-exporting `PALETTES` from `_bokeh_names`), so the public surface did not move.

`MARKERS.get(name, 'circle')` was a SILENT SUBSTITUTION in a module whose own docstring declares
refusal-by-name — measured while writing the cloud's marker line, which needed the same lookup. It is
now `_bokeh_names.marked()`, refusing with the list, and both verbs read it: the alternative was one
verb refusing and its twin drawing a circle for the same description.

## What moved, and what it cost

* `__init__.py` 289 → 278 code lines, `_placement.py` 83, `mpl_frame.py` 270, `bokeh_frame.py` 215,
  `_bokeh_glyphs.py` 166 — all under the 300 band, `__init__.py` with room for step 4 (the 3D
  protocol). Sizes were checked AFTER `git add`, because the size guard reads TRACKED files only.
* `CONSTANT_FLOOR` re-measured 358 → 359 (449 constants read; the two subject constants in
  `_viz_figure.py` are the growth), headroom unchanged at 90.
* `Field`'s bokeh refusal means the peer claim now has TWO subjects one adapter cannot draw (polar,
  continuum), both named in `test_viz_adapters_are_peers`' docstring rather than left to be noticed.
