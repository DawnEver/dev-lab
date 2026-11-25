"""NEVER-LOG-SECRETS: no output sink in this package interpolates a credential's value (hashes only).

The scan reads every tracked ``src/`` module; the planted controls show it convicts each sink shape and lets the
hashed, path-named and absent forms through.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev.secretlog import secret_interpolations

ROOT = Path(__file__).resolve().parents[1]
_FLOOR = 300


@pytest.mark.parametrize(
    'line',
    [
        "emit(f'login with {token}')",
        "print(f'key={self.api_key}')",
        'log.info(f\'fp {row["fingerprint"]}\')',
        "handle.write(f'{password}')",
    ],
)
def test_a_planted_secret_in_a_sink_is_convicted(line: str) -> None:
    """PLANTED CONTROL: each sink shape interpolating a secret-named value is a finding."""
    assert secret_interpolations(line) != ()


@pytest.mark.parametrize(
    'line',
    [
        "emit(f'login with {sha256(token)}')",
        "emit(f'token file {token_path}')",
        "emit(f'set {token_env} first')",
        "value = f'{token}'",
    ],
)
def test_the_sanctioned_forms_pass(line: str) -> None:
    """A wrapped value (a hash), a path or variable name, and a non-sink format are not findings."""
    assert secret_interpolations(line) == ()


def test_the_package_logs_no_secret() -> None:
    """THE CHECK, over every module of the package, with a floor so an unread tree cannot pass."""
    modules = sorted((ROOT / 'src').rglob('*.py'))
    assert len(modules) >= _FLOOR, f'read {len(modules)} modules; the scan read nothing'
    found = [
        f'{p.relative_to(ROOT)}:{line} {name}'
        for p in modules
        for line, name in secret_interpolations(p.read_text(encoding='utf-8'))
    ]
    assert found == [], 'a credential value reaches an output sink; log its hash:\n  ' + '\n  '.join(found)
