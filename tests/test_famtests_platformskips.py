"""``dev_lab.dev.famtests.platformskips`` -- planted skips both ways, then the kit's own tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev.famtests.platformskips import PlatformSkip, assert_no_platform_skips, platform_skips

ROOT = Path(__file__).resolve().parents[1]

_PLANTED = """
import os, sys, platform, pytest

@pytest.mark.skipif(sys.platform != 'win32', reason='windows only')
def test_a(): ...

@pytest.mark.skipif(os.name == 'nt', reason='posix')
def test_b(): ...

pytestmark = pytest.mark.skipif(platform.system() == 'Darwin', reason='x')

def test_c():
    if sys.platform.startswith('linux'):
        pytest.skip('not here')

@pytest.mark.skipif(shutil.which('node') is None, reason='a tool, not an OS')
def test_tool(): ...

@pytest.mark.windows
def test_marked(): ...

def test_unguarded_skip():
    pytest.skip('unconditional')
"""


def test_a_planted_module_is_read_both_ways() -> None:
    """PLANTED: four platform skips red; a tool skipif, a marker and an unguarded skip stay green."""
    assert platform_skips(_PLANTED) == (4, 7, 10, 14)


def test_the_assertion_reds_names_the_declaration_and_floors(tmp_path: Path) -> None:
    """A skip reds naming the OS to declare; a declared OS drops that half; an empty scan reds."""
    (tmp_path / 'test_x.py').write_text(_PLANTED, encoding='utf-8')
    with pytest.raises(PlatformSkip, match=r"declare \['linux', 'macos', 'windows'\]"):
        assert_no_platform_skips(tests=tmp_path, pyproject='', floor=1)
    full = '[tool.lab_commons.tests]\nresources = ["linux", "macos", "windows"]\n'
    with pytest.raises(PlatformSkip, match=r'4 platform skip\(s\)') as caught:
        assert_no_platform_skips(tests=tmp_path, pyproject=full, floor=1)
    assert 'declare' not in str(caught.value)
    with pytest.raises(PlatformSkip, match='under the floor'):
        assert_no_platform_skips(tests=tmp_path, pyproject=full, floor=99)


def test_the_kits_own_tests_skip_on_no_platform() -> None:
    """The kit adopts its own row."""
    assert_no_platform_skips(
        tests=ROOT / 'tests', pyproject=(ROOT / 'pyproject.toml').read_text(encoding='utf-8'), floor=50
    )
