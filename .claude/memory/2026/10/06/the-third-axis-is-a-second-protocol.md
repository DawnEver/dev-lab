---
name: the-third-axis-is-a-second-protocol
description: The 3D frame lands as a second protocol (`Frame3D`, reached by `Figure.frame_3d()`) rather than a third projection, because the two arities promise opposite verbs; the vocabulary is reused (`Series.z` for a trace in space) with one new shape (`Mesh`, vertices plus the faces that index them), bokeh refuses `frame_3d()` by name with the mpl remedy, and the module band is paid by a `_three_d.py` seam.
metadata:
  type: project
created: 2026-10-06
accessed: 2026-10-06
---

# The third axis is a second protocol

Step 4 of the plan in the design doc `DESIGN-the-viz-layer-from-first-principles.md` (2026-10-06) §6b
— the last shape that must exist before the winding consumer's ~62 figure functions can merge in.

## THE 3D VERB SET, RE-MEASURED (the lead was wrong in two places)

Measured from the consumer that must merge — its `wdg_viz/backend3d/mpl3d.py` (251 lines, 1 class)
and the `base.py` Protocol beside it, with the call sites read across the consumer's `src/`:

| verb in the consumer | real call sites | where it landed here |
|---|---|---|
| `draw_line_collection_3d(segments, colors, linewidths, linestyles, alpha)` | **`viz3d/connection_3d.py` ×2** — the ONLY production 3D drawing in the whole consumer | `Frame3D.draw_lines(Sequence[Series])` |
| `draw_line_3d(xs, ys, zs, ...)` | tests only | the same verb, one line per call |
| `draw_markers_3d(xs, ys, zs, ...)` | tests only | `Frame3D.draw_markers(Series)` |
| `draw_mesh_3d(vertices, faces, color, alpha)` | tests only — the consumer's `wdg_3d/measure.py` builds a `Poly3DCollection` raw and never routes through the backend | `Frame3D.draw_meshes(Sequence[Mesh])` |
| `draw_tube_3d(centerline, radius, color, alpha, n_around)` | tests only | **NOT A VERB** — see below |
| `set_bounds_3d(xlim, ylim, zlim)` | connection_3d ×1 | `Frame3D.set_limits(*, x, y, z)` |
| `set_view_3d(elev, azim)` | connection_3d ×1, measure.py (`view_init`) | `set_view(*, elev, azim)` |
| `set_box_aspect_3d(aspect)` | connection_3d ×1, measure.py | `set_box_aspect(aspect)` |
| `set_axis_labels_3d(x, y, z)` | connection_3d ×1 | `set_xlabel`/`set_ylabel`/`set_zlabel` |
| `add_legend_entries(...)` + `legend(...)` | connection_3d ×1 | `legend(*, on=True)`, with the label on the primitive |
| `regist_fig_path`/`save_fig`/`show_fig`/`close` | connection_3d | already `Figure`'s (the artefact policy) |

**THE CONSUMER'S PROTOCOL IS WIDER THAN ITS OWN CALL SITES**: three of the nine verbs exist only for
their tests. The real figure is ONE shape — a group of conductor centrelines in space — plus a camera
and three labels, which is why the landing protocol is eleven verbs rather than the union of nine
plus a frame's.

**AND A `draw_tube_3d` IS NOT A DRAWING VERB AT ALL.** It builds a swept surface (parallel-transport
frames, rings, quad faces) — geometry GENERATION, which is not this layer's subject; the same
argument the design's §4 makes about `PolyCollection` factories leaking into arrangements. What
reaches a frame is the `Mesh` the generator produced, and the generator belongs with the geometry
(the consumer's mesh layer), not here. Nothing in the layer draws a tube; nothing needs to.

## THE SHAPE: two protocols, not one union (the shared base WOULD have been a lie)

`Frame` and `Frame3D` promise OPPOSITE verb sets — a 3D frame has a camera, a box aspect and a z
label and LACKS bars, circles, a raster, a field, a quiver, ticks. Folding them into one type leaves
half of every verb table refusing per call, and `isinstance(frame, Frame)` — which this tier says is
"a question with an answer instead of an assumption" — would answer "of some arity". So:

```
Figure.frame(rect, projection='cartesian'|'polar', sharex, sharey)  -> Frame    (21 verbs)
Figure.frame_3d(rect)                                               -> Frame3D  (11 verbs)
```

* `frame(projection='3d')` **RAISES** with `figure.frame_3d()` as the remedy (`_placement._place`),
  and `'3d'` is deliberately NOT in `PROJECTIONS`: that set is what a plane frame's `projection` may
  hold, and a third axis is a different protocol rather than a third entry.
* Both protocols are `runtime_checkable`, so `isinstance` answers the arity question on the object
  itself; `test_viz.py::test_a_3d_frame_is_a_different_protocol_from_a_plane_one` measures both
  directions with NOTHING installed.
* The canvas's registry is the union: `Figure.frames` is `tuple[Frame | Frame3D, ...]`.
* What stays SHARED is what the two frames would drift on: the placement rule (`_place_3d`), the
  canvas's palette cursor (extracted to `mpl_frame._next_color`, measured: a plane trace takes
  `palette[0]` and the next 3D trace `palette[1]` on one canvas), the canvas and its lifecycle, and
  every primitive field.

