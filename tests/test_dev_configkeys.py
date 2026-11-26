"""The config-key scan finds a unit spelled into a key on every surface it claims, and passes the new shape.

Each arm has a PLANTED case (`PLANTED-CONTROL`): the defect written where the arm looks, found; and the same table in
the new shape (``memory = "32 GiB"``), passed -- so a scan that cannot say no would red here first.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev import configkeys
from dev_lab.dev.configkeys import RULE, Site, markdown_sites, refusal, schema_sites, toml_sites, unit_token


@pytest.mark.parametrize(
    ('key', 'token'),
    [
        ('memory_gb', 'gb'),
        ('max_idle_hours', 'hours'),
        ('wall_s', 's'),
        ('tick-minutes', 'minutes'),
        ('journal_max_mb', 'mb'),
        ('timeout-minutes', 'minutes'),
        ('shard_minutes_min', 'min'),
        ('seconds', 'seconds'),
        ('cpu_pct', 'pct'),
        ('wave_hours_max', 'hours'),
        ('disk_percent_ceiling', 'percent'),
    ],
)
def test_a_key_that_spells_its_unit_is_named_with_its_token(key: str, token: str) -> None:
    assert unit_token(key) == token


@pytest.mark.parametrize(
    'key',
    [
        'memory',
        'max_idle',
        'tick',
        'cores',
        'logical_cores',
        'jobs',
        'roots',
        's',
        'min_age',
        'h_index',
        'max_merges_max',
    ],
)
def test_a_key_without_a_unit_passes(key: str) -> None:
    """The control: the new shape, a plural, and a lone letter that is no unit word all pass."""
    assert unit_token(key) is None


def test_every_toml_depth_is_read_arrays_of_tables_included() -> None:
    text = (
        '[dev.resources]\ncores = 8\nmemory_gb = 32\n\n'
        '[[components.process_monitor.processes]]\nname = "x"\nmax_rss_mb = 500\n'
    )
    found = toml_sites(text, 'host.toml')
    assert [s.key for s in found] == ['dev.resources.memory_gb', 'components.process_monitor.processes[].max_rss_mb']
    assert found[0].where == 'host.toml:3'
    assert toml_sites('[dev.resources]\ncores = 8\nmemory = "32 GiB"\n', 'host.toml') == []


def test_an_unreadable_toml_is_refused_not_passed() -> None:
    with pytest.raises(ValueError, match='not TOML'):
        toml_sites('[dev\nmemory_gb = ', 'broken.toml')


def test_a_documented_block_is_read_whole_or_line_by_line() -> None:
    page = (
        '# Guide\n\n```toml\n[ssh.hold]\nmax_hours = 24\n```\n\nprose memory_gb = 1 is not a block\n\n'
        '```toml\n...\ntick_minutes = 15   # an excerpt, not whole TOML\n```\n'
    )
    found = markdown_sites(page, 'guide.md')
    assert [(s.where, s.key) for s in found] == [('guide.md:5', 'ssh.hold.max_hours'), ('guide.md:12', 'tick_minutes')]
    assert markdown_sites('```toml\n[ssh.hold]\nmax_age = "24 h"\n```\n', 'guide.md') == []


def test_a_declared_schema_constant_is_read() -> None:
    source = (
        'from typing import Final\n'
        "RESOURCES: Final = {'cores': int, 'memory_gb': (int, float)}\n"
        "_KEYS = frozenset({'trunk', 'max_idle_hours'})\n"
        "LIMITS: Final = {'memory_gb': 3}\n"  # a dict of numbers named neither KEYS nor SCHEMA: no schema
        "_ANSWER = {'wall_s': 1}\n"
    )
    found = schema_sites(source, 'm.py')
    assert [s.key for s in found] == ["RESOURCES['memory_gb']", "_KEYS['max_idle_hours']"]
    assert schema_sites("RESOURCES: Final = {'memory': (int, float)}\n", 'm.py') == []


def test_a_dataclass_that_names_its_table_is_that_tables_schema() -> None:
    source = (
        'from dataclasses import dataclass\n'
        '@dataclass(frozen=True)\n'
        'class Policy:\n'
        '    """The ``[retention]`` table over its defaults."""\n'
        '    min_age_hours: float = 6.0\n'
        '    target: float = 0.7\n'
        '@dataclass\n'
        'class Record:\n'
        '    """One run, as its JSON record holds it."""\n'
        '    wall_s: float = 0.0\n'
    )
    assert [s.key for s in schema_sites(source, 'm.py')] == ['Policy.min_age_hours']


def test_the_refusal_names_the_rule_the_key_and_the_door() -> None:
    said = refusal(Site('host.toml:3', 'dev.resources.memory_gb', 'gb'))
    assert said.startswith(f'{RULE}: host.toml:3: dev.resources.memory_gb')
    assert 'write memory = "<n> <unit>"' in said
    assert 'write wave_max = "<n> <unit>"' in refusal(Site('x.toml:1', 'ops.breakglass.wave_hours_max', 'hours'))
    assert 'lab_commons.quantity.parse' in said


def test_sites_in_reads_a_file_by_its_kind(tmp_path: Path) -> None:
    (tmp_path / 'a.toml').write_text('wall_s = 1\n', encoding='utf-8')
    (tmp_path / 'b.md').write_text('```toml\nwall_s = 1\n```\n', encoding='utf-8')
    (tmp_path / 'c.py').write_text("_KEYS = ('wall_s',)\n", encoding='utf-8')
    (tmp_path / 'd.json').write_text('{"wall_s": 1}', encoding='utf-8')
    found = {p: configkeys.sites_in(tmp_path / p, p) for p in ('a.toml', 'b.md', 'c.py', 'd.json')}
    assert {p: len(s) for p, s in found.items()} == {'a.toml': 1, 'b.md': 1, 'c.py': 1, 'd.json': 0}
