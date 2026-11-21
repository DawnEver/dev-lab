"""A wedged test must END AS ITS OWN NAMED RED, never as the box wall killing the whole session.

MEASURED 2026-11-21, ci.yml run 44917070995 on integrate/main bf1b4cef: tests/base@windows ran
10,390 of 10,462 tests under ``-n 2``, printed nothing for 21 minutes, and the box wall (3600 s)
killed pytest -- exit 4294967295 (-1), no summary line, verdict INCONCLUSIVE, and NO TEST NAMED.
The kit's own pyproject says pytest-timeout is "the per-test ceiling every gate relies on", yet this
repo declared no ``timeout``: a declaration that lies. With the ceiling below the wall a wedge dies
inside its WORKER (Windows: ``thread`` method, ``os._exit(1)``), xdist files ``worker crashed while
running <nodeid>`` and restarts it, and the session survives to a verdict that names the test.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from dev_lab.dev.verifybox import declared_wall_s

ROOT = Path(__file__).resolve().parents[1]


def per_test_ceiling_refusal(root: Path) -> str:
    """Why *root* lets a wedged test reach the wall unnamed; ``''`` when its ceiling sits below the wall."""
    ini = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    ceiling = ini.get('tool', {}).get('pytest', {}).get('ini_options', {}).get('timeout')
    wall = declared_wall_s(root)
    if not isinstance(ceiling, int | float) or isinstance(ceiling, bool) or ceiling <= 0:
        return f'[tool.pytest.ini_options] declares no per-test timeout, so a wedge runs to the {wall} s wall unnamed'
    if ceiling >= wall:
        return f'per-test timeout {ceiling} s is not below the {wall} s wall, so the wall fires first, unnamed'
    return ''


def test_this_repo_names_a_wedged_test_before_the_wall_kills_the_session() -> None:
    assert per_test_ceiling_refusal(ROOT) == ''


@pytest.mark.parametrize(
    ('ini', 'says'),
    [
        ('[tool.pytest.ini_options]\ntestpaths = ["tests"]\n', 'declares no per-test timeout'),
        ('[tool.pytest.ini_options]\ntimeout = 3600\n', 'not below'),
        ('[tool.pytest.ini_options]\ntimeout = 0\n', 'declares no per-test timeout'),
    ],
)
def test_the_reading_refuses_a_repo_whose_wall_fires_first(tmp_path: Path, ini: str, says: str) -> None:
    # The planted control: the reading above can say no.
    (tmp_path / 'pyproject.toml').write_text(ini, encoding='utf-8')
    assert says in per_test_ceiling_refusal(tmp_path)
