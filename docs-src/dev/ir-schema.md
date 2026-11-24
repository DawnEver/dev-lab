# IR schemas: one TOML declaration, generated Python and Rust

**Status: DRAFT for review. No generator exists yet.** The fixtures under `tests/data/ir_schema/` are the
worked example below, kept for the generator's TDD.

A repo declares each intermediate representation (IR) once, as TOML. Python and Rust types, their validation,
the unit codec and the canonical serialization are all generated from it; nothing generated is committed.

- The schema is the single source of truth for a record's shape; the catalogue is the single source of truth
  for what a quantity's SI unit is.
- Units exist only at the boundary. Generated types hold linear, absolute SI floats and nothing else.
- dev-lab hard-codes no path: the repo declares where its schema and catalogue live (below).

## Where the files live

The repo declares both paths as facts in its `pyproject.toml` (or `layout.toml` when it has one):

```toml
[tool.dev_lab.ir_schema]
schema = "<path>/schema.toml"        # one or more files; see open question 7
quantities = "<path>/quantities.toml"
python_package = "<importable package>"   # where the generated module is written
```

A repo with no such table has no IR; `verify` is silent for it.

## The schema file

```toml
schema_version = 3                    # positive int; see Versioning

[enum.<Name>]
values = ["a", "b"]                   # non-empty, unique, lower_snake strings

[record.<Name>]
doc = "..."                           # optional
[record.<Name>.field.<name>]
type = "float"                        # see the table
optional = false                      # default false
quantity = "<quantity name>"          # float and array fields; never a unit string
doc = "..."                           # optional
dtype = "float64"                     # arrays only
shape = ["n", 3]                      # arrays only: ints or named symbolic dims
```

| `type` | Meaning | Python | Rust |
|---|---|---|---|
| `bool` | true/false | `bool` | `bool` |
| `int` | signed 64-bit | `int` (range-checked) | `i64` |
| `float` | IEEE double, finite | `float` | `f64` |
| `str` | UTF-8 | `str` | `String` |
| `enum:<Name>` | one of `[enum.<Name>].values` | `Enum` subclass | `enum` |
| `record:<Name>` | nested record, by value | the dataclass | the struct |
| `id:<Name>` | reference to a `<Name>` record by its `id` field | `NewType("<Name>Id", str)` | newtype `struct <Name>Id(String)` |
| `array` | n-d array of `dtype` and `shape` | `NDArray[np.<dtype>]` | `ndarray::Array<dtype, IxN>` |

- Names: records and enums are `UpperCamel`, fields and enum values `lower_snake`. Field order in the file is
  the constructor order; required fields come first in generated code, optionals after, each in file order.
- `dtype` is one of `bool`, `int32`, `int64`, `float32`, `float64`.
- `shape`: an int is a fixed extent; a string is a symbolic dim. Within one record, every use of the same
  symbol must have the same extent at construction (`time` and `position` above share `n`).
- `quantity` is required on a `float`/`float`-dtype array that carries a physical value and is forbidden on
  `bool`, `int`, `str`, `enum`, `id`, `record`. A dimensionless float declares `quantity = "dimensionless"`
  only if the catalogue has it; a float with no `quantity` is a pure number.
- `id:<Name>` requires `<Name>` to have a field named `id` of type `id:<Name>`.

## The quantities catalogue

```toml
[quantity.<name>]
unit = "<SI unit>"                    # coherent SI, Pint-parsable: "m", "kg", "m/s", "K"
dimension = "M L T I Theta N J"       # seven integer exponents, space-separated, e.g. "1 1 -2 0 0 0 0"

[port_domain.<name>]
effort = "<quantity>"
flow = "<quantity>"
```

- `unit` is coherent SI (no prefix, no offset): `K`, never `degC`; `Pa` absolute, never gauge; never `dB`.
  `unit` and `dimension` must agree (checked through Pint at generation).
- A port domain names a power-conjugate pair: `dimension(effort) + dimension(flow)` must equal the dimension of
  power (`1 2 -3 0 0 0 0`).

