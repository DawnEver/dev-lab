"""The machine-file merge keeps every unrelated byte and refuses a result that does not read back."""

from __future__ import annotations

import tomllib

import pytest

from lab_commons.dev._machinefile import diff, merged

HAND: str = (
    '# this box\n[hpc]\n\n[[hpc.grant]]\nuser = "me"  # mine\ncpus = 96\n\n'
    '[capabilities.jmag]\nseats = 4  # measured here\n\n[serve]\nown_weight = 2\n'
)


def test_an_absent_table_is_appended_and_every_other_line_kept() -> None:
    out = merged(HAND, {'capabilities.node': {}, 'serve': {'repos': ['a', 'b']}})
    assert out.startswith(HAND.rstrip('\n'))
    parsed = tomllib.loads(out)
    assert parsed['capabilities'] == {'jmag': {'seats': 4}, 'node': {}}
    assert parsed['serve'] == {'own_weight': 2, 'repos': ['a', 'b']}
    assert parsed['hpc']['grant'] == [{'user': 'me', 'cpus': 96}]


def test_an_equal_value_keeps_its_line_and_comment_so_a_second_merge_is_a_no_op() -> None:
    wanted = {'capabilities.jmag': {'seats': 4}, 'serve': {'own_weight': 2}}
    assert merged(HAND, wanted) == HAND
    once = merged(HAND, {'serve': {'repos': ['x']}})
    assert merged(once, {'serve': {'repos': ['x']}}) == once


def test_a_different_value_replaces_only_its_own_line() -> None:
    out = merged(HAND, {'capabilities.jmag': {'seats': 2}})
    assert diff(HAND, out, 'c').count('\n-') == 1
    assert '-seats = 4  # measured here' in diff(HAND, out, 'c')
    assert tomllib.loads(out)['capabilities']['jmag'] == {'seats': 2}


def test_a_merge_that_would_break_the_file_is_refused() -> None:
    inline = '[capabilities]\njmag = { seats = 4 }\n'
    with pytest.raises(ValueError, match='edit it by hand'):
        merged(inline, {'capabilities.jmag': {'seats': 4}})


def test_an_empty_file_gets_the_tables() -> None:
    assert tomllib.loads(merged('', {'serve': {'own_weight': 2.5}})) == {'serve': {'own_weight': 2.5}}
    assert diff('a\n', 'a\n', 'c') == ''
