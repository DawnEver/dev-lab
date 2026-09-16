"""The unit-token registry, DATA half -- which name segments spell a unit, and which only look like they do.

THE RULE THIS SERVES, in the user's words: "all units must go through pint; forbid any spelling
like this: --slot-pitch-mm|slot_pitch_mm|conductor-width-mm". Read from first principles, the defect it names is a
BARE NUMBER WHOSE UNIT LIVES IN ITS NAME INSTEAD OF IN ITS VALUE: ``--slot-pitch-mm=12.5`` tells a
reader the unit and hands pint nothing, so the value stays a unitless float and nothing can convert
it. While a name MAY carry a unit, spelling the unit into the VALUE stays optional; once the name is
forbidden to carry one, the value is the only place left. THE NAMING BAN IS THEREFORE WHAT MAKES PINT
NON-OPTIONAL, which is why this half exists: the pint half is :mod:`lab_commons.units`, and the
machinery that reads this table is :mod:`lab_commons.dev.units`.

WHAT A ROW IS. A trailing name SEGMENT -- the text after the last ``_`` or ``-`` -- that a reader
would take for a unit. Matching is on the LAST segment only (``radial_gap`` is not a violation,
``gap_rad`` is), case-insensitively, and EXACTLY: ``mm2`` is a row, ``1mm`` is not, so the family's
``Q_1mm``/``Q_0Nm`` constants -- whose values ARE pint Quantities -- are not flagged by accident.

WHY THE SINGLE LETTERS ARE DECLARED RATHER THAN OMITTED, AND THIS IS THE MEASURED PART. A scan that
silently omits metre -- core's own unit -- reads exactly like a scan that found none, so every symbol
considered and REJECTED is a row below, with the collision that rejected it. The brief this registry
serves states that a lone ``_s`` "is usually a plural" and a lone ``_a`` "is usually an article".
MEASURED 2026-09-15, over ``motronics-studio``'s ``src/``+``tests/`` (4046 modules) and over this
package's own tree, that is FALSE in the direction that matters here: the trailing single-letter
segments are dominated by REAL units -- ``_a`` 1914 rows (``RATED_PEAK_A``), ``_t`` 1253, ``_n`` 1063
(``--top-n``), ``_m`` 842 (``PROBE_DEPTH_M``), ``_k`` 674 (``_SAME_TEMPERATURE_K``), ``_v`` 611
(``BUS_V``), ``_s`` 608 (``DEAD_TIME_S``). So the exclusions below are a KNOWING GAP rather than a
claim of rarity, and the honest repair is the one the machinery already supports::
``scan_files(paths, tokens=UNIT_TOKENS | {'m', 's'})`` lets a domain repo opt in, and every
:class:`~lab_commons.dev.units.Scan` REPORTS the token set it used, so an opt-in is visible in the
record rather than silent.

THE OTHER SIDE OF THE SAME MEASUREMENT, which is why the conservative set is the right DEFAULT for a
shared package: ``ns`` is nanoseconds in motronics (54 rows, ``_SSC_CAP_NS``) and argparse's
``Namespace`` in lab-commons (32 rows, every one ``ns = parser.parse_args()``); ``_sec`` is a SECTOR
(``n_sec`` x102) and a transformer SECONDARY WINDING (``l_sec``) far more often than it is seconds, so
the plural ``secs`` -- unambiguously a duration -- is the row that stays; ``_kw`` is ``**kwargs``
plumbing in 489 rows and a kilowatt in none; ``_m`` appears in ``Q_0A_per_m``/``Q_0Wb_per_m`` in
:mod:`lab_commons.em`, where the unit is already in the value and the name merely says so out loud. A
shared default that flagged those would red on code that already obeys the rule, and a guard that reds
on correct code is the one that gets widened.

THE MEASUREMENTS, and both instruments, because a count from one sweep is a claim. Instrument A is the
PRODUCTION path -- :func:`~lab_commons.dev.units.scan_files` over each repo's git-tracked files, so
PARAMETERS and module/class-scope assignments only, which is the surface this table actually governs.
Instrument B is a raw-text census: every identifier-shaped run in the tracked tree, scored on its
COMPLETE FINAL segment (``[_-]`` separated, no prefix matching -- a pattern that scored ``mm`` inside
``mm2`` once produced a 9,735-hit flood that was pure artifact), over ``.py``. The two AGREE on the
READING of every row below, which is the verdict this table needs, and they DISAGREE on magnitude
wherever a collision lives in a function local or in prose -- ``_pm`` is 924 rows and 63 violations in
motronics, ``_ft`` 78 rows and 1 -- because B counts the whole tree and A counts interfaces. The scope
of the counts quoted in the reasons is every git-tracked ``.py`` in the four repos the table is shared
by -- ``motronics-studio`` (``src/``, ``tests/``, ``cases/``, ``scripts/``), ``wdg-lab``,
``optimi-lab`` and this package -- minus the three files that cannot be written without the forbidden
spelling in them (this one, ``dev/units.py``, ``tests/test_dev_units.py``); see the note above
:data:`EXCLUDED_TOKENS` for why that subtraction is a correction rather than a convenience.

WHAT IS NOT HERE. Spelled-out unit words (``millimetres``, ``seconds``): the family writes symbols --
measured, the longest time spelling in either tree is ``_sec``. ``deg_c``/``deg_f``, whose trailing
segment is the excluded ``c``/``f``: that is a violation this registry cannot SEE, named here rather
than left for a reader to discover. And the registry is not exhaustive by design: a unit absent from
both tables (``tonne``, ``slug``, ``knot``) is OUT OF SCOPE rather than declared safe, so extending
the guard is adding a row here, which is the whole point of the data/checks seam.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

__all__ = ['EXCLUDED_TOKENS', 'UNIT_TOKENS']

#: The trailing segments a name must not end in. SORTED and LOWER-CASE, both as data properties
#: rather than style: a sorted table makes the diff of a removal readable, and the machinery compares
#: a lower-cased segment against these rows, so a row that is not lower-case could never match and
#: would sit in the table looking like coverage.
#:
#: EVERY ROW HERE IS A SYMBOL THE FAMILY ACTUALLY WRITES IN A NAME, and the AREA AND VOLUME rows are
#: the pair that made the rule visible: ``mm2`` had been carried alone since the first draft while its
#: siblings ``m2``/``cm3``/``mm3`` were absent, which a reader could only read as an oversight rather
#: than a decision. ``m3`` is the one that mattered most -- 185 rows, ``volume_m3`` x81,
#: ``density_kg_per_m3`` -- because a density is the single most unit-carrying quantity in a motor
#: case library. ``wb`` (weber, 57 rows, ``flux_wb``/``flux_d_q_wb``/``flux_linkage_wb``) and ``uh``
#: (microhenry, 19 rows, ``ld_uh``/``lq_uh``) are the same argument from the magnetics side.
UNIT_TOKENS: Final[tuple[str, ...]] = (
    'ah',
    'atm',
    'cm',
    'cm3',
    'deg',
    'ghz',
    'gpa',
    'gw',
    'hrs',
    'hz',
    'kcal',
    'kev',
    'kg',
    'kgf',
    'khz',
    'kj',
    'kn',
    'kohm',
    'kpa',
    'kv',
    'kva',
    'kwh',
    'lbf',
    'lpm',
    'm2',
    'm3',
    'mah',
    'mev',
    'mg',
    'mhz',
    'mil',
    'mins',
    'mj',
    'ml',
    'mm',
    'mm2',
    'mm3',
    'mol',
    'mpa',
    'mrad',
    'ms',
    'mv',
    'mwh',
    'nm',
    'ohm',
    'oz',
    'pa',
    'rad',
    'rpm',
    'secs',
    'slpm',
    'thou',
    'torr',
    'ug',
    'uh',
    'um',
    'va',
    'wb',
    'yd',
    'µm',
)

#: Every symbol considered and REJECTED, with the collision that rejected it. A reason is not
#: decoration: an exemption or an exclusion whose reason is not recorded cannot be told from a hole
#: somebody widened to make a red suite green, and it is the exclusion that gets widened because it
#: is the cheaper repair. A blank one is REFUSED by
#: :func:`~lab_commons.dev.units.assert_registry_sane`. Every count below is a MEASUREMENT taken
#: 2026-09-15 under the two instruments the module docstring names -- instrument B's row counts over
#: ``.py`` first, because a row count is what says WHAT the family reads a segment as, with the
#: production-path violation count alongside it wherever the token is currently included. "rows" is
#: instrument B (names whose COMPLETE FINAL segment is the token); "violations" is instrument A (the
#: same names in a parameter or a module/class-scope assignment), which is why the second number is
#: always the smaller one and is the number that justifies a REMOVAL from the table above.
#:
#: THE CENSUS EXCLUDES THIS FILE AND ITS TWO SIBLINGS, and that is a correction rather than a
#: convenience: a raw-text census counts PROSE, this registry has to write every excluded spelling down
#: in it, and the first run of the sweep duly found `power_meters` and `_cal` -- twice, in the two
#: reasons that had cited them as evidence. A reason that quotes itself is circular. The three files
#: left out are this one, ``dev/units.py`` and ``tests/test_dev_units.py``, which are exactly the three
#: that cannot be written without the forbidden spelling in them. The trees are LIVE and their file
#: lists move, so a re-measurement a few rows either way is expected; the shape of every row is not.
EXCLUDED_TOKENS: Final[Mapping[str, str]] = {
    'a': (
        'ampere -- and it is the LARGEST real category measured: 1914 trailing `_a` rows, and they '
        'are amperes (`RATED_PEAK_A`, `PLANTED_CURRENT_A`). Excluded anyway, because a lone `a` is '
        'also area, amplitude and an article, and this table is the SHARED default rather than one '
        "repo's: a domain repo opts in with tokens=UNIT_TOKENS | {'a'} and the Scan says so."
    ),
    'amp': (
        'ampere -- the symbol is `A`; `_amp` is an amplifier or an amplitude, measured 91 rows '
        '(`RESP_FLUX_AMP`, `V_AMP`).'
    ),
    'b': (
        'byte/bel -- measured 1427 rows of `_b`, dominated by `B` for FLUX DENSITY, which is a '
        'quantity rather than a unit: a `_b` name does not tell a reader which unit to use, so there '
        'is nothing for the ban to recover.'
    ),
    'bar': (
        'bar (pressure) -- 836 `_bar` rows measured, 134 distinct, and ZERO of pressure: the reading is '
        'a BUS BAR (`bus-bar` x89, `calc_bus_bar` x37, `bus_bar` x26), a THRESHOLD to clear '
        '(`BELOW_THE_BAR` x37, `MET_THE_BAR` x31, `TORQUE_LABEL_MEAN_REL_BAR`), or an ASPECT ratio bar '
        '(`aspect_bar` x29, `QUAD_ASPECT_BAR` x24). Zero violations on the production surface. The '
        'earlier "82 rows, every one a THRESHOLD" undercounted the bus-bar half by an order of '
        'magnitude; the verdict is unchanged and the reason now carries the whole measurement.'
    ),
    'c': (
        'coulomb/celsius -- `_c` is a coefficient or a count as often (`H_c`, `_DIODE_TEMP_C`, '
        '`DEFAULT_TEMP_C` are celsius and ARE in scope for a repo that opts in); 866 rows.'
    ),
    'cal': (
        'calorie -- 0 `_cal` rows measured across the four repos: the spelling is never written in a '
        'name here, and neither is a calorie. Kept rather than deleted because a reader who asks whether '
        '`cal` is covered deserves an answer instead of an absence.'
    ),
    'd': ('day -- `_d` is a derivative index or a distance (`FLUX_LINKAGE_D`, `L_d`, `I_D`); 884 rows.'),
    'db': 'decibel -- `_db` is a database handle (`in_db`, `solver_db`), 28 rows.',
    'dl': (
        'decilitre -- 7 `_dl` rows measured and the reading is a download or a DIFFERENTIAL inductance '
        '(`_dl` x6, `cur-dL` x1); zero decilitres. A volume here is `m3`/`cm3`/`mm3`, added to the '
        'table above on the same measurement that removes this row.'
    ),
    'dm': (
        'decimetre -- 4 `_dm` rows measured, ONE distinct (`_Dm`, a test-double class standing in for a '
        '`DiscreteModel`), and the two production violations are `dm` bound to a real `DiscreteModel` '
        '(`_assign(study, dm)` in the JMAG parametric route). Zero decimetres: the family is SI and '
        'writes lengths in `mm`, and this token spends its whole budget on a MODEL.'
    ),
    'ev': (
        'electronvolt -- 28 `_ev` rows measured, ONE distinct (`t_ev`), and every site is an EVENT time: '
        '`located = sorted(t_ev for _, t_ev in solution.events)` in the laplace switch and fault tests. '
        'One violation, also an event. The family writes no electronvolt, and a guard holding this row '
        'would refuse the timestamp of a zero-crossing.'
    ),
    'f': ('farad -- `_f` is frequency, force or field as often (`C_F`, `_REFERENCE_BETA_ON_F`); 169 rows.'),
    'fm': (
        'femtometre / FEMM -- 28 `_fm` rows measured, two distinct (`srdab_fm` x26, `test_srdab_fm` x2), '
        'and both are the FREQUENCY-MODULATED drive control law: `laplace/control/laws/fm_drive.py` is '
        'titled "Frequency-modulated drive controller" and exports `srdab_fm_law`/`SRDABFmParameters`. It '
        'is not the vendor either -- `hamilton/adapters/femm` spells FEMM out, and no name measured here '
        'abbreviates it. The single violation, `fm`, is a `field_map` in a mesh-diagnostics test.'
    ),
    'fs': (
        'femtosecond -- `_fs` is a FILESYSTEM (`want_fs`, `_fs`), 21 rows. A prefix of a unit is not a '
        'unit: the family time symbols stop at `ns`, and a scan that flagged `_fs` would find the '
        'filesystem it is standing on.'
    ),
    'ft': (
        'foot -- 78 `ft` occurrences measured and ONE distinct spelling, the bare `ft`, which is a '
        'function PARAMETER in `hamilton/torque_extraction/harmonic.py` where `fr`/`ft` are the radial '
        'and the TANGENTIAL force component. Zero `_ft` rows in a name: the family is SI and its '
        'lengths are `mm`, so this token has never seen a foot, and the one violation it produces is a '
        'force component.'
    ),
    'g': 'gram -- `_g` is gain, gap or gradient (`_STEEL_G`, `air_g`, `az_g`); 263 rows.',
    'gal': 'gallon -- 2 rows measured (`a_gal`), neither a volume; the family is SI.',
    'gauss': (
        'gauss -- the symbol the module docstring used to name as OUT OF SCOPE, now measured and so '
        'declared instead: 72 `_gauss` rows, 11 distinct, and every one is GAUSSIAN QUADRATURE '
        '(`arkkio_torque_quad_gauss` x17, `x2-Gauss` x17, `_GAUSS` x14, `n_gauss`, `stiffness_gauss`). '
        'In motronics `gauss` is additionally the NUMERICAL RUNTIME module (``gauss.solve_linear_'
        'system``), so a `_gauss` name points at the solver far more often than at the field unit.'
    ),
    'h': ('hour -- `_h` is height, a harmonic or a headroom (`_AIR_SEED_WALL_CLEARANCE_H`, `--min-age-h`); 341 rows.'),
    'hp': (
        'horsepower -- 2 `_hp` rows measured, both the BH-curve DERIVATIVE: `h, _hp = '
        '_bh_h_and_hprime(...)` in `core/materials/magnetic_runtime.py`. Zero violations, zero '
        'horsepower. The family is SI and writes power in `w`/`kw`, and `hrs` is the row kept above '
        'for the duration spelling.'
    ),
    'hr': (
        'hour -- 3 `_hr` rows measured, ONE distinct (`r_hr`, an archived SDM residual matrix in '
        '`attic/`), zero violations, zero hours. Durations here are seconds, and `hrs` stays in the '
        'table for the plural; `hr` itself is not a spelling the family writes.'
    ),
    'in': (
        'inch -- 3,167 `_in` rows measured, 227 distinct, and not one an inch: the dominant reading is '
        'an INNER radius (`r_in` x1197, paired with `r_out`), then the English words `opt-in` x282, '
        '`stand-in` x126, `built-in` x68, and then INPUTS (`_R_IN` x121, `R_IN` x67, `v_in` x59). The '
        'collision is the preposition, and it is the reason a two-letter unit can be as unusable as a '
        'one-letter one.'
    ),
    'j': ('joule -- `_j` is a loop index (`b_j`, `_j`), 277 rows, and an index is not a unit.'),
    'k': (
        'kelvin -- `_k` is a constant or a key (`K_B`, `_K`), 674 rows (`_SAME_TEMPERATURE_K` is '
        'kelvin and in scope for an opt-in).'
    ),
    'km': (
        'kilometre -- ZERO `_km` rows measured in a name across the four repos, and the two violations '
        'are `KM = 0.2  # motor constant k_t = k_e [N*m/A]` in two hamilton coupling tests. A distance '
        'here is never written in kilometres and a MOTOR CONSTANT is; the family works in `mm` and `m`.'
    ),
    'kw': (
        'kilowatt -- THE LARGEST false positive measured on this family, and the number that matters is '
        'the PRODUCTION one: 182 violations in a single repo (motronics, 14 distinct) and every one is '
        '`**kwargs` plumbing -- `mesh_kw: str` is a mesh KEYWORD, `band_kw`, `BAND_VARIANT_TO_KW` maps a '
        'band variant TO keyword arguments, `_airgap_kw = {...}` is splatted as `**_airgap_kw`. 489 '
        '`_kw` rows in the family, 1,106 in the raw tree, ZERO of them a kilowatt in a name: the real '
        'ones are in PROSE (`25.24 kW` of stator core loss; 25 occurrences of `kW`, every one a comment '
        'or a docstring). A token that reds 182 times on a tree that obeys the rule is the guard that '
        'gets widened, which is the failure this table exists to prevent.'
    ),
    'l': ('litre -- `_l` is length, level or lower (`BETA_L`, `_i_l`, `RL_L`), 178 rows.'),
    'lb': (
        'pound -- 13 `_lb` rows measured, four distinct, and all four a LOWER BOUND or a handle: '
        '`radius_lb`/`radius_ub` is the declared pair in `euclid/param_model/closed_shape.py`, plus '
        '`radius_slot_lb`, `r_lb` and `h_Lb` (a Simulink block handle). The one violation, in wdg-lab, '
        'is `def lb() -> int` -- a bound in a benchmark. Zero pounds: a mass is written in `kg` here.'
    ),
    'm': (
        'metre -- the biggest real category measured (842 rows, `PROBE_DEPTH_M`, `--depth-m`) AND '
        'the reason the default is conservative: `Q_0A_per_m`/`Q_0Wb_per_m` in `lab_commons.em` '
        'spell `m` in names whose VALUE is already a pint Quantity, so a naive `m` row reds on code '
        "that obeys the rule. Opt in per repo with tokens=UNIT_TOKENS | {'m'}."
    ),
    'meters': (
        'metre, spelled -- 0 `_meters` rows measured across the four repos. The symbol is the plural a '
        'MEASURING INSTRUMENT would take (`power_meters`), which is a device and not a unit, so admitting '
        'the row would admit the wrong thing; and nothing here writes a metre as a word at all.'
    ),
    'mi': 'mile -- `_mi` is mutual information; 8 rows measured, none of them a distance.',
    'min': (
        'minute -- 807 `_min` rows measured, 73 distinct, and every one a MINIMUM, which is the reading '
        'a reader takes first (`v_min` x119, `bend_radius_min` x76, `r_min`, `_F_MIN`, `theta_min`, '
        '`--b-min`). The family writes durations in seconds; `mins` stays in the table for the plural.'
    ),
    'n': (
        'newton -- `_n` is a count or a size (`--top-n`, `_DEFAULT_TOP_N`), 1063 rows, and a count '
        'is the one thing a plain `int` already is.'
    ),
    'ng': (
        'nanogram -- and the FAMILY reading wins, which is the same ruling `pm` gets: 141 `_ng` rows '
        'measured, 23 distinct, and the collision is overlap-free in both of its readings. It is the '
        'NGSPICE side of a cross-check -- `v_ng` x29 against `v_mna`, `t_ng` against `t_our`, `worst_ng`, '
        '`tol_ng`, `drift_ng`, `duty_ng` -- and, in the mesh code, a GROUP count (`ng = int('
        'tet_group_mat.max()) + 1`). Zero nanograms written anywhere in the four repos.'
    ),
    'ns': (
        'nanosecond -- the two-sided measurement, and the reason a SHARED default cannot hold it: '
        "nanoseconds in motronics (54 rows, `_SSC_CAP_NS`, `coarse_ns`) and argparse's `Namespace` "
        'in lab-commons (32 rows, every one `ns = parser.parse_args()`).'
    ),
    'ph': (
        'picohenry -- 170 `_ph` rows measured and every one PER PHASE: `n_unit_slot_ph` x36, '
        '`n_conductor_ph` x33, `n_h_unit_slot_ph`, `n_coil_ph`, and the per-phase circuit quantities '
        '`L_PH`/`R_PH`/`V_ph`. A winding design writes turns-per-phase orders of magnitude more often '
        'than it writes picohenries, and this table is the SHARED default.'
    ),
    'pm': (
        'picometre IN PHYSICS, PERMANENT MAGNET HERE -- and the family reading is the one a SHARED table '
        'has to hold, because all four repos are motor-design trees. MEASURED 924 `_pm` rows, 48 '
        'distinct, permanent magnet at every one: `psi_pm` x438, `lambda_pm`, `lam_pm`, `nu_pm`, `W_pm`, '
        '`flux_d_pm`, `surface-PM`, `interior-PM`, `buried-PM`. 63 violations in motronics and every one '
        'of them a permanent magnet, plus a third reading in wdg-lab where `ArcSeg.pm` is the arc MID '
        'POINT. Picometre is real physics and is not what any of these repos writes; a repo that wants '
        "it opts in per repo with tokens=UNIT_TOKENS | {'pm'}."
    ),
    'ps': (
        'picosecond -- 43 `_ps` rows measured, five distinct, and the reading is the Simulink-PS '
        'CONVERTER: `Simulink-PS` x35 is the BLOCK NAME the vendor ships and not ours to rename, and '
        '`_PS` is the generated handle (`h_{name}_PS`, `add_block(..._PS)`). `motronics_ps` is a circuit '
        'builder and `h_M1_PS` a generated signal. Zero violations and zero picoseconds.'
    ),
    'psi': (
        'pounds per square inch -- 5 `_psi` rows measured, two distinct (`_PSI` x3, `_psi` x2), and both '
        "are the GREEK LETTER used as FLUX LINKAGE: `_PSI = STATE_COLUMNS.index('psi_r')` in the "
        'sensorless-observer test, and `|psi|` as the B-proxy in `core/loss/flux_model.py`. Pressure '
        'here is `pa` (538 rows) and `mpa`; the psi spelling has never carried a pressure.'
    ),
    'pt': 'point -- 31 rows of `_pt` (`cur_pt`, `far_pt`) and every one a point on a curve, not a pint.',
    'rev': 'revolution -- `_rev` is a revision (`_rev`, `a_rev`, `d_rev`), 15 rows.',
    's': (
        "second -- and the brief's reason for excluding it does NOT survive the measurement: 608 "
        'rows in motronics (`DEAD_TIME_S`, `CEILING_S`, `--max-age-s`) and 14 in this package '
        '(`waited_s`, `interval_s`, `poll_s`) are seconds, and NOT ONE is a plural. It stays out '
        'because a lone letter is a weak anchor for a SHARED default and the family also uses `_s` '
        "on plural-style names; a domain repo should opt in with tokens=UNIT_TOKENS | {'s'}."
    ),
    'sec': (
        'second -- and this is a TWO-SIDED measurement, which is why a SHARED default cannot hold it (the '
        '`ns` shape again). 260 `_sec` rows measured, 29 distinct: 117 are a SECTOR (`n_sec` x102, whose '
        'own definition is `_n_sectors(grid)`, `_N_SEC = 8  # sectors per full ring`, `k_sec`), 26 a '
        'transformer SECONDARY winding (`l_sec`/`L_SEC`), and 71 genuinely SECONDS (`td_sec` x23, '
        '`filename_base_current_time_sec` x20, `t_sec`, `elapsed_sec`). That last group is a real loss '
        'and it is recorded here rather than left implicit. `secs` STAYS in the table above: `_secs` is '
        'unambiguous (`band_secs` x12), which is the same reason `hr`/`min` are out and `hrs`/`mins` in.'
    ),
    't': (
        'tesla/time -- 1253 rows, and `_t` reads as temperature, torque or a turn (`_CARRIER_T`, '
        '`_MIN_PEAK_BR_T`) as often as tesla; `kernel_t`/`user_t` in `lab_commons.proc` ARE seconds, '
        'so this is a real loss rather than a lucky one.'
    ),
    'u': ('atomic mass unit -- `_u` is a unit, an upper bound or a user (`bis_u`, `azp_u`), 545 rows.'),
    'us': (
        'microsecond -- ZERO DECLARED `_us` rows and exactly one row at all, and that one is a test '
        "FUNCTION's name (`test_an_opaque_job_handle_is_resolved_by_the_consumer_not_by_us`), which the "
        'scanner never reads. The single violation is a declared FIELD, '
        '`us: list[NDArray[np.floating]]` in `gauss/time_integrators/__init__.py`, which is the control '
        'INPUT u sampled over the steps; the other 356 occurrences are prose. Times here are `ns`, `ms` '
        'and `s`, and this token has never seen a microsecond.'
    ),
    'uv': (
        'microvolt -- 1,051 `_uv` rows measured and every one a CASE NAME: `ipm_uv` x891 and '
        '`pmasynrm_uv` x119 are the U-shape/V-shape magnet layouts two motor cases are named for, and '
        '`IPM_UV` x13 is the same name shouting. Two case families account for 1,047 of the 1,051 rows; '
        'zero microvolts.'
    ),
    'v': (
        'volt -- 611 rows, and in motronics they are volts (`BUS_V`, `LOSS_V`); excluded because '
        '`v` is also the conventional name of a validated VALUE -- `def validate(cls, v)` in '
        '`lab_commons.units` -- where flagging it would red on every pydantic validator in the family.'
    ),
    'var': (
        'volt-ampere reactive -- 274 `_var` rows measured, 19 distinct, and every one a VARIABLE: '
        '`n_var` x104, `sweep-var`/`sweep_var` x94 (a swept axis), `axis_var` x13, `env_var`/`ENV_VAR` '
        '(an environment variable), `block_var`, `flag_var`. Real power here is `w`/`kw`; the reactive '
        'spelling has never been written, and this row exists because a reader who asked for `var` would '
        'otherwise get no answer at all.'
    ),
    'w': ('watt -- `_w` is width or weight as often (`_KEY_W`, `--pm-loss-w`), 347 rows.'),
    'wh': (
        'watt-hour -- 4 `_wh` rows measured, ONE distinct (`_wh`, the WANT side of a mesh comparison: '
        '`for (_h, gms), (_wh, wms) in zip(got, want, strict=True)`), zero violations, zero watt-hours. '
        'Energy in this family is `j`/`kj`/`kwh`.'
    ),
}