## Units cross once, at the boundary

- **Input codec** (generated): a boundary value is a number (already SI) or a string with a unit
  (`"250 g"`, `"85 degC"`). It converts once, through Pint, to the field's catalogue unit, refusing a
  dimension mismatch. Affine units (`degC`, `degF`) convert as absolute temperatures; gauge pressure needs a
  declared reference pressure in the same input (open question 5); `dB`/`dBA` convert to the linear ratio.
- **Output rendering** (generated) converts SI back to a requested display unit. dB is a rendering of a
  linear value, never stored.
- Generated types, the canonical serialization and the content hash hold SI floats only. Pint is imported by
  the codec and the renderer, never by the generated types.

## Versioning

- `schema_version` is a positive int bumped on every schema change. Any change to the schema, the catalogue or
  the generator regenerates (see Freshness).
- **Additive** change -- a new `optional` field, a new record, a new enum, a new quantity: no migration. A
  record written before it reads unchanged, because the field is absent and absent optionals are omitted.
- **Breaking** change -- a field removed or renamed, a type, `dtype`, `shape` or `quantity` changed, an optional
  made required, an enum value removed or renamed, a quantity's `unit` changed: `FORMATS-MIGRATE-ONCE`. The same
  change rewrites every tracked record to the new shape, and readers keep only the current shape.
- Every serialized record carries `"schema_version"`. A reader meeting an older version refuses it by name:
  `<path>: schema_version 2, current 3 -- migrate with <the repo's declared migration command>`. A newer
  version is refused the same way, naming the regenerate command.
- Adding an enum value is additive for readers but breaking for an exhaustive Rust `match`; it is classified
  additive (open question 8).

## Canonical serialization

One byte sequence per value, so `sha256(bytes)` is a stable content hash.

- **Encoding**: JSON (RFC 8259), UTF-8, no BOM, no insignificant whitespace, no trailing newline.
- **Top level**: an object holding the record's fields plus `"schema_version"`. Nested records carry no
  `schema_version`.
- **Key order**: sorted by Unicode code point of the key (equal to UTF-8 byte order), at every level.
- **Absent optionals are omitted**; `null` never appears. So adding an optional field leaves every existing hash
  unchanged.
- **bool**: `true`/`false`. **int**: decimal, no leading zeros, no `+`, no exponent.
- **float**: the shortest decimal string that round-trips to the same IEEE double (Python `repr`, Rust `ryu`),
  then normalized: always contains `.` or `e` (`1.0`, not `1`); exponent as `e` with sign only when negative
  (`1e-07`, `1e+16` -> `1e16`); `-0.0` kept as `-0.0`. NaN and infinities are refused at construction.
- **str**: JSON string; escape only `"`, `\` and U+0000..U+001F (as `\uXXXX` except `\b \f \n \r \t`); no
  other escaping, no Unicode normalization.
- **enum**: its value string. **id**: its string.
- **array**: nested JSON lists in C (row-major) order, elements by the scalar rules for the `dtype`. `dtype` and
  `shape` are not serialized: the schema fixes them and the reader validates against it. An extent-0 array is
  `[]` at the depth where it occurs.

## Python output

One module per schema, written at package build into `<python_package>/_ir.py` (the way hatch-vcs writes
`__version__.py`), git-ignored. No Pydantic; runtime dependencies are `numpy` only (Pint for the codec module).

- Records: `@dataclass(frozen=True, slots=True, kw_only=True)` with a generated `__post_init__` that validates.
- Arrays: annotated `NDArray[np.float64]`; `__post_init__` checks `dtype` (exact, no casting) and shape
  (fixed extents and consistent symbolic dims), then stores a read-only copy (`flags.writeable = False`).
- Enums: `class Finish(Enum)` with the values as both name and value.
- Optionals: `X | None = None`.
- Ids: `WidgetId = NewType("WidgetId", str)`.
- Errors: one `IRValidationError(ValueError)` whose message is `<field path>: expected <x>, got <y>`, the path
  dotted from the top record (`Sample.position.shape[1]: expected 3, got 2`).
- Each record gets `to_canonical_json() -> bytes`, `content_hash() -> str` and `from_canonical_json(bytes)`.

### Freshness

The generated file's first line records `# ir-schema-fingerprint: sha256:<hex>`, the hash of the canonical
bytes of the schema file(s), the catalogue and the generator version. `verify` recomputes it and refuses a
generated file whose fingerprint differs, naming the file and the regenerate command.

