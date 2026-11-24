# IR schemas: one TOML declaration, generated Python and Rust

A repo declares its intermediate representations (IR) once, as TOML. Python and Rust types, their
validation, the unit codec and the canonical serialization are generated from it. Nothing generated is
committed.

- The schema is the single source of truth for a record's shape. The quantities catalogue is the single
  source of truth for a quantity's SI unit.
- Units exist only at the boundary. Generated types hold linear, absolute SI values and nothing else.
- dev-lab hard-codes no path: the repo declares every path in its `pyproject.toml`.
- The generator is `dev_lab.dev.irschema` (CLI: `python -m dev_lab.dev.irschema --help`).
- The worked example is a fixture repo: `tests/data/ir_schema/repo/`.

## The declaration

```toml
[tool.dev_lab.ir_schema]
version = "1.4.0"                    # MAJOR.MINOR.PATCH: the repo's ONE version epoch
package = "sample_pkg"               # importable package the Python modules go into
package_dir = "src/sample_pkg"       # its directory, relative to the repo root
quantities = "ir/quantities.toml"
migrations = "sample_pkg.ir_migrations"   # module holding MIGRATIONS (see Reading and migration)

[tool.dev_lab.ir_schema.modules]     # several schema files; one generated module each
widgets = "ir/widgets.toml"          # -> sample_pkg/_ir_widgets.py, Rust mod ir_widgets
samples = "ir/samples.toml"

[tool.dev_lab.ir_schema.external]    # another repo's IR: alias -> its generated Python module
base = "other_pkg._ir_base"          # which embeds its schema as SCHEMA_TOML

[tool.dev_lab.ir_schema.external_rust]   # the same alias -> its Rust module path
base = "other_crate::ir::ir_base"
```

A repo with no `[tool.dev_lab.ir_schema]` has no IR, and every IR check is silent for it.

## A schema file

```toml
[dim.n]                               # optional bounds of a symbolic dim
min = 1                               # and/or max = <int>

[enum.<Name>]
values = ["a", "b"]                   # non-empty, unique, lower_snake

[record.<Name>]
doc = "..."
[record.<Name>.field.<name>]
type = "float"                        # see the table
optional = false                      # default false; a required field never has a default
quantity = "<quantity>"               # float, complex and float/complex arrays only
doc = "..."
dtype = "float64"                     # arrays only
shape = ["n", 3]                      # arrays only: ints and symbolic dims
unique_by = "id"                      # list:record:<R> only
csr_values = "<array field>"          # int64 1-d array only: this is the CSR offsets of that field
gauge_reference = "<float field>"     # pressure only: gauge at the boundary, relative to that field
```

| `type` | Python | Rust | Canonical JSON |
|---|---|---|---|
| `bool` | `bool` | `bool` | `true` / `false` |
| `int` | `int` (signed 64-bit) | `i64` | decimal |
| `float` | `float` (finite) | `f64` | float rule |
| `complex` | `complex` (finite) | `Complex` (`re`, `im`) | `[re, im]` |
| `str` | `str` | `String` | string |
| `enum:<E>` | `Enum` subclass | `enum` (exhaustive) | value string |
| `record:<R>` | the dataclass | the struct | object |
| `id:<R>` | `NewType('<R>Id', str)` | `struct <R>Id(String)` | string |
| `list:<type>` | `tuple[T, ...]` | `Vec<T>` | array |
| `array` | `NDArray[np.<dtype>]`, read-only | `ndarray::ArrayD<T>` | `{"data": base64, "shape": [...]}` |

- A reference `<R>` or `<E>` is local, `<module>.<R>` for another module of this repo, or `<alias>.<R>`
  for an external one. The owner repo's version governs its records.
- Records and enums are `UpperCamel`; fields and enum values are `lower_snake`.
- `dtype`: `bool`, `int32`, `int64`, `float32`, `float64`, `complex128`.
- `id:<R>` needs `<R>` to have a field `id` of type `id:<R>`.
- **Symbolic dims** are scoped to the whole top-record tree: every array under one top-level record that
  names `n` has the same extent. `[dim.<n>]` bounds apply everywhere `n` is used.
