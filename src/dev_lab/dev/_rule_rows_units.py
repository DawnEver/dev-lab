"""The rules registry's UNITS rows -- pure DATA, the same row shape as ``_rule_rows.py``.

Every rule about where a physical unit lives: in the value, never in a name, a key or a bare tolerance.
"""

from __future__ import annotations

ROWS: tuple[tuple[str, str, tuple[str | tuple[str, str], ...]], ...] = (
    (
        'TOLERANCE-CARRIES-A-UNIT',
        (
            'A relative tolerance is free and an absolute one is not (`epsilon = 1e-10 * L` is a statement about '
            'the unit its inputs are in, so the same call in meters tightens a test by 1000x): sweep for absolute '
            'tolerances BEFORE a rewrite, state the unit a golden was generated in, and never write a `rel=` '
            'without the `abs=` floor it is combined with.'
        ),
        ('tests/architecture/ratchets/test_approx_rel_requires_abs.py',),
    ),
    (
        'UNITS-GO-THROUGH-PINT',
        (
            'A unit is never spelled into a NAME but lives in the VALUE as a pint Quantity -- one rule, because '
            'once a name cannot carry a unit the value must, so `--slot-pitch-mm=12.5` typed as a bare float has '
            'nowhere left to keep its unit but pint -- and renaming such a flag without typing it DELETES the '
            'unit, which is worse than leaving it, while a name whose value IS already a Quantity is not a '
            'violation, since there the name merely repeats the unit.'
        ),
        (
            'tests/test_dev_units.py',
            'tests/test_no_name_carries_a_unit.py',
            # THE VALUE HALF, added 2026-09-16. The clause above about renaming-without-typing was
            # STATED here and enforced by nothing, so the name scan's cheapest green was the lossy
            # repair it warns against. `dev_lab.dev.quantity_values` is the mechanism, and it is
            # listed on THIS row rather than under a new ID because the row already argues the two
            # halves are one rule.
            'tests/test_dev_quantity_values.py',
        ),
    ),
    (
        'CONFIG-VALUES-CARRY-UNITS',
        (
            # Why: user ruling 2026-11-25 -- `memory_gb = 32` puts the unit in the key and leaves the number bare,
            # so nothing checks it; machine memory is written in GiB.
            'A config key never spells a size, duration or percentage unit (`memory_gb`, `max_idle_hours`, '
            '`wall_s`): its VALUE is a quantity string (`memory = "32 GiB"`, `max_idle = "12 h"`) that every '
            'reader parses ONCE through `lab_commons.quantity.parse`, which refuses a bare number, another '
            'dimension or an unknown unit by key. A retired unit-suffixed key is never read: its reader refuses it '
            'by name with the replacement line written from its own value (`refuse_renamed`). The architecture '
            'suite scans every tracked TOML file, every documented `toml` block and every declared schema '
            '(`dev_lab.dev.configkeys`).'
        ),
        ('tests/test_dev_configkeys.py', 'tests/test_config_keys_carry_no_unit.py'),
    ),
)