## Rust output

`build.rs` of the consuming crate calls the generator (a dev-lab build-dependency) and writes
`$OUT_DIR/ir.rs`, included by `include!(concat!(env!("OUT_DIR"), "/ir.rs"));`. Never committed.

- Records: `#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]` structs with
  `#[serde(deny_unknown_fields)]`; optionals are `Option<T>` with `skip_serializing_if = "Option::is_none"`.
- A `validate(&self) -> Result<(), IrValidationError>` with the same path messages as Python.
- Behind feature `pyo3`: `FromPyObject`/`IntoPyObject` converting to and from the generated Python dataclass
  (arrays through `numpy` crate, zero-copy on read where the layout allows).
- The canonical bytes come from a generated `to_canonical_json`, not from `serde_json`'s defaults (key order and
  float format above); the equivalence test is Python bytes == Rust bytes on the fixtures.

## Refusals

Each refusal names its cause and its door.

| Refusal | Cause | Door |
|---|---|---|
| `IR-SCHEMA-UNDECLARED` | generation asked but no `[tool.dev_lab.ir_schema]` | add the table (Where the files live) |
| `IR-UNKNOWN-TYPE` | `type` not in the table, or a dangling `enum:`/`record:`/`id:` name | fix the name or declare the target |
| `IR-RECORD-CYCLE` | `record:` nesting reaches itself | break the cycle with an `id:` reference |
| `IR-ID-WITHOUT-ID-FIELD` | `id:<Name>` but `<Name>` lacks `id: id:<Name>` | add the `id` field |
| `IR-UNIT-IN-SCHEMA` | `quantity` is a unit string, or a `unit` key on a field | name a catalogue quantity |
| `IR-UNKNOWN-QUANTITY` | `quantity` not in the catalogue | add it to the catalogue |
| `IR-QUANTITY-ON-NON-FLOAT` | `quantity` on bool/int/str/enum/id/record | remove it |
| `IR-NON-SI-UNIT` | catalogue `unit` is prefixed, affine, gauge or logarithmic | use the coherent SI unit |
| `IR-DIMENSION-MISMATCH` | catalogue `unit` and `dimension` disagree; or a port domain is not power-conjugate | correct the row |
| `IR-ARRAY-SPEC` | array without `dtype`/`shape`, bad dtype, or `dtype`/`shape` on a non-array | complete or remove |
| `IR-BREAKING-WITHOUT-MIGRATION` | a breaking change with tracked records still in the old shape | migrate them in the same change |
| `IR-VERSION-NOT-BUMPED` | schema changed, `schema_version` did not | bump it |
| `IR-OLD-RECORD` | a reader met an older `schema_version` | the repo's migration command, named in the message |
| `IR-STALE-GENERATED` | generated file fingerprint differs | the regenerate command, named in the message |
| `IR-GENERATED-TRACKED` | a generated file is in git | `git rm --cached` it; it is ignored by design |
| `IR-NON-FINITE` | NaN or infinity at construction | fix the producer; SI floats are finite |
| `IR-BOUNDARY-UNIT` | input unit unparsable or of the wrong dimension | give a unit of the field's quantity |

## Worked example (illustrative)

Fixtures: `tests/data/ir_schema/schema.toml`, `quantities.toml`, `input_sample.toml`.