- **Lists**: `list:<type>` nests one level and holds no `array` (a list of arrays is a list of records). A
  `unique_by = "id"` list refuses duplicates and is stored and serialized in ascending id order. It is
  the IR's map: there is no map type.
- **Ragged data** is explicit CSR. An int64 `offsets` array names its values with `csr_values`. Offsets
  start at 0, never decrease and end at the values' first extent.
- No quantity on `int`; counts are pure numbers.

## The quantities catalogue

```toml
[quantity.<name>]
unit = "<coherent SI unit>"           # "m", "kg", "m/s", "K", "Pa"
dimension = "M L T I Theta N J"       # seven integer exponents, e.g. "1 1 -2 0 0 0 0"
db_reference = 2e-5                   # optional: the 0 dB value, in `unit`
db_scale = 20                         # with db_reference: 20 (field) or 10 (power)

[port_domain.<name>]
effort = "<quantity>"
flow = "<quantity>"                   # effort x flow must be a power ("1 2 -3 0 0 0 0")
```

`unit` is coherent SI: no prefix, no offset (`K`, never `degC`), absolute (`Pa`, never gauge), never `dB`.
`unit` and `dimension` must agree.

## Units cross once, at the boundary

- **The input codec** (`_ir_codec.from_boundary(Record, mapping)`) takes a number or a string with a unit (`"250 g"`,
  `"85 degC"`, `"94 dB"`).
- It converts once, through Pint, to the catalogue unit. A dimension mismatch is refused.
- Affine temperatures convert as absolute. A `gauge_reference` field converts the gauge value and adds the
  named field's absolute value.
- `dB` uses the quantity's `db_reference` and `db_scale`. A quantity without them refuses dB.
- **Output rendering** (`_ir_codec.to_boundary(record, {"field.path": "unit"})`) converts back to a requested
  display unit, gauge and dB included. Its output reads back through `from_boundary` unchanged.
- Generated types, canonical bytes and content hashes hold SI only. Pint is imported by the codec, never by
  the types.

## Versioning

`version` in the declaration is `MAJOR.MINOR.PATCH`, one per repo. The generator classifies a change by
diffing every schema file and the catalogue against the last commit.

| class | what changed | migration | what is retested |
|---|---|---|---|
| PATCH | docs only | none | none; regenerate |
| MINOR | new optional field, record, enum, enum value, quantity, port domain, dim, module | none | modules consuming the changed records, and their tests |
| MAJOR | anything else: a removed or renamed field, a changed type, dtype, shape or quantity, an optional made required, a removed enum value, a changed unit | tracked records migrate ONCE in the same change (`FORMATS-MIGRATE-ONCE`) | everything |

- A declared bump below the computed class is refused, and so is a change with no bump.
- A consumer of a record is a module that imports it from the generated module.
- `python -m dev_lab.dev.irschema affected` names the class and the consuming modules.
- `verify --changed` reads an IR change by its class. PATCH adds nothing, MINOR adds the consumers, and MAJOR
  adds `pyproject.toml`, which every test's footprint reaches. A `pyproject.toml` edit that only moves the IR
  version reaches nothing.
- A new enum value is MINOR. Rust's `match` stays exhaustive, so a Rust consumer fails to compile until it
  handles the value. That compile error is the retest.

## Canonical serialization and the content hash

One byte sequence per value; `content_hash = sha256(canonical bytes)`, hex.

- JSON (RFC 8259), UTF-8, no BOM, no insignificant whitespace, no trailing newline.
- Object keys are sorted by Unicode code point at every level.
- Absent optionals are omitted; `null` never appears. An added optional field keeps every old hash.
- `int`: decimal. `float`: Python `repr` -- the shortest round-trip digits, exponent form when the decimal
  exponent is below -4 or at least 16 (`1e-05`, `1e+16`, `0.0001`, `1.0`, `-0.0`). NaN and infinities are
  refused at construction.
