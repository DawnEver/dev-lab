"""ONE NEED REGISTRY (T2, 2026-11-24): a test declares its needs; a declared need found missing FAILS by name."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev import needs

pytest_plugins = ['pytester']

_MANIFEST = (
    '[project]\nname="example"\nversion="0"\n'
    '[project.optional-dependencies]\nplot=["matplotlib"]\nfast-io=["orjson"]\n'
    '[tool.lab_commons.tests]\nresources=["jmag", "windows", "extra_plot", "extra_fast_io", "data_meas"]\n'
    '[tool.dev_lab.needs]\ndata={meas="MEAS_ROOT"}\n'
)


def _root(tmp_path: Path, text: str = _MANIFEST) -> Path:
    (tmp_path / 'pyproject.toml').write_text(text, encoding='utf-8')
    return tmp_path


@pytest.mark.parametrize(
    ('spelled', 'kind', 'name', 'marker'),
    [
        ('jmag', 'tool', 'jmag', 'jmag'),
        ('os:windows', 'os', 'windows', 'windows'),
        ('extra:fast-io', 'extra', 'fast-io', 'extra_fast_io'),
        ('data:meas', 'data', 'meas', 'data_meas'),
    ],
)
def test_every_kind_parses_to_its_resource_marker(
    tmp_path: Path, spelled: str, kind: str, name: str, marker: str
) -> None:
    need = needs.parse(spelled, root=_root(tmp_path))
    assert (need.kind, need.name, need.marker) == (kind, name, marker)


@pytest.mark.parametrize(
    ('spelled', 'named'),
    [
        ('jmagg', "'jmagg'"),  # a typo of a tool: no CHECKS row
        ('os:beos', "'beos'"),
        ('extra:nope', "'nope'"),  # not in [project.optional-dependencies]
        ('data:attic', "'attic'"),  # not in [tool.dev_lab.needs] data
        ('gpu:a100', "'gpu'"),  # an unknown kind
    ],
)
def test_an_unregistered_need_is_refused_by_name(tmp_path: Path, spelled: str, named: str) -> None:
    with pytest.raises(needs.UnregisteredNeed, match=named):
        needs.parse(spelled, root=_root(tmp_path))


def test_a_registered_need_whose_marker_the_repo_does_not_declare_is_refused(tmp_path: Path) -> None:
    """Its test would land in ``base`` and run on every host: refused, naming the resources row to add."""
    root = _root(tmp_path)
    with pytest.raises(needs.UnregisteredNeed, match=r'femm.*\[tool\.lab_commons\.tests\] resources'):
        needs.parse('femm', root=root)


def test_presence_reads_each_kind(tmp_path: Path) -> None:
    """Each probe answers present AND absent -- the PLANTED CONTROL for every kind."""
    root = _root(tmp_path)
    store = tmp_path / 'store'
    store.mkdir()
    host = needs.Host(
        system='windows',
        tool=lambda tool: tool == 'jmag',
        installed=lambda dist: dist == 'matplotlib',
        environ={'MEAS_ROOT': str(store)},
    )
    assert host.missing(needs.parse('jmag', root=root), root=root) is None
    assert host.missing(needs.parse('os:windows', root=root), root=root) is None
    assert host.missing(needs.parse('extra:plot', root=root), root=root) is None
    assert host.missing(needs.parse('data:meas', root=root), root=root) is None
    bare = needs.Host(system='linux', tool=lambda _t: False, installed=lambda _d: False, environ={})
    assert 'jmag' in (bare.missing(needs.parse('jmag', root=root), root=root) or '')
    assert 'windows' in (bare.missing(needs.parse('os:windows', root=root), root=root) or '')
    assert 'matplotlib' in (bare.missing(needs.parse('extra:plot', root=root), root=root) or '')
    assert 'MEAS_ROOT' in (bare.missing(needs.parse('data:meas', root=root), root=root) or '')


_RUNNER_MANIFEST = (
    '[project]\nname="example"\nversion="0"\n[tool.lab_commons.tests]\nresources=["windows", "linux", "macos"]\n'
)


def test_a_missing_need_fails_never_skips(pytester: pytest.Pytester) -> None:
    """The run on a host that lacks a declared need FAILS that test naming the need; a present one passes."""
    pytester.makefile('.toml', pyproject=_RUNNER_MANIFEST)
    here = needs.Host.this().system
    other = next(name for name in ('windows', 'linux', 'macos') if name != here)
    pytester.makepyfile(
        f'from dev_lab.dev.needs import needs\n'
        f'@needs("os:{other}")\ndef test_elsewhere():\n    pass\n'
        f'@needs("os:{here}")\ndef test_here():\n    pass\n'
    )
    result = pytester.runpytest('-p', 'no:cacheprovider')
    result.assert_outcomes(passed=1, failed=1)
    result.stdout.fnmatch_lines([f'*need os:{other}*missing on this host*'])


def test_an_unregistered_need_on_a_test_is_refused_at_collection(pytester: pytest.Pytester) -> None:
    pytester.makefile('.toml', pyproject=_RUNNER_MANIFEST)
    pytester.makepyfile('from dev_lab.dev.needs import needs\n@needs("os:beos")\ndef test_x():\n    pass\n')
    result = pytester.runpytest('-p', 'no:cacheprovider')
    result.stderr.fnmatch_lines(["*test_x*'beos'*"])
    assert result.ret != 0