```toml
schema_version = 3

[enum.Finish]
values = ["raw", "painted", "anodized"]

[record.Widget]
[record.Widget.field.id]
type = "id:Widget"
[record.Widget.field.finish]
type = "enum:Finish"
[record.Widget.field.mass]
type = "float"
quantity = "mass"
[record.Widget.field.operating_temperature]
type = "float"
quantity = "temperature"
optional = true

[record.Sample]
[record.Sample.field.widget]
type = "id:Widget"
[record.Sample.field.label]
type = "str"
[record.Sample.field.calibrated]
type = "bool"
[record.Sample.field.count]
type = "int"
[record.Sample.field.time]
type = "array"
dtype = "float64"
shape = ["n"]
quantity = "time"
[record.Sample.field.position]
type = "array"
dtype = "float64"
shape = ["n", 3]
quantity = "length"
[record.Sample.field.source]
type = "record:Widget"
optional = true
```

```toml
[quantity.mass]
unit = "kg"
dimension = "1 0 0 0 0 0 0"
[quantity.temperature]
unit = "K"
dimension = "0 0 0 0 1 0 0"
[port_domain.translational]
effort = "force"
flow = "velocity"
```

Boundary input `operating_temperature = "85 degC"` becomes `358.15`; `mass = "250 g"` becomes `0.25`.

### Generated Python (abridged)

```python
# ir-schema-fingerprint: sha256:<hex>
# GENERATED from schema.toml + quantities.toml; do not edit.
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import NewType

import numpy as np
from numpy.typing import NDArray

SCHEMA_VERSION = 3
WidgetId = NewType("WidgetId", str)


class IRValidationError(ValueError):
    pass


class Finish(Enum):
    raw = "raw"
    painted = "painted"
    anodized = "anodized"


@dataclass(frozen=True, slots=True, kw_only=True)
class Widget:
    """One manufactured widget."""

    id: WidgetId
    finish: Finish
    mass: float  # kg
    operating_temperature: float | None = None  # K

    def __post_init__(self) -> None:
        _check_str(self.id, "Widget.id")
        _check_enum(self.finish, Finish, "Widget.finish")
        _check_float(self.mass, "Widget.mass")
        if self.operating_temperature is not None:
            _check_float(self.operating_temperature, "Widget.operating_temperature")


@dataclass(frozen=True, slots=True, kw_only=True)
class Sample:
    """A measured trace taken from one widget."""

    widget: WidgetId
    label: str
    calibrated: bool
    count: int
    time: NDArray[np.float64]  # s, shape (n,)
    position: NDArray[np.float64]  # m, shape (n, 3)
    source: Widget | None = None

    def __post_init__(self) -> None:
        _check_str(self.widget, "Sample.widget")
        _check_str(self.label, "Sample.label")
        _check_bool(self.calibrated, "Sample.calibrated")
        _check_int(self.count, "Sample.count")
        dims: dict[str, int] = {}
        object.__setattr__(self, "time", _frozen_array(self.time, np.float64, ("n",), dims, "Sample.time"))
        object.__setattr__(
            self, "position", _frozen_array(self.position, np.float64, ("n", 3), dims, "Sample.position")
        )
        if self.source is not None and not isinstance(self.source, Widget):
            raise IRValidationError(f"Sample.source: expected Widget, got {type(self.source).__name__}")


def _frozen_array(value, dtype, shape, dims, path):
    if not isinstance(value, np.ndarray):
        raise IRValidationError(f"{path}: expected ndarray, got {type(value).__name__}")
    if value.dtype != dtype:
        raise IRValidationError(f"{path}.dtype: expected {np.dtype(dtype)}, got {value.dtype}")
    if value.ndim != len(shape):
        raise IRValidationError(f"{path}.ndim: expected {len(shape)}, got {value.ndim}")
    for axis, (want, got) in enumerate(zip(shape, value.shape)):
        if isinstance(want, str):
            want = dims.setdefault(want, got)
        if want != got:
            raise IRValidationError(f"{path}.shape[{axis}]: expected {want}, got {got}")
    if value.dtype.kind == "f" and not np.isfinite(value).all():
        raise IRValidationError(f"{path}: expected finite values, got NaN or infinity")
    out = np.array(value, copy=True, order="C")
    out.flags.writeable = False
    return out

# _check_str/_check_bool/_check_int/_check_float/_check_enum, to_canonical_json,
# from_canonical_json and content_hash follow the same pattern.
```

