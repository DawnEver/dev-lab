"""The tree declares no config key that spells its unit (`CONFIG-VALUES-CARRY-UNITS`, user ruling 2026-11-25).

`tests/test_dev_configkeys.py` proves the scan works on planted text; this proves the tree it ships in is clean, on
every surface the scan claims (:mod:`dev_lab.dev.configkeys`): each tracked TOML file, each ``toml`` block of the
guide, and each declared schema in ``src/``. Each surface has a floor, so a scan that stopped reaching the tree reds
instead of reading clean. ``tests/`` is not a surface: a test PLANTS the retired keys its reader must refuse.

THE EXEMPTIONS ARE A NAMED SET, each with its reason, and two-sided: an exemption no site uses reds.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from dev_lab.dev.configkeys import Site, refusal, sites_in
from dev_lab.dev.rules import tracked_files

_ROOT: Final = Path(__file__).resolve().parents[1]

#: ``path: key`` -> why it is not a config key this repo declares.
_EXEMPT: Final = {
    'src/dev_lab/dev/ci_base.toml: ci.yml.jobs.part.timeout-minutes': (
        "the forge's own workflow vocabulary (GitHub/Gitea `timeout-minutes`), emitted by the renderer"
    ),
    "src/dev_lab/dev/artifactfolder.py: _MANIFEST_KEYS['bytes']": (
        'a JSON manifest field of an artifact folder (a record, not config: UNITS-GO-THROUGH-PINT`s JSON half)'
    ),
}

#: Floors MEASURED 2026-11-25 (files read per surface), set below the count so growth never reds.
_FLOORS: Final = {'toml': 5, 'guide': 30, 'schema': 500}


def _surface(name: str) -> list[str]:
    files = sorted(tracked_files(_ROOT))
    if name == 'toml':
        return [f for f in files if f.endswith('.toml') and not f.startswith('tests/')]
    if name == 'guide':
        return [f for f in files if f.endswith('.md') and (f.startswith('docs-src/') or '/' not in f)]
    return [f for f in files if f.startswith('src/') and f.endswith('.py')]


def _sites(name: str) -> list[Site]:
    files = _surface(name)
    assert len(files) >= _FLOORS[name], f'the {name} surface read {len(files)} files, under its floor {_FLOORS[name]}'
    return [site for f in files for site in sites_in(_ROOT / f, f)]


def _key(site: Site) -> str:
    return f'{site.where.rsplit(":", 1)[0]}: {site.key}'


def _refused(name: str) -> list[str]:
    return [refusal(site) for site in _sites(name) if _key(site) not in _EXEMPT]


def test_no_tracked_toml_key_spells_its_unit() -> None:
    assert not (found := _refused('toml')), '\n'.join(found)


def test_no_documented_toml_key_spells_its_unit() -> None:
    assert not (found := _refused('guide')), '\n'.join(found)


def test_no_declared_schema_key_spells_its_unit() -> None:
    assert not (found := _refused('schema')), '\n'.join(found)


def test_every_exemption_is_used() -> None:
    used = {_key(site) for name in _FLOORS for site in _sites(name)}
    assert not (stale := sorted(set(_EXEMPT) - used)), f'exempt but no longer found -- delete: {stale}'
