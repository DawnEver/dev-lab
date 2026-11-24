"""The notice door normalises licences, refuses an unknown one by name, and takes the product only as data."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from dev_lab.dev import notices
from dev_lab.dev.notices import UNKNOWN, NoticeData, UnknownLicense, normalize_license, notice_data, refuse_unknown

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ('raw', 'spdx'),
    [
        ('MIT License', 'MIT'),
        ('License :: OSI Approved :: BSD License', 'BSD-3-Clause'),
        ('(MIT OR Apache-2.0) AND Unicode-3.0', '(MIT OR Apache-2.0) AND Unicode-3.0'),
        ('Apache-2.0', 'Apache-2.0'),
        ('MIT/Apache-2.0', 'MIT OR Apache-2.0'),
        ('Copyright (c) 2020 someone\nPermission is hereby granted', UNKNOWN),
        ('Dual License', UNKNOWN),
        ('', UNKNOWN),
    ],
)
def test_a_raw_licence_normalises_to_spdx_or_unknown(raw: str, spdx: str) -> None:
    assert normalize_license('pkg', raw, overrides={}) == spdx


def test_an_override_outranks_the_metadata() -> None:
    assert normalize_license('pkg', 'Dual License', overrides={'pkg': 'MIT'}) == 'MIT'


def test_an_unknown_licence_is_refused_by_name_and_a_known_set_is_not() -> None:
    refuse_unknown([{'name': 'a', 'license': 'MIT'}])
    with pytest.raises(UnknownLicense, match='b, c'):
        refuse_unknown(
            [{'name': 'c', 'license': UNKNOWN}, {'name': 'a', 'license': 'MIT'}, {'name': 'b', 'license': UNKNOWN}]
        )


def test_the_product_is_data_and_its_absence_names_the_table(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "x"\n', encoding='utf-8')
    with pytest.raises(ValueError, match=r'\[tool.dev_lab.notices\]'):
        notice_data(tmp_path)
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.dev_lab.notices]\nentity = "Org"\nproduct = "P"\nin_tree = ["p"]\n'
        '[tool.dev_lab.notices.overrides]\nq = "MIT"\n',
        encoding='utf-8',
    )
    assert notice_data(tmp_path) == NoticeData(
        entity='Org', product='P', in_tree=frozenset({'p'}), overrides={'q': 'MIT'}
    )


def test_the_notice_lists_third_parties_and_never_the_product(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "p"\n', encoding='utf-8')
    rows = [{'name': 'numpy', 'version': '2.0', 'license': 'BSD-3-Clause', 'url': 'u'}]
    monkeypatch.setattr(notices, 'python_packages', lambda **_: rows)
    monkeypatch.setattr(notices, 'git_sources', lambda _declared: {})
    data = NoticeData(entity='Org', product='P', in_tree=frozenset({'p'}))
    notice = notices.build_notices(tmp_path, tmp_path / 'out', data)
    text = notice.read_text(encoding='utf-8')
    assert '| numpy | 2.0 | BSD-3-Clause | u |' in text
    assert 'P is © Org' in text
    assert (tmp_path / 'out' / 'index.html').is_file()