### Generated Rust (abridged)

```rust
// ir-schema-fingerprint: sha256:<hex>
// GENERATED into $OUT_DIR by build.rs; do not edit.
use ndarray::{Array1, Array2};
use serde::{Deserialize, Serialize};

pub const SCHEMA_VERSION: u32 = 3;

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct WidgetId(pub String);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Finish { Raw, Painted, Anodized }

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Widget {
    pub id: WidgetId,
    pub finish: Finish,
    /// kg
    pub mass: f64,
    /// K
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub operating_temperature: Option<f64>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Sample {
    pub widget: WidgetId,
    pub label: String,
    pub calibrated: bool,
    pub count: i64,
    /// s, shape (n,)
    pub time: Array1<f64>,
    /// m, shape (n, 3)
    pub position: Array2<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source: Option<Widget>,
}

#[derive(Debug, thiserror::Error)]
#[error("{path}: expected {expected}, got {got}")]
pub struct IrValidationError { pub path: String, pub expected: String, pub got: String }

impl Sample {
    pub fn validate(&self) -> Result<(), IrValidationError> {
        let n = self.time.len();
        if self.position.nrows() != n {
            return Err(IrValidationError {
                path: "Sample.position.shape[0]".into(),
                expected: n.to_string(),
                got: self.position.nrows().to_string(),
            });
        }
        if self.position.ncols() != 3 {
            return Err(IrValidationError {
                path: "Sample.position.shape[1]".into(),
                expected: "3".into(),
                got: self.position.ncols().to_string(),
            });
        }
        // finiteness of mass, time, position; source.validate() when present
        Ok(())
    }
}

#[cfg(feature = "pyo3")]
mod py { /* FromPyObject / IntoPyObject for each record, via the numpy crate */ }
```

## Open questions for review

1. **Symbolic dims**: scope is one record here. Should a dim bind across nested records (a parent's `n` equal to
   a child's), and may a schema declare a dim's bounds (`n >= 1`)?
2. **Nested arrays and lists of records**: `array` holds numeric dtypes only. Is a `list:<type>` (e.g. a list of
   `record:Sample`) needed, and is a ragged array ever needed?
3. **Map types**: `map:<key>:<value>` (str or id keys)? Canonical form would sort by key.
4. **Defaults**: only optionals default (to absent). Should a required field allow a declared default, and does
   a default count as additive?
5. **Gauge pressure and dB references**: where is the reference declared -- per field in the schema, per value at
   the boundary, or per quantity in the catalogue? Same for the dB reference (20 uPa, 1 V, ...).
6. **Complex numbers**: a `complex128` dtype and a `complex` scalar type for phasors? Canonical form `[re, im]`?
7. **Multiple schema files and cross-repo IRs**: one file per repo, or a set? Can one repo import another's
   records (a contracts leaf shared by two repos), and whose `schema_version` governs?
8. **Enum evolution**: is adding an enum value additive (readers) or breaking (exhaustive Rust `match`)?
   `#[non_exhaustive]` would make it additive at a cost to callers.
9. **Quantity on int**: counts (turns, poles) are dimensionless; is `quantity` ever wanted on `int`?
10. **Array canonical form**: nested JSON lists are readable but large; for big arrays, is a base64 little-endian
    form (with dtype and shape) preferred, and is the hash then over that?
11. **Migration command**: is it a per-repo declared command, or a generated `migrate_<from>_to_<to>` hook the
    repo fills in?
12. **Where `verify` runs**: as a dev-lab check over the declared paths, and at import time of the generated
    module (cheap fingerprint compare), or only the former?