- `str`: escape only `"`, `\` and U+0000..U+001F (`\b \f \n \r \t`, else `\u00XX` lowercase hex). No
  Unicode normalization.
- `complex`: `[re, im]`, each by the float rule.
- `array`: `{"data": "<base64>", "shape": [extents]}`. The data is standard base64 (with padding) of the
  C-order little-endian bytes. A complex element is `re` then `im`; a bool is one byte, 0 or 1.
- The dtype is the schema's. The extents are stored because a shape with two symbolic dims cannot be
  recovered from the byte count.
- A `unique_by` list is in ascending key order; any other list keeps its order.
- **The hash never includes the version.** A stored record is an envelope, and the hash is over `value`
  alone:

```json
{"record":"widgets.Widget","schema_version":"1.4.0","value":{...}}
```

## Reading and migration

- A reader accepts only the current shape.
- An envelope of an older MAJOR is refused by name, with the migrate door:
  `python -m dev_lab.dev.irschema migrate <path>`.
- A field it does not know is refused by name. From a newer MINOR the door is regenerate
  (`python -m dev_lab.dev.irschema generate`).
- The migrate door is generic. It runs the repo's registered functions, `MIGRATIONS: dict[int, Callable]`
  in the `migrations` module.
- Key `k` turns a MAJOR-`k` value into MAJOR `k+1`: `fn(record_name, value_dict) -> value_dict`. The door
  chains them and rewrites the file at the current version.

## Python output

`python -m dev_lab.dev.irschema generate` refuses a bump below the change's class, then writes `<package_dir>/_ir_<module>.py` for each module. The
files are git-ignored. No Pydantic; the runtime needs `numpy` only, and
the codec needs `pint`.

- Records are `@dataclass(frozen=True, slots=True, kw_only=True)`; `__post_init__` validates and
  normalizes. An array is copied C-contiguous and made read-only; a list becomes a tuple, sorted when
  `unique_by`.
- `IRValidationError(ValueError)` messages read `<path>: expected <x>, got <y>`, with a dotted path from the
  top record (`Batch.samples[2].position.shape[1]: expected 3, got 2`).
- Each record has `to_json() -> bytes`, `content_hash() -> str`, `from_json(bytes)`, `dump(path)` and
  `load(path)`. Equality is equality of canonical bytes.
- Beside the modules sit `_ir_runtime.py` (validation, canonical JSON, envelope, freshness; numpy only) and
  `_ir_codec.py` (the boundary; Pint), copied verbatim from `dev_lab.dev._ir_runtime` / `_ir_codec`.

- Ids live in one shared `_ir_ids.py`, and a field names its record or enum target as text resolved through the
  runtime's registry. Two modules may therefore reference each other: each imports the other only after
  defining its own classes.
- **At package build**, the hatchling hook `dev_lab.dev.irhatch` runs the same generation and ships the files
  in the wheel. A consumer declares it:

```toml
[build-system]
requires = ["hatchling", "dev-lab"]
build-backend = "hatchling.build"

[tool.hatch.build.hooks.ir-schema]
```

### Freshness

- The first line of a generated module is `# ir-schema-fingerprint: <sources>:<generator>`. The first
  half is the sha256 of this module's schema file, the catalogue and the declared version. The second is
  the generator's version.
- `python -m dev_lab.dev.irschema check` refuses a missing or stale module by name (`IR-STALE-GENERATED`).
  `verify` runs the same check on every run of a repo that declares an IR.
- At import, the module re-hashes its sources when they are present (an editable checkout) and raises
  `IR-STALE-GENERATED` on a mismatch. A wheel ships no sources: its module was generated in the same
  build.

## Rust output

The consuming crate's `build.rs` runs the generator into `OUT_DIR`; nothing is committed.

```rust
// build.rs
fn main() {
    let out = std::env::var("OUT_DIR").unwrap();
    let python = std::env::var("PYTHON").unwrap_or_else(|_| "python".into());
    let status = std::process::Command::new(python)
        .args(["-m", "dev_lab.dev.irschema", "rust", "--root", "..", "--out", &out])
        .status()
        .expect("python -m dev_lab.dev.irschema rust");
    assert!(status.success(), "IR generation failed; the line above names why");
    println!("cargo:rerun-if-changed=../ir");
    println!("cargo:rerun-if-changed=../pyproject.toml");
}
// lib.rs: include!(concat!(env!("OUT_DIR"), "/ir.rs"));
```