## THE VOCABULARY IS REUSED, and the one new shape is CONNECTIVITY

* **A trace in space is a `Series` with a `z`** — not a `Curve3D`. matplotlib spells the two as one
  method (`plot(x, y)`, `plot(x, y, z)`), the fields a curve carries are the same six, and a second
  dataclass would be one idea with two spellings. THE RANK IS NOT SILENT: `mpl_frame._plane` refuses
  a `Series` carrying a z on a plane frame (matplotlib would drop the coordinate without a word) and
  `MplFrame3D._space` refuses one that does not carry it. One refusal each, both naming the other
  frame's verb.
* **The new one is `Mesh(vertices, faces, ...)`** — a vertex set AND the faces that index it, which
  is what a meshing layer holds and what no other primitive does (`Patch` repeats its vertices per
  polygon; `Grid` is rectilinear; `Field`/`Samples` are points). `polygons()` resolves the indices in
  ONE place, the way `Grid.cells()`/`Colorbar.bands()` do. Nothing else was added: no `Tube`, no
  `Mesh3D` name (a mesh is a mesh; the third axis is the FRAME's).
* `Frame3D.draw_lines` is a COLLECTION verb (`Sequence[Series]` → one `Line3DCollection`).
  MEASURED on matplotlib 3.11.2: 200 traces drawn in one collection take 0.037 s against 0.14 s as
  200 `Line3D` artists (~4x), and the consumer's own backend chose the collection for the same
  reason. Because one artist carries ONE legend label, the lines of one call must share theirs —
  refused by name otherwise, so a mixed call cannot silently lose a legend row.

## PARITY: bokeh refuses at the canvas, with the polar message's exact voice

`BokehRenderer.frame_3d()` raises `NotImplementedError`, mirroring `frame(projection='polar')` one
verb away rather than the per-CALL refusals (`draw_field`/`draw_contours`):

> `BokehRenderer cannot build a 3D frame: bokeh draws every glyph in two cartesian dimensions and has
> no third axis. Draw this figure with lab_commons.viz.mpl.MplRenderer, which has one`

It is refused at the CANVAS rather than on a frame because there is no 3D frame to hand back at all —
a stronger version of the same statement, and it leaves `renderer.frames` untouched.

## NO NEW DEPENDENCY, and the gate says so by MEASUREMENT

`mpl_toolkits` ships INSIDE the matplotlib distribution (measured from its own file list: the
top-level roots are `matplotlib` and `mpl_toolkits`), so `mpl_frame_3d.py`'s
`import mpl_toolkits.mplot3d.art3d` is a matplotlib import. `test_viz_gate._PROVIDED` is the named
declaration of that, and `test_the_import_map_names_modules_their_distribution_really_provides`
re-measures it against `importlib.metadata` where the extra is installed. Registering the `'3d'`
projection is a side effect of that same import, which is why `MplRenderer.frame_3d` needs no setup
of its own.

## THE MODULE BAND: the seam is `_three_d.py`

`__init__.py` was at 278/300 code lines and this addition is ~11 code lines of vocabulary plus two
protocols; the module would have crossed the band. The seam taken is the same one `_placement.py`
took: `_three_d.py` (private file, public re-export — `Frame3D`, `Mesh`, `NullFrame3D`) holds the 3D
protocol and the one shape only it draws, and `mpl_frame_3d.py` holds the frame class, which the
plane frame's own module had no room for. Final readings: `__init__.py` 289, `_placement.py` 93,
`_three_d.py` 78, `mpl_frame.py` 280, `mpl_frame_3d.py` 109 — all under the 300 band, so the DEBT
pins and the ceiling do not move (measured over TRACKED files, after staging: 190 modules, the same
three pins, the sum at the ceiling exactly).

Ratchets RE-MEASURED rather than raised, three of them: `test_viz_gate`'s module roster and
`PROTOCOLS` gained the two files (and the table gained the module that DECLARES each protocol,
because `Frame3D` is not in `__init__.py` any more); `test_famtests_countpins.CONSTANT_FLOOR` moved
359 -> 361 by the four figure constants the new shared subject adds; and
`test_famtests_venvspelling.FILE_FLOOR` moved 150 -> 151, because two source modules are two files
and the 40-file margin is not the thing to widen.
