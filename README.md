# lab-commons

Project-agnostic shared infrastructure for the consumer-a / consumer-c / consumer-b
family of labs. Extracted because the same utils layer had drifted into **six
near-identical, silently-diverging copies** across those repos (see
`finding-shared-lab-infra-extraction.md` in consumer-a's memory).

## The two-tier rule

**Tier 1 ? project-agnostic infrastructure.** No single lab's solver, winding,
optimizer, or vendor vocabulary belongs here. Generic ownership does not imply
an eager package facade or a mandatory installation dependency.

**Tier 2 ? shared-domain vocabulary.** `lab_commons.em` describes the family's EM
quantities; it is imported explicitly and installed through the `units` extra.
The plotting vocabulary is NumPy data, with separate renderer adapters.

The package root imports nothing. Use the defining module, such as
`from lab_commons.log import get_logger`, rather than root symbol re-exports.
The base installation is the standard library alone. Select capabilities explicitly:

| Extra | Modules | Additional dependencies |
|---|---|---|
| `units` | `units`, `em` | NumPy, Pint, Pydantic |
| `paths` | `paths` | platformdirs |
| `io` | `file_io` | rtoml |
| `structured` | `structured` | structlog, colorama on Windows |
| `viz` | the plotting vocabulary (`viz`) | NumPy |
| `viz-mpl` / `viz-bokeh` | named renderer adapter, beside `viz` | matplotlib / Bokeh |
| `dev` | development tools and their declared infrastructure | verification/tool dependencies |

## What's here (v1)

- `lab_commons.log` — a named, `propagate=False` stdlib logger factory plus
  `log` / `log_decorator` / `timer` free-function helpers.
- `lab_commons.paths` — app-agnostic path resolution and per-run output directories.
  Home-root precedence per app: `<APP>_HOME` env -> auto-detected source checkout ->
  platformdirs. Everything is parameterized by `app_name`; nothing is hardcoded to any
  one project.
- `lab_commons.structured` — structlog/JSON structured output layered on the SAME named
  logger `log.py` produces (purely additive, v1 stays unchanged), secret redaction by
  field-KEY pattern (license keys / tokens / fingerprints / secrets / passwords are
  hashed, never logged in the clear), and a two-phase `bootstrap()` -> `bind_run_dir()`
  transport (console-only before the run directory is known, then a JSONL file sink).
- `lab_commons.file_io` — TOML read/write (`read_toml`, `save_toml`), plus filesystem
  presence helpers (`check_path`, `list_files_in_dir`).
- `lab_commons.exceptions` — the generic subset of exception classes/decorators
  (`ParameterException`, `QuantityException`, `deprecated`, `not_implemented`).
  Project-specific exceptions (a vendor-solver name, an error-code catalog) stay in
  each consumer's own tree.
- `lab_commons.units` (**tier 1**) — the generic pint <-> pydantic `Annotated` machinery:
  `ureg` / `Q_`, `PydanticQuantity`, `get_quantity_type()`, `BaseModel_with_q`. No EM
  vocabulary; importing this module never imports `lab_commons.em`.
- `lab_commons.em` (**tier 2, opt-in**) — the family-shared EM/physical quantity
  vocabulary built on `lab_commons.units`: every `*Type = NewType(...)` (`LengthType`,
  `TorqueType`, `AngleSpeedType`, ...) and every `Q_*` constant (`Q_0mm`, `Q_360deg`,
  `Q_0Nm`, ...), plus `Cartesian2DPoint`/`Polar2DPoint`, `Q_list2array`,
  `array2list_2Dpoint`, `is_equal_2DPoint`, and `CONSTANTS` (`vacuum_permeability`).
  Import explicitly: `from lab_commons.em import TorqueType`.
- `lab_commons.viz` (**tier 2, opt-in**) — the family's ONE plotting vocabulary, and the two
  adapters that draw it. The vocabulary imports **no plotting library at all**: a figure is
  declared as data (`Series`, `Bars`, `Patch`, `Circle`, `Segment`, `Label`, `Contours`, `Vectors`,
  `Colorbar`, `Ticks`, one `Style` — the single source of the figure size, typeface and palette —
  and the three shapes a scalar over a plane can be: `Field` for a continuum drawn as a surface,
  `Samples` for points that carry values, `Grid` for a masked rectilinear array) and handed to an
  adapter. A CANVAS is a `Figure` (`frame`/`frame_3d`/`save`/`show`/`close`) and a COORDINATE SYSTEM
  is a `Frame` (its projection, its axes, every draw verb), so one picture can hold a panel grid, a
  polar frame or a second y scale over the first — `panel_rects(nrows, ncols)` is the panel
  arithmetic, gaps included, so a grid's labels do not land on the panel below. A THIRD AXIS IS A
  SECOND PROTOCOL rather than a third projection: `Frame3D` (`figure.frame_3d()`) has verbs a plane
  frame does not (a camera, a box aspect, a z label) and lacks verbs it has, a trace in space is
  still a `Series` carrying a `z`, and `Mesh` is the one shape nothing else holds — a vertex set AND
  the faces that index it, which is how meshed data arrives. `NullRenderer` is the default,
  so a solver batch describes its figures on a box where no plotting library is installed and draws
  nothing. A backend is an adapter whose own import is the opt-in — `from
  lab_commons.viz.mpl import MplRenderer` (`lab-commons[viz,viz-mpl]`) or `from
  lab_commons.viz.bokeh import BokehRenderer` (`lab-commons[viz,viz-bokeh]`); the two are equal peers,
  checked against the same protocols and drawing the same description. A figure that cannot be
  drawn by a backend raises with the reason, never a silent substitution — bokeh has no polar
  projection, no isoline glyph, no filled-contour glyph over a point set and no third axis, so
  `projection='polar'`, `Contours`, `Field` and `frame_3d()` are refused by name there, each naming
  the adapter or the shape to use instead.

- `lab_commons.proc` (**tier 1**) — what a BOX is doing: `system_memory()` (the one home for
  `GlobalMemoryStatusEx` / `/proc/meminfo`), `working_set_bytes(pid)`, `pid_alive(pid)`,
  `process_tree(pid)` and `kill_process_tree(pid)`. stdlib `ctypes` only, never `psutil` — an
  optional dependency makes a ceiling that silently stops being enforced on some machines, which
  is worse than no ceiling because it is believed. Unreadable is always distinct from zero.
- `lab_commons.resources` (**tier 1**) — resource DIMENSIONS as data (`seats`/`memory`/`cpu`
  enforced; `wallclock`/`disk`/`gpu` carrying the shape with nothing able to check them), the vocabulary
  a Slurm plan and `lab_commons.width.fits` read.
- `lab_commons.box` (**tier 1**) — the ONE ledger per machine: a run DECLARES cores, memory, a wall and
  tool seats, is admitted by the one rule (`compute.admission.admit`) on the MEASURED room
  (`box.supply.room`: free now, less what held claims have not taken yet, less the `[reserve]` margin),
  and runs inside a kernel limit sized to its claim. Seats (an environment, a licence) are claims too.
- `lab_commons.outcomes` (**tier 1**, standard library only, imports no other subpackage) -- the ONE
  task-outcome vocabulary: `Status` in two families (DECIDED / RETRYABLE), `Evidence`, `Cell`, `Identity`,
  `Expectation`, an append-only fsynced `Record` with DECIDED finality, and `Conclusion`.
- **consumer-a** — the origin of this code; re-points `core/utils/{config,logger}.py`
  at this package (see that repo's `plan-lab-commons-standalone.md` for the swap runbook).
- **consumer-c** — consumes the runtime package and the `[dev]` kit (shared rules registry,
  deny rules and agent guard, famconfig-rendered config, `lab_commons.dev.verify`).
- **consumer-b** — consumes the runtime package (logging, paths, file_io, exceptions, units, em) and
  the `[dev]` kit the same way. Its forks (Hairpinexample-org, consumer-b-webui) do NOT depend on
  lab-commons.

## Installing (git URL)

Not yet published to PyPI. Consumers depend on it by git URL and track the latest
`main` (`<forge-host>/<owner>` is what your `origin` remote names) — the family takes the
newest version of every dependency, so drift is closed by
upgrading, not by pinning:

```toml
dependencies = [
    "lab-commons @ git+https://<forge-host>/<owner>/lab-commons.git",
]
```

## Anti-drift guard

Each consumer is expected to carry a test that reds if a local re-implementation of a
lab-commons module reappears in its own tree (a re-fork), per this repo's origin plan
("a check the code must consult", not a policy nobody reads).