- One `mod ir_<module>` per schema module, written to `ir.rs`. Dependencies: `serde` (derive),
  `serde_json` and `ndarray`.
- Records derive `Serialize`/`Deserialize` with `deny_unknown_fields`; optionals are
  `Option<T>` with `skip_serializing_if`.
- `validate()` gives the same path messages as Python. `to_json()` writes the canonical bytes with a
  generated writer, because serde_json's float format and key order are not canonical.
- Behind the crate feature `pyo3` (pyo3 0.23 or later), `Record::from_py(&obj)` and `record.to_py(py)` convert
  to and from the Python dataclass through the canonical bytes.
- `tests/test_dev_irrust.py` builds the generated Rust offline and checks it against the Python: the same
  bytes for every fixture value, and the same error for a refused one.

## Refusals

| refusal | cause | door |
|---|---|---|
| `IR-UNKNOWN-TYPE` | a `type` not in the table, or a dangling reference | fix the name or declare the target |
| `IR-RECORD-CYCLE` | `record:` nesting reaches itself | break it with an `id:` reference |
| `IR-ID-WITHOUT-ID-FIELD` | `id:<R>` but `<R>` has no `id` field of that type | add the field |
| `IR-UNIT-IN-SCHEMA` | a unit where a quantity name belongs | name a catalogue quantity |
| `IR-UNKNOWN-QUANTITY` | a quantity missing from the catalogue | add it to the catalogue |
| `IR-QUANTITY-ON-NON-FLOAT` | a quantity on bool/int/str/enum/id/record/list or an int array | remove it |
| `IR-NON-SI-UNIT` | a catalogue unit that is prefixed, affine, gauge or logarithmic | use the coherent SI unit |
| `IR-DIMENSION-MISMATCH` | a catalogue unit disagrees with its dimension, or a port domain is not a power | correct the row |
| `IR-FIELD-SPEC` | a misplaced or incomplete key (`dtype`, `shape`, `unique_by`, `csr_values`, `gauge_reference`, `default`) | the message names the key |
| `IR-VERSION-NOT-BUMPED` | IR changed, version did not, or the bump is below the class | bump to at least the named class |
| `IR-OLD-RECORD` | a stored record of an older MAJOR | `python -m dev_lab.dev.irschema migrate <path>` |
| `IR-UNKNOWN-FIELD` | a stored record carries a field this reader does not know | regenerate; if MAJOR-older, migrate |
| `IR-NO-MIGRATION` | the migrate door finds no function for a MAJOR step | register it in `MIGRATIONS` |
| `IR-STALE-GENERATED` | a generated module is missing or its fingerprint differs | `python -m dev_lab.dev.irschema generate` |
| `IR-NON-FINITE` | NaN or infinity in a float, complex or array | fix the producer |
| `IR-BOUNDARY-UNIT` | a boundary unit unparsable, of the wrong dimension, or dB without a reference | give a unit of the field's quantity |

## Worked example

The fixture repo `tests/data/ir_schema/repo/` declares two modules.

- `widgets` holds the enum `Finish` and the record `Widget`, which has a gauge pressure.
- `samples` holds `Sample` (a complex gain, `n`-shaped arrays, a list and an optional dB-capable level)
  and `Batch` (a `unique_by` widget list and a CSR pair).

To read the exact output, copy the fixture repo to a scratch directory and run
`python -m dev_lab.dev.irschema generate --root <copy>`. An abridged excerpt:

```python
# ir-schema-fingerprint: 3f0c...:0.4.2
@dataclass(frozen=True, slots=True, kw_only=True)
class Widget:
    """One manufactured widget."""

    id: WidgetId
    finish: Finish
    mass: float  # kg
    ambient_pressure: float  # Pa
    seal_pressure: float  # Pa; gauge at the boundary, relative to ambient_pressure
    operating_temperature: float | None = None  # K
```

```rust
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Widget {
    pub id: WidgetId,
    pub finish: Finish,
    pub mass: f64,
    pub ambient_pressure: f64,
    pub seal_pressure: f64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub operating_temperature: Option<f64>,
}
```
